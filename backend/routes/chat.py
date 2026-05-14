"""Chat routes — HR Brain chatbot with SSE streaming."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.core.auth import get_current_user
from backend.core.database import (
    create_chat_session, add_chat_message, get_chat_messages,
    list_chat_sessions, get_position, list_positions,
    get_position_candidates, get_candidate, get_brain_entries,
    get_feedback_patterns, count_candidates,
)
from backend.core.config import (
    llm_call, CHAT_MODEL, LITE_MODEL,
    AGENT_NAME, AGENT_ROLE, AGENT_FOCUS, AGENT_PERSONALITY,
)
from backend.core.rate_limit import limiter


def _agent_v2_enabled() -> bool:
    return os.getenv("AGENT_V2", "false").strip().lower() in ("1", "true", "yes", "on")

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------
INTENT_KEYWORDS = {
    "find_candidates": ["find", "search", "candidates", "who", "show me", "top", "best", "match"],
    "compare": ["compare", "versus", "vs", "side by side", "difference"],
    "create_jd": ["create jd", "generate jd", "write jd", "job description", "draft jd"],
    "pipeline_status": ["pipeline", "status", "stage", "how many", "count", "funnel"],
    "generate_document": ["draft", "offer letter", "rejection", "email", "template", "scorecard"],
    "analytics": ["analytics", "metrics", "report", "average", "trend", "stats"],
    "general": [],
}


def classify_intent(message: str) -> str:
    """Quick keyword-based intent classification."""
    msg_lower = message.lower()
    scores = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        scores[intent] = sum(1 for kw in keywords if kw in msg_lower)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------
def sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Build agent instructions
# ---------------------------------------------------------------------------
def build_instructions(position: dict = None) -> str:
    """Build system prompt for HR Brain agent."""
    base = f"""You are {AGENT_NAME}, a {AGENT_ROLE}.
Personality: {AGENT_PERSONALITY}
Focus: {AGENT_FOCUS}

You help HR teams with:
- Finding and ranking candidates against job descriptions
- Creating and improving job descriptions
- Managing hiring pipelines
- Generating HR documents (offer letters, rejections, scorecards)
- Answering questions about candidates and positions
- Providing hiring analytics and insights

Always be data-driven, fair, and specific. Reference candidate names and scores when available.
Format responses in Markdown. Use tables for comparisons."""

    if position:
        base += f"""

CURRENT CONTEXT: Position "{position.get('title')}"
Department: {position.get('department', 'N/A')}
Required Skills: {', '.join(position.get('required_skills', []))}
Min Experience: {position.get('min_experience_years', 0)} years
Scoring Weights: Skills {position.get('weight_skills')}%, Experience {position.get('weight_experience')}%, Education {position.get('weight_education')}%, Certs {position.get('weight_certifications')}%, Industry {position.get('weight_industry')}%"""

    # Inject brain knowledge
    brain = get_brain_entries(position_id=position["id"] if position else None)
    if brain:
        base += "\n\nHR BRAIN KNOWLEDGE:\n"
        for entry in brain[:20]:
            base += f"- [{entry['category']}] {entry['key']}: {entry['value']}\n"

    # Inject feedback patterns
    patterns = get_feedback_patterns(position_id=position["id"] if position else None)
    if patterns.get("do"):
        base += "\n\nDO (learned from feedback):\n"
        for p in patterns["do"][:10]:
            base += f"- {p}\n"
    if patterns.get("avoid"):
        base += "\nAVOID (learned from feedback):\n"
        for p in patterns["avoid"][:10]:
            base += f"- {p}\n"

    return base


# ---------------------------------------------------------------------------
# Chat execution
# ---------------------------------------------------------------------------
async def execute_chat(message: str, session_id: int, position: dict = None,
                       user: dict = None):
    """Execute a chat turn and yield SSE events.

    When AGENT_V2=true, delegates to backend.agents.hr_agent.arun and translates
    its event stream into SSE. Old keyword path preserved verbatim below.
    """
    if _agent_v2_enabled():
        async for sse in _execute_chat_v2(message, session_id, position, user):
            yield sse
        return

    start = time.time()

    # Step 1: Intent classification
    intent = classify_intent(message)
    yield sse_event("status", {"step": "intent", "message": f"Intent: {intent}", "duration_ms": 0})

    # Step 2: Gather context based on intent
    context = ""

    if intent == "find_candidates" and position:
        yield sse_event("status", {"step": "searching", "message": "Searching candidates..."})
        candidates = get_position_candidates(position["id"], limit=10)
        if candidates:
            context += "\n\nCANDIDATES IN THIS POSITION (ranked by match):\n"
            for c in candidates:
                context += f"- {c.get('name')}: {c.get('match_score_composite', 'N/A')}% match, {c.get('current_role', 'N/A')}, Skills: {', '.join((c.get('skills_technical') or [])[:5])}\n"

    elif intent == "pipeline_status" and position:
        yield sse_event("status", {"step": "pipeline", "message": "Loading pipeline..."})
        from backend.core.database import get_pipeline_counts
        pipeline = get_pipeline_counts(position["id"])
        context += f"\n\nPIPELINE STATUS:\n"
        for stage, count in pipeline.items():
            context += f"- {stage}: {count}\n"

    elif intent in ("find_candidates", "analytics") and not position:
        yield sse_event("status", {"step": "overview", "message": "Loading overview..."})
        positions = list_positions()
        total_candidates = count_candidates()
        context += f"\n\nOVERVIEW:\nTotal candidates in repo: {total_candidates}\nOpen positions: {len(positions)}\n"
        for p in positions[:10]:
            context += f"- {p.get('title')}: {p.get('cv_count', 0)} CVs, avg match {p.get('avg_match', 'N/A')}%\n"

    elif intent == "compare" and position:
        yield sse_event("status", {"step": "comparing", "message": "Loading candidates for comparison..."})
        candidates = get_position_candidates(position["id"], limit=5)
        if candidates:
            context += "\n\nTOP CANDIDATES FOR COMPARISON:\n"
            for c in candidates:
                context += (
                    f"- {c.get('name')}: Composite {c.get('match_score_composite')}%, "
                    f"Skills {c.get('match_score_skills')}%, Exp {c.get('match_score_experience')}%, "
                    f"Edu {c.get('match_score_education')}%, Certs {c.get('match_score_certifications')}%, "
                    f"Industry {c.get('match_score_industry')}%\n"
                )

    # Step 3: Build prompt
    yield sse_event("status", {"step": "thinking", "message": "Generating response..."})

    instructions = build_instructions(position)
    history = get_chat_messages(session_id)
    history_text = ""
    for msg in history[-10:]:
        history_text += f"\n{msg['role'].upper()}: {msg['content']}"

    full_prompt = f"""{instructions}
{context}

CONVERSATION HISTORY:{history_text}

USER: {message}

Respond helpfully. Be specific and reference data when available."""

    # Step 4: LLM call
    response = llm_call(full_prompt, model=CHAT_MODEL, temperature=0.4, max_tokens=2000)
    if not response:
        response = "I apologize, I was unable to generate a response. Please try again."

    duration = round((time.time() - start) * 1000)

    # Step 5: Generate suggestions
    suggestions = await _generate_suggestions(message, response, position)

    # Save messages
    add_chat_message(session_id, "user", message)
    msg_id = add_chat_message(
        session_id, "assistant", response,
        sources=[], suggestions=suggestions, model_used=CHAT_MODEL,
    )

    # Yield final response
    yield sse_event("answer", {
        "content": response,
        "suggestions": suggestions,
        "model_used": CHAT_MODEL,
        "duration_ms": duration,
    })

    yield sse_event("done", {"duration_ms": duration})


async def _execute_chat_v2(message: str, session_id: int,
                           position: dict = None, user: dict = None):
    """AGENT_V2 path — drive the Agno-based HR agent and emit SSE events."""
    from backend.agents.hr_agent import arun as agent_arun

    start = time.time()
    user = user or {"user_id": None, "role": "viewer", "tenant_id": 0}
    final_text = ""
    model_used = None
    suggestions: list[str] = []

    yield sse_event("status", {"step": "agent_v2", "message": "Agent v2 starting..."})

    # Persist user message up-front
    try:
        add_chat_message(session_id, "user", message)
    except Exception as e:
        logger.warning(f"add_chat_message(user) failed: {e}")

    try:
        async for evt in agent_arun(message, session_id, user, position=position):
            ename = evt.get("event")
            data = evt.get("data") or {}
            if ename == "answer":
                final_text = data.get("content", "") or ""
                model_used = data.get("model_used")
                suggestions = data.get("suggestions") or []
                yield sse_event("answer", {
                    "content": final_text,
                    "suggestions": suggestions,
                    "model_used": model_used,
                    "duration_ms": round((time.time() - start) * 1000),
                    "run_id": data.get("run_id"),
                })
            elif ename == "done":
                yield sse_event("done", {
                    "duration_ms": round((time.time() - start) * 1000),
                    **data,
                })
            else:
                # status / tool_call / tool_result / step pass through
                yield sse_event(ename or "status", data)
    except Exception as e:
        logger.exception("agent v2 execution failed")
        yield sse_event("answer", {
            "content": f"Agent v2 error: {type(e).__name__}: {e}",
            "suggestions": [], "model_used": None,
            "duration_ms": round((time.time() - start) * 1000),
        })
        yield sse_event("done", {"status": "error",
                                  "duration_ms": round((time.time() - start) * 1000)})
        return

    # Save assistant final
    try:
        add_chat_message(
            session_id, "assistant", final_text or "(no response)",
            sources=[], suggestions=suggestions, model_used=model_used,
        )
    except Exception as e:
        logger.warning(f"add_chat_message(assistant) failed: {e}")


async def _generate_suggestions(question: str, answer: str, position: dict = None) -> list[str]:
    """Generate follow-up question suggestions."""
    context = f"Position: {position['title']}" if position else "Global HR Brain"
    prompt = f"""Based on this Q&A, suggest 3 natural follow-up questions the user might ask.
Context: {context}
Q: {question}
A: {answer[:500]}

Return exactly 3 suggestions, one per line. Keep them short (under 60 chars)."""

    result = llm_call(prompt, model=LITE_MODEL, temperature=0.5, max_tokens=200)
    if not result:
        return []

    lines = [l.strip().lstrip("0123456789.-) ") for l in result.strip().split("\n") if l.strip()]
    return lines[:3]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/")
@limiter.limit("30/minute")
async def chat_global(request: Request):
    """Global HR Brain chat — SSE streaming."""
    user = get_current_user(request)
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id")

    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    if not session_id:
        session_id = create_chat_session(
            user_id=user.get("user_id"),
            title=message[:100],
        )

    return StreamingResponse(
        execute_chat(message, session_id, user=user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Session-Id": str(session_id)},
    )


@router.post("/position/{slug}")
@limiter.limit("30/minute")
async def chat_position(slug: str, request: Request):
    """Position-scoped HR Brain chat — SSE streaming."""
    user = get_current_user(request)
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id")

    if not message:
        raise HTTPException(status_code=400, detail="Message required")

    position = get_position(slug)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    if not session_id:
        session_id = create_chat_session(
            user_id=user.get("user_id"),
            position_id=position["id"],
            title=f"{position['title']}: {message[:80]}",
        )

    return StreamingResponse(
        execute_chat(message, session_id, position=position, user=user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Session-Id": str(session_id)},
    )


@router.get("/sessions")
async def list_sessions_route(
    request: Request,
    position_id: Optional[int] = Query(None),
):
    """List chat sessions."""
    user = get_current_user(request)
    sessions = list_chat_sessions(
        user_id=user.get("user_id"),
        position_id=position_id,
    )
    return {"sessions": sessions}


@router.get("/sessions/{session_id}/messages")
async def get_messages_route(session_id: int, request: Request):
    """Get messages for a chat session."""
    get_current_user(request)
    messages = get_chat_messages(session_id)
    return {"messages": messages}


@router.post("/sessions/{session_id}/feedback")
async def submit_feedback(session_id: int, request: Request):
    """Submit thumbs up/down feedback on a message."""
    user = get_current_user(request)
    body = await request.json()

    message_id = body.get("message_id")
    feedback = body.get("feedback")  # "thumbs_up" or "thumbs_down"

    if feedback not in ("thumbs_up", "thumbs_down"):
        raise HTTPException(status_code=400, detail="Invalid feedback")

    from backend.core.database import get_cursor
    with get_cursor() as cur:
        cur.execute(
            "UPDATE chat_messages SET feedback = %s WHERE id = %s AND session_id = %s",
            (feedback, message_id, session_id),
        )

    # Extract learning pattern from feedback
    if feedback == "thumbs_down":
        with get_cursor() as cur:
            cur.execute("SELECT content FROM chat_messages WHERE id = %s", (message_id,))
            row = cur.fetchone()
            if row:
                # Save as AVOID pattern
                cur.execute("""
                    INSERT INTO hr_brain_learnings (type, pattern, context, confidence, source_agent)
                    VALUES ('learned_negative', %s, %s, 0.5, 'chat_feedback')
                """, (f"Response was not helpful: {row[0][:200]}", f"session_{session_id}"))

    return {"message": "Feedback recorded"}

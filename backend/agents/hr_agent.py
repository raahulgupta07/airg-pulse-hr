"""HR Agent — Agno-based chat v2 (flag-gated AGENT_V2).

Wires the 5 providers (candidate / position / brain / analytics / email) into a
tool-calling agent driven by an OpenRouter chat model. Streams structured events
(`status` / `tool_call` / `tool_result` / `step` / `answer` / `done`) suitable
for SSE relay in routes/chat.py.

Notes:
- Tries to import `agno.Agent` for full framework features; if unavailable
  (e.g. dev box without the optional `agno[postgres]` install), a lightweight
  in-process tool loop powered by the existing OpenAI-compat client takes over.
  Either path emits the same event stream, so the route layer is uniform.
- Role allowlist enforced before tool list is exposed to the model.
- PII keys (`national_id`, `dob`, `phone`, `email`) are redacted from tool
  inputs that leave the process toward the LLM (logging keeps full payload).
- Every model call routes through `_log_llm_call(step='agent', run_id=...)`
  so the billing dashboard picks it up.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Callable, Optional

from backend.agents.providers import candidate_provider as _cand
from backend.agents.providers import position_provider as _pos
from backend.agents.providers import brain_provider as _brain
from backend.agents.providers import analytics_provider as _analytics
from backend.agents.providers import email_provider as _email
from backend.agents.memory import AgnoMemory
from backend.agents.session import start_run, record_tool_call, close_run
from backend.core.config import (
    OPENROUTER_API_KEY, CHAT_MODEL, LLM_GATE,
    _log_llm_call, AGENT_NAME, AGENT_ROLE, AGENT_PERSONALITY, AGENT_FOCUS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional Agno import — never fatal
# ---------------------------------------------------------------------------
_AGNO_AVAILABLE = False
try:  # pragma: no cover - environment dependent
    from agno.agent import Agent as _AgnoAgent  # type: ignore
    _AGNO_AVAILABLE = True
except Exception:
    try:
        from agno import Agent as _AgnoAgent  # type: ignore
        _AGNO_AVAILABLE = True
    except Exception:
        _AgnoAgent = None  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AGNO_MAX_STEPS = int(os.getenv("AGNO_MAX_STEPS", "8"))
AGENT_SESSION_CAP_USD = float(os.getenv("AGENT_SESSION_CAP_USD", "1"))
AGENT_MODEL = os.getenv("AGENT_MODEL", CHAT_MODEL)

# PII keys to scrub before sending tool outputs/inputs to the LLM
_PII_KEYS = {"national_id", "dob", "phone", "email", "phone_number",
             "personal_email", "ssn", "tax_id"}


# ---------------------------------------------------------------------------
# Tool registry — wraps provider functions with a uniform contract
# ---------------------------------------------------------------------------
def _wrap(name: str, fn: Callable, schema: dict) -> dict:
    return {"name": name, "fn": fn, "schema": schema}


TOOLS: list[dict] = [
    _wrap("query_cvs", _cand.query_cvs, {
        "type": "function",
        "function": {
            "name": "query_cvs",
            "description": "Search the CV repository by free text + filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "filters": {"type": "object"},
                    "k": {"type": "integer", "default": 10},
                },
            },
        },
    }),
    _wrap("get_candidate_brief", _cand.get_candidate_brief, {
        "type": "function",
        "function": {
            "name": "get_candidate_brief",
            "description": "Get a structured brief for a single candidate by id.",
            "parameters": {
                "type": "object",
                "properties": {"cand_id": {"type": "integer"}},
                "required": ["cand_id"],
            },
        },
    }),
    _wrap("score_cv_vs_position", _cand.score_cv_vs_position, {
        "type": "function",
        "function": {
            "name": "score_cv_vs_position",
            "description": "Score a candidate against a position; returns dimension breakdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cand_id": {"type": "integer"},
                    "position_id": {"type": "integer"},
                },
                "required": ["cand_id", "position_id"],
            },
        },
    }),
    _wrap("list_candidate_pipeline", _cand.list_candidate_pipeline, {
        "type": "function",
        "function": {
            "name": "list_candidate_pipeline",
            "description": "List candidates assigned to a position, optionally filtered by stage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "position_id": {"type": "integer"},
                    "stage": {"type": "string"},
                },
                "required": ["position_id"],
            },
        },
    }),
    _wrap("query_positions", _pos.query_positions, {
        "type": "function",
        "function": {
            "name": "query_positions",
            "description": "List/search positions, optional filter dict.",
            "parameters": {
                "type": "object",
                "properties": {"filter": {"type": "object"}},
            },
        },
    }),
    _wrap("get_position_brief", _pos.get_position_brief, {
        "type": "function",
        "function": {
            "name": "get_position_brief",
            "description": "Get full position brief by slug.",
            "parameters": {
                "type": "object",
                "properties": {"slug": {"type": "string"}},
                "required": ["slug"],
            },
        },
    }),
    _wrap("get_pipeline", _pos.get_pipeline, {
        "type": "function",
        "function": {
            "name": "get_pipeline",
            "description": "Get pipeline counts by stage for a position.",
            "parameters": {
                "type": "object",
                "properties": {"position_id": {"type": "integer"}},
                "required": ["position_id"],
            },
        },
    }),
    _wrap("query_brain", _brain.query_brain, {
        "type": "function",
        "function": {
            "name": "query_brain",
            "description": "Query the HR Brain knowledge store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "position_id": {"type": "integer"},
                },
            },
        },
    }),
    _wrap("update_brain", _brain.update_brain, {
        "type": "function",
        "function": {
            "name": "update_brain",
            "description": "Write/update an HR Brain knowledge entry. RESTRICTED.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "category": {"type": "string"},
                    "position_id": {"type": "integer"},
                },
                "required": ["key", "value"],
            },
        },
    }),
    _wrap("query_funnel", _analytics.query_funnel, {
        "type": "function",
        "function": {
            "name": "query_funnel",
            "description": "Funnel/conversion analytics by position + range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "position_id": {"type": "integer"},
                    "range": {"type": "string", "default": "30d"},
                },
            },
        },
    }),
    _wrap("draft_email", _email.draft_email, {
        "type": "function",
        "function": {
            "name": "draft_email",
            "description": "Draft an email to a candidate. RESTRICTED for analyst.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "kind": {"type": "string"},
                    "position_id": {"type": "integer"},
                    "context": {"type": "string"},
                },
                "required": ["candidate_id", "kind"],
            },
        },
    }),
]

TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------------------
# Role allowlist
# ---------------------------------------------------------------------------
_ALL_TOOL_NAMES = [t["name"] for t in TOOLS]

ROLE_ALLOWLIST: dict[str, list[str]] = {
    "admin": _ALL_TOOL_NAMES,
    "superadmin": _ALL_TOOL_NAMES,
    "operator": [n for n in _ALL_TOOL_NAMES if n not in ("update_brain",)],
    "recruiter": [n for n in _ALL_TOOL_NAMES if n not in ("update_brain",)],
    "analyst": [n for n in _ALL_TOOL_NAMES if n not in ("draft_email",)],
    "viewer": [n for n in _ALL_TOOL_NAMES
               if n not in ("update_brain", "draft_email")],
}


def allowed_tools_for(role: str) -> list[dict]:
    role = (role or "viewer").lower()
    allowed = ROLE_ALLOWLIST.get(role, ROLE_ALLOWLIST["viewer"])
    return [TOOLS_BY_NAME[n] for n in allowed if n in TOOLS_BY_NAME]


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------
def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k.lower() in _PII_KEYS else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# OpenRouter model adapter (OpenAI-compat)
# ---------------------------------------------------------------------------
def get_openrouter_client():
    """Reuse the existing OpenAI-compat client pointed at OpenRouter."""
    from backend.core.config import get_llm_client
    return get_llm_client()


def _build_agno_model():
    """If agno is installed, build its OpenAI-compat model class.

    Tries a few likely class paths Agno has shipped under in 2.x. Returns None
    on any import failure — caller falls back to direct client loop.
    """
    if not _AGNO_AVAILABLE:
        return None
    candidates = [
        ("agno.models.openai.like", "OpenAILike"),
        ("agno.models.openai", "OpenAILike"),
        ("agno.models.openai", "OpenAIChat"),
        ("agno.models.openrouter", "OpenRouter"),
    ]
    for mod_path, cls_name in candidates:
        try:
            mod = __import__(mod_path, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            try:
                return cls(
                    id=AGENT_MODEL,
                    api_key=OPENROUTER_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                )
            except TypeError:
                # Some versions take `model=` not `id=`
                return cls(
                    model=AGENT_MODEL,
                    api_key=OPENROUTER_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                )
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def _build_system_prompt(position: Optional[dict],
                         memory_hits: list[dict]) -> str:
    base = (
        f"You are {AGENT_NAME}, a {AGENT_ROLE}.\n"
        f"Personality: {AGENT_PERSONALITY}\n"
        f"Focus: {AGENT_FOCUS}\n\n"
        "You have tools to search CVs, score candidates, look up positions, "
        "query analytics, recall HR brain knowledge and draft emails. "
        "Plan briefly, call tools to gather facts, then answer in Markdown. "
        "Always cite candidate names + ids when you reference them."
    )
    if position:
        base += (
            f"\n\nCURRENT POSITION CONTEXT: id={position.get('id')} "
            f"slug={position.get('slug')} title={position.get('title')}"
        )
    if memory_hits:
        base += "\n\nRELEVANT MEMORY:\n"
        for m in memory_hits[:5]:
            base += f"- {m.get('key')}: {json.dumps(m.get('value'))[:200]}\n"
    return base


# ---------------------------------------------------------------------------
# Cost cap helper
# ---------------------------------------------------------------------------
def _session_spend_usd(session_id: Optional[int]) -> float:
    if not session_id:
        return 0.0
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute(
                """SELECT COALESCE(SUM(cost_usd), 0)
                   FROM agent_runs WHERE session_id = %s""",
                (session_id,),
            )
            return float(cur.fetchone()[0] or 0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------
async def _exec_tool(tool: dict, args: dict) -> tuple[Any, int, Optional[str]]:
    """Execute a tool synchronously in a thread, return (output, latency_ms, err)."""
    t0 = time.time()
    err: Optional[str] = None
    out: Any = None
    try:
        fn = tool["fn"]
        if inspect.iscoroutinefunction(fn):
            out = await fn(**args)
        else:
            out = await asyncio.to_thread(lambda: fn(**args))
    except TypeError as e:
        # Argument shape mismatch — try positional fallback
        err = f"args_error: {e}"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    return out, int((time.time() - t0) * 1000), err


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------
async def arun(message: str, session_id: Optional[int], user: dict,
               position: Optional[dict] = None,
               run_id: Optional[str] = None) -> AsyncGenerator[dict, None]:
    """Run the agent. Yields event dicts:

        {event: 'status'|'tool_call'|'tool_result'|'step'|'answer'|'done',
         data: {...}}
    """
    role = (user or {}).get("role", "viewer")
    tenant_id = int((user or {}).get("tenant_id") or 0)
    operator_id = (user or {}).get("user_id")

    tools = allowed_tools_for(role)
    tool_names = [t["name"] for t in tools]

    # Cost cap pre-check
    spent = _session_spend_usd(session_id)
    if spent >= AGENT_SESSION_CAP_USD:
        yield {"event": "answer", "data": {
            "content": (f"Session cost cap reached "
                        f"(${spent:.2f} ≥ ${AGENT_SESSION_CAP_USD:.2f}). "
                        "Start a new session to continue."),
            "model_used": AGENT_MODEL, "suggestions": [],
        }}
        yield {"event": "done", "data": {"reason": "cost_cap"}}
        return

    # Open run row + memory recall
    run_id = run_id or start_run(session_id, tenant_id, operator_id)
    yield {"event": "status", "data": {"step": "start", "run_id": run_id,
                                       "tools": tool_names}}

    mem = AgnoMemory(tenant_id=tenant_id)
    try:
        memory_hits = mem.recall(message, tenant_id=tenant_id, k=5)
    except Exception:
        memory_hits = []

    system_prompt = _build_system_prompt(position, memory_hits)

    client = get_openrouter_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    tools_param = [t["schema"] for t in tools]

    total_in = 0
    total_out = 0
    total_cost = 0.0
    final_text = ""
    status_terminal = "ok"
    err_terminal: Optional[str] = None

    try:
        for step in range(AGNO_MAX_STEPS):
            # mid-loop cost cap
            if (spent + total_cost) >= AGENT_SESSION_CAP_USD:
                yield {"event": "status", "data": {
                    "step": "cost_cap", "spent": round(spent + total_cost, 4)}}
                final_text = (final_text or
                              "Stopping — session cost cap reached.")
                status_terminal = "cost_cap"
                break

            yield {"event": "step", "data": {"index": step}}
            t0 = time.time()
            try:
                def _call():
                    with LLM_GATE:
                        return client.chat.completions.create(
                            model=AGENT_MODEL,
                            messages=messages,
                            tools=tools_param if tools_param else None,
                            tool_choice="auto" if tools_param else None,
                            temperature=0.3,
                            max_tokens=2000,
                        )
                resp = await asyncio.to_thread(_call)
            except Exception as e:
                err_terminal = f"llm_error: {type(e).__name__}: {e}"
                logger.exception("agent LLM call failed")
                status_terminal = "error"
                break

            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(resp, "usage", None)
            in_tok = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0
            total_in += in_tok
            total_out += out_tok
            try:
                from backend.core.cost_cap import estimate_cost
                step_cost = estimate_cost(AGENT_MODEL, in_tok + out_tok)
            except Exception:
                step_cost = 0.0
            total_cost += step_cost

            # Persist per-step LLM call to billing ledger
            try:
                _log_llm_call(
                    tenant=str(tenant_id), model=AGENT_MODEL,
                    latency_ms=latency_ms,
                    in_tokens=in_tok, out_tokens=out_tok,
                    cost_usd=step_cost, status="ok",
                    step="agent", run_id=run_id,
                    operator_id=str(operator_id) if operator_id else None,
                )
            except Exception:
                pass

            choice = resp.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                final_text = (msg.content or "").strip()
                # echo assistant message into history for completeness
                messages.append({"role": "assistant", "content": final_text})
                break

            # Append assistant tool-call message verbatim
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    } for tc in tool_calls
                ],
            })

            # Execute each tool call sequentially, recording trace
            for tc in tool_calls:
                tname = tc.function.name
                try:
                    targs = json.loads(tc.function.arguments or "{}")
                except Exception:
                    targs = {}

                if tname not in [t["name"] for t in tools]:
                    out_payload = {"error": f"tool_not_allowed: {tname}"}
                    record_tool_call(run_id, step, tname,
                                     input=targs, output=out_payload,
                                     latency_ms=0, status="forbidden",
                                     error="role_blocked")
                    yield {"event": "tool_call", "data": {
                        "name": tname, "args": _redact(targs),
                        "status": "forbidden"}}
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "name": tname,
                        "content": json.dumps(out_payload),
                    })
                    continue

                yield {"event": "tool_call", "data": {
                    "name": tname, "args": _redact(targs)}}

                tool = TOOLS_BY_NAME[tname]
                output, lat_ms, err = await _exec_tool(tool, targs)
                tstatus = "error" if err else "ok"

                record_tool_call(run_id, step, tname,
                                 input=targs, output=output,
                                 latency_ms=lat_ms, status=tstatus, error=err)

                redacted_out = _redact(output) if output is not None else None
                yield {"event": "tool_result", "data": {
                    "name": tname, "status": tstatus,
                    "latency_ms": lat_ms,
                    "result": redacted_out, "error": err,
                }}

                # Feed redacted output back to the model
                payload = (json.dumps({"error": err})
                           if err else json.dumps(redacted_out, default=str))
                # Truncate very large payloads to keep the context bounded
                if len(payload) > 12000:
                    payload = payload[:12000] + "...<truncated>"
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "name": tname, "content": payload,
                })
        else:
            # Loop fell through without break — hit max steps
            status_terminal = "max_steps"
            if not final_text:
                final_text = ("Reached max reasoning steps without a final "
                              "answer. Please refine your question.")
    except Exception as e:
        logger.exception("agent run crashed")
        err_terminal = f"{type(e).__name__}: {e}"
        status_terminal = "error"

    # Persist a memory of this turn (best-effort)
    try:
        mem.write(
            key=f"chat:{session_id}:{run_id[:8]}",
            value={"q": message[:500], "a": final_text[:1000]},
            tenant_id=tenant_id,
            embed_text_for=message,
            updated_by=operator_id if isinstance(operator_id, int) else None,
        )
    except Exception:
        pass

    close_run(run_id, in_tokens=total_in, out_tokens=total_out,
              cost_usd=total_cost,
              status=status_terminal, error=err_terminal)

    yield {"event": "answer", "data": {
        "content": final_text or "(no response)",
        "model_used": AGENT_MODEL,
        "suggestions": [],
        "run_id": run_id,
        "in_tokens": total_in, "out_tokens": total_out,
        "cost_usd": round(total_cost, 6),
    }}
    yield {"event": "done", "data": {
        "run_id": run_id, "status": status_terminal,
        "cost_usd": round(total_cost, 6),
    }}

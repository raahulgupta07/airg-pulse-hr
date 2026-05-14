"""Email provider — drafts only (no send).

Sending happens via /api/emails/send (existing) after user review in UI.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from backend.core.config import CHAT_MODEL, llm_call
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supported draft types and per-type prompt guidance
# ---------------------------------------------------------------------------
_VALID_TYPES = ("rejection", "offer", "follow_up", "screening_request")

_TYPE_GUIDELINES: dict[str, str] = {
    "rejection": (
        "Write a personalized, empathetic rejection email.\n"
        "- Be warm, respectful, and specific — avoid generic boilerplate.\n"
        "- Reference something positive about the candidate's application.\n"
        "- Encourage them to apply for future roles.\n"
        "- Keep it concise (3-4 short paragraphs)."
    ),
    "offer": (
        "Write a warm, exciting job offer email.\n"
        "- Express genuine excitement about the candidate joining the team.\n"
        "- Mention the role and what makes it special.\n"
        "- Include salary and start date if provided in extra context.\n"
        "- Mention next steps (formal offer letter, onboarding).\n"
        "- 3-4 paragraphs."
    ),
    "follow_up": (
        "Write a polite follow-up / status-check email to the candidate.\n"
        "- Acknowledge time elapsed since last contact.\n"
        "- Provide whatever update is appropriate (still under review, next step coming, etc.).\n"
        "- Invite questions and keep the relationship warm.\n"
        "- Short — 2 paragraphs."
    ),
    "screening_request": (
        "Write a friendly screening-call request email.\n"
        "- Thank them for their interest in the role.\n"
        "- Explain that the next step is a brief screening conversation (15-30 min) with the recruiter.\n"
        "- Ask for 2-3 time slots that work in the next several days.\n"
        "- Mention what topics will be covered (background, motivation, logistics).\n"
        "- 2-3 short paragraphs."
    ),
}

_DEFAULT_SUBJECTS: dict[str, str] = {
    "rejection": "Update on your application",
    "offer": "An offer from our team",
    "follow_up": "Following up on your application",
    "screening_request": "Quick screening call?",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _fetch_candidate(cur, candidate_id: int) -> Optional[dict]:
    cur.execute(
        """SELECT id, name, email, "current_role", "current_company"
           FROM candidates WHERE id = %s""",
        (candidate_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _fetch_position(cur, position_id: int) -> Optional[dict]:
    cur.execute(
        "SELECT id, title, department FROM positions WHERE id = %s",
        (position_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _strip_code_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Public: draft_email
# ---------------------------------------------------------------------------
def draft_email(
    type: str,
    candidate_id: int,
    position_id: int = None,
    tone: str = "professional",
    extra_context: str = "",
) -> dict:
    """Draft an email for the given candidate and type. Does NOT send.

    type: 'rejection' | 'offer' | 'follow_up' | 'screening_request'

    Returns: {subject, body, type, candidate_id}
             On error: {error: str, type, candidate_id}
    """
    if type not in _VALID_TYPES:
        return {
            "error": f"invalid type '{type}'. Must be one of: {', '.join(_VALID_TYPES)}",
            "type": type,
            "candidate_id": candidate_id,
        }

    with get_cursor() as cur:
        cand = _fetch_candidate(cur, candidate_id)
        if not cand:
            return {
                "error": f"candidate {candidate_id} not found",
                "type": type,
                "candidate_id": candidate_id,
            }

        pos = _fetch_position(cur, position_id) if position_id else None
        if position_id and not pos:
            return {
                "error": f"position {position_id} not found",
                "type": type,
                "candidate_id": candidate_id,
            }

    candidate_name = cand.get("name") or "Candidate"
    position_title = (pos or {}).get("title", "the role")
    department = (pos or {}).get("department") or "N/A"
    current_role = cand.get("current_role") or "N/A"
    current_company = cand.get("current_company") or "N/A"

    guidelines = _TYPE_GUIDELINES[type]
    prompt = f"""{guidelines}

Candidate Name: {candidate_name}
Candidate Current Role: {current_role}
Candidate Current Company: {current_company}
Position: {position_title}
Department: {department}
Tone: {tone}
Additional context from recruiter: {extra_context or 'None provided'}

Return ONLY valid JSON with this exact shape (no commentary, no code fences):
{{"subject": "string", "body": "string (HTML formatted, use <p> tags between paragraphs)"}}"""

    raw = llm_call(prompt, model=CHAT_MODEL, temperature=0.4, max_tokens=2000)
    if not raw:
        return {
            "error": "LLM unavailable or returned empty response",
            "type": type,
            "candidate_id": candidate_id,
        }

    try:
        result = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as e:
        logger.warning(f"draft_email: LLM returned invalid JSON: {e}")
        # Soft fallback — surface the raw text as the body so the agent still has something usable.
        return {
            "subject": _DEFAULT_SUBJECTS[type],
            "body": raw.strip(),
            "type": type,
            "candidate_id": candidate_id,
            "warning": "LLM output was not valid JSON; raw text returned as body",
        }

    subject = result.get("subject") or _DEFAULT_SUBJECTS[type]
    body = result.get("body") or ""

    return {
        "subject": subject,
        "body": body,
        "type": type,
        "candidate_id": candidate_id,
    }


# ---------------------------------------------------------------------------
# Public: list_email_templates
# ---------------------------------------------------------------------------
def list_email_templates() -> list[dict]:
    """List available email templates.

    Tries the `templates` table first (rows whose category matches an email type).
    Falls back to a hardcoded list of the 5 supported draft types.
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, name, category, tone, usage_count
                   FROM templates
                   WHERE category IN (
                       'rejection_email', 'offer_letter',
                       'follow_up', 'screening_request', 'rejection', 'offer'
                   )
                   ORDER BY usage_count DESC NULLS LAST
                   LIMIT 200"""
            )
            rows = cur.fetchall()
            if rows:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        # Table may be missing on a fresh install — fall through to hardcoded list.
        logger.debug(f"list_email_templates: templates query failed ({e}); using hardcoded list")

    return [
        {"type": "rejection",         "name": "Rejection Email",         "description": "Empathetic decline after screen."},
        {"type": "offer",             "name": "Offer Email",             "description": "Warm offer announcement with role + comp summary."},
        {"type": "follow_up",         "name": "Follow-up / Status",      "description": "Polite check-in when there has been a delay."},
        {"type": "screening_request", "name": "Screening Call Request",  "description": "Ask for time slots for a 15-30 min recruiter screen."},
    ]

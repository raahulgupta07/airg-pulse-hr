"""Interview kit generator — produces interview questions per position (generic) or per candidate (tailored)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.core.config import llm_call, LITE_MODEL

logger = logging.getLogger(__name__)

AUDIENCES = {"HR_BP", "HIRING_MGR", "PANEL", "TECH"}
STAGES = {"SCREEN", "TECH", "ONSITE", "FINAL"}
GENERIC_CATEGORIES = ["BEHAVIORAL", "TECHNICAL", "CULTURE", "ROLE_SPECIFIC"]
TAILORED_CATEGORIES = ["GAP_PROBE", "STRENGTH_VERIFY", "BEHAVIORAL", "CULTURE"]


def _audience_focus(audience: str) -> str:
    return {
        "HR_BP": "motivation, communication, culture-fit, salary alignment, notice period, soft skills. Avoid deep technical drills.",
        "HIRING_MGR": "ownership, scope of past work, leadership, prioritization, tradeoffs. Light technical, heavy decision-making.",
        "PANEL": "cross-functional collaboration, conflict, stakeholder mgmt, scenario-based.",
        "TECH": "deep technical depth, system design, code reasoning, architecture trade-offs.",
    }.get(audience, "balanced screening")


def _stage_depth(stage: str) -> str:
    return {
        "SCREEN": "30-min phone screen — fast filter questions. No whiteboarding.",
        "TECH": "60-min technical deep-dive. Probe specifics.",
        "ONSITE": "panel onsite. Scenario + behavioral + system design mix.",
        "FINAL": "exec/final round. Vision, culture-fit, longevity, comp.",
    }.get(stage, "general")


def _parse_json(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            return []
        data = json.loads(m.group())
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            q = (item.get("question") or "").strip()
            if not q:
                continue
            out.append({
                "question": q[:1000],
                "category": (item.get("category") or "BEHAVIORAL").upper().replace(" ", "_"),
                "look_for": [str(x)[:200] for x in (item.get("look_for") or [])][:6],
                "red_flags": [str(x)[:200] for x in (item.get("red_flags") or [])][:6],
            })
        return out
    except Exception as e:
        logger.warning(f"[interview-kit] parse failed: {e}")
        return []


def generate_generic(
    position_title: str,
    jd_text: str,
    audience: str,
    stage: str,
    count: int = 8,
) -> list[dict]:
    """Generate question bank for a position (no specific candidate)."""
    audience = audience if audience in AUDIENCES else "HR_BP"
    stage = stage if stage in STAGES else "SCREEN"
    cats = ", ".join(GENERIC_CATEGORIES)

    prompt = f"""You are designing an interview question kit.

ROLE: {position_title}
INTERVIEWER ROLE: {audience} — focus on: {_audience_focus(audience)}
STAGE: {stage} — {_stage_depth(stage)}
NUMBER OF QUESTIONS: {count}

For each question, also give the interviewer:
- look_for: 2-4 bullets of strong-answer signals
- red_flags: 1-3 bullets of weak-answer signals

Categories to draw from: {cats}

Return ONLY a JSON array, no prose:
[
  {{
    "question": "Tell me about a time you...",
    "category": "BEHAVIORAL",
    "look_for": ["ownership", "metric-driven outcome"],
    "red_flags": ["blames team", "vague timeline"]
  }}
]

JOB DESCRIPTION:
{(jd_text or '')[:6000]}
"""
    raw = llm_call(prompt, model=LITE_MODEL, temperature=0.4, max_tokens=2500)
    return _parse_json(raw)


def generate_tailored(
    position_title: str,
    jd_text: str,
    candidate: dict[str, Any],
    match: dict[str, Any],
    audience: str,
    stage: str,
    count: int = 6,
) -> list[dict]:
    """Generate questions tailored to specific candidate using match gaps + strengths."""
    audience = audience if audience in AUDIENCES else "HR_BP"
    stage = stage if stage in STAGES else "SCREEN"

    cv_summary = candidate.get("ai_summary") or candidate.get("summary") or ""
    name = candidate.get("name") or "the candidate"
    role = candidate.get("current_role") or "N/A"
    yrs = candidate.get("total_experience_years") or candidate.get("years_experience") or 0
    skills = candidate.get("skills") or []
    if isinstance(skills, list):
        skills_str = ", ".join(str(s) for s in skills[:30])
    else:
        skills_str = str(skills)[:500]

    gaps = match.get("gaps") or match.get("skills_missing") or []
    strengths = match.get("top_strengths") or match.get("skills_matched") or []
    composite = match.get("match_score_composite") or 0
    explanation = match.get("match_explanation") or ""

    cats = ", ".join(TAILORED_CATEGORIES)

    prompt = f"""You are designing a tailored interview kit for a SPECIFIC candidate.

ROLE: {position_title}
INTERVIEWER: {audience} — focus on: {_audience_focus(audience)}
STAGE: {stage} — {_stage_depth(stage)}

CANDIDATE: {name}
CURRENT ROLE: {role} · {yrs} yrs exp
TOP SKILLS: {skills_str}
CV SUMMARY: {(cv_summary or '')[:1500]}

MATCH SCORE: {composite}%
STRENGTHS vs ROLE: {', '.join(str(s) for s in strengths[:8]) or '(none)'}
GAPS vs ROLE: {', '.join(str(g) for g in gaps[:8]) or '(none)'}
WHY THE SCORE: {explanation[:500]}

Generate {count} questions that:
- GAP_PROBE: directly probe each gap above ("CV light on X. Walk me thru...")
- STRENGTH_VERIFY: verify their claimed strengths are real ("CV says 5yr Y. Design Z.")
- BEHAVIORAL/CULTURE: round out for the stage

Categories to use: {cats}

For each question, also include:
- look_for: 2-4 strong-answer signals
- red_flags: 1-3 weak-answer signals

Return ONLY a JSON array, no prose:
[
  {{"question": "...", "category": "GAP_PROBE", "look_for": [...], "red_flags": [...]}}
]
"""
    raw = llm_call(prompt, model=LITE_MODEL, temperature=0.4, max_tokens=2500)
    return _parse_json(raw)

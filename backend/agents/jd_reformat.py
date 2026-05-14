"""JD auto-reformat agent.

Restructures messy JD text (raw docx/pdf extraction) into clean markdown
WITHOUT changing wording. Layout-only LLM call via Lite model.

Strategy:
  1. Score original structure quality (heuristic).
  2. If score < threshold, call LLM to reformat (preserve every sentence).
  3. Diff guard: reject reformat if output token count < retention threshold
     (catches LLM dropping content).
  4. Return (new_text, source_enum, score).

Source enums:
  raw            — pasted text, no processing
  extracted      — docx/pdf extractor output, structure good enough
  ai_reformatted — Lite-model layout restructure (verbatim wording)
  ai_enhanced    — Flash rewrite (separate flow, /enhance endpoint)
"""
from __future__ import annotations

import os
import re
import logging
from typing import Tuple

from backend.core.config import llm_call, LITE_MODEL

logger = logging.getLogger(__name__)

# ---------- Config ----------
AUTO_REFORMAT_ENABLED = os.getenv("JD_AUTO_REFORMAT", "true").lower() in ("true", "1", "yes", "on")
REFORMAT_THRESHOLD = float(os.getenv("JD_REFORMAT_THRESHOLD", "0.5"))
MIN_RETENTION = float(os.getenv("JD_REFORMAT_MIN_RETENTION", "0.4"))
REFORMAT_MODEL = os.getenv("JD_REFORMAT_MODEL", "") or LITE_MODEL
MIN_LENGTH_WORDS = int(os.getenv("JD_REFORMAT_MIN_WORDS", "200"))


# ---------- Quality Score ----------
def score_structure(text: str) -> float:
    """Heuristic 0-1: how well-structured is this markdown JD?
    Higher = better. < 0.5 = needs reformat.

    Signals:
      + Heading lines (#/##/###) — sectioned content
      + Bullet lines (- /*/•/numbered) — list structure
      + Inline metadata (`Location:` `Reports to:` etc) — clear field labels
      - Malformed table rows (no leading pipe but contains ` | `) — penalty
      - Long unbroken paragraphs — readability penalty
    """
    if not text or len(text.strip()) < 50:
        return 1.0  # too short to need reformat
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return 1.0
    n = len(lines)
    headings = sum(1 for l in lines if re.match(r"^\s*#{1,6}\s+", l))
    bullets = sum(1 for l in lines if re.match(r"^\s*([-*•]|\d+\.)\s+", l))
    proper_tables = sum(1 for l in lines if re.match(r"^\s*\|.*\|\s*$", l))
    malformed_tables = sum(1 for l in lines if " | " in l and not l.strip().startswith("|"))
    avg_len = sum(len(l) for l in lines) / n

    # 0-1 components
    heading_score = min(headings / max(n / 10, 1), 1.0)        # ~1 heading per 10 lines = perfect
    bullet_score = min(bullets / max(n / 4, 1), 1.0)           # ~1 bullet per 4 lines
    table_penalty = min(malformed_tables / max(n / 3, 1), 1.0) # >33% malformed = full penalty
    length_score = 1.0 if avg_len < 120 else max(0, 1 - (avg_len - 120) / 200)

    score = (
        heading_score * 0.40
        + bullet_score * 0.30
        + length_score * 0.20
        + (proper_tables / n) * 0.10
        - table_penalty * 0.50
    )
    return max(0.0, min(1.0, score))


# ---------- Prompt ----------
_REFORMAT_PROMPT = """You are a document layout assistant. Reformat the following job description into clean Markdown.

STRICT RULES:
1. PRESERVE EVERY SENTENCE VERBATIM. Do not paraphrase, summarize, or invent.
2. PRESERVE ORIGINAL LANGUAGE (English, Burmese, Thai, etc).
3. Keep all numbers, names, dates, currency, code references unchanged.
4. Do not add new sections that don't exist in the source.
5. Output ONLY the reformatted markdown. No commentary, no preamble.

LAYOUT GUIDELINES:
- Use ## for major sections (About / Responsibilities / Requirements / Qualifications / Compensation / etc).
- Use - for bullet lists where source has lists or comma-separated items.
- Use **bold** for inline labels like Location, Reports to, Department.
- Convert messy 2-col key-value tables (e.g. `Job Title: | Group HSE Manager`) into ## headings + body text.
- Keep meaningful tables (comp grids, leveling rubrics) as proper markdown tables with `|` borders.
- Strip duplicate content (some uploads repeat each row twice — keep one copy only).

INPUT JD:
---
{text}
---

CLEAN MARKDOWN OUTPUT:"""


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # remove opening ```lang
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        if s.endswith("```"):
            s = s[:-3].rstrip()
    return s


# ---------- Main ----------
def reformat_text(text: str) -> str | None:
    """Single LLM call. Returns reformatted markdown or None on failure."""
    if not text or not text.strip():
        return None
    prompt = _REFORMAT_PROMPT.format(text=text.strip())
    try:
        out = llm_call(prompt, model=REFORMAT_MODEL, temperature=0.1, max_tokens=8000)
        if not out:
            return None
        return _strip_code_fence(out)
    except Exception as e:
        logger.warning("[jd_reformat] LLM call failed: %s", e)
        return None


def safe_reformat(text: str) -> Tuple[str, str, float]:
    """Top-level entry. Returns (final_text, source_enum, score).

    source_enum: 'extracted' (no reformat needed) | 'ai_reformatted' (LLM ran)
    Score is the ORIGINAL structure score (not the reformatted one).
    """
    try:
        from backend.agents.registry import heartbeat as _hb_rf, cycle_done as _cd_rf
        _hb_rf("reformat", status="running", action="scoring + reformatting JD layout")
    except Exception:
        _hb_rf = _cd_rf = lambda *a, **kw: None  # noqa
    score = score_structure(text)
    word_count = len(text.split())

    if not AUTO_REFORMAT_ENABLED:
        logger.info("[jd_reformat] disabled via env, score=%.2f", score)
        try: _cd_rf("reformat", events=0)
        except Exception: pass
        return text, "extracted", score
    if word_count < MIN_LENGTH_WORDS:
        logger.info("[jd_reformat] skip: too short (%d words < %d)", word_count, MIN_LENGTH_WORDS)
        try: _cd_rf("reformat", events=0)
        except Exception: pass
        return text, "extracted", score
    if score >= REFORMAT_THRESHOLD:
        logger.info("[jd_reformat] skip: score %.2f >= %.2f", score, REFORMAT_THRESHOLD)
        try: _cd_rf("reformat", events=0)
        except Exception: pass
        return text, "extracted", score

    logger.info("[jd_reformat] reformat triggered: score=%.2f, words=%d", score, word_count)
    new_text = reformat_text(text)
    if not new_text:
        logger.warning("[jd_reformat] LLM returned nothing, keeping original")
        try: _cd_rf("reformat", events=0)
        except Exception: pass
        return text, "extracted", score

    # Diff guard — reject if LLM dropped excessive UNIQUE content.
    # Compare against unique-word counts so dedup-by-design (the prompt strips
    # repeated rows) doesn't trip the guard.
    def _unique_words(s: str) -> set:
        return {w.lower() for w in re.findall(r"[a-zA-Z0-9'\-]+", s) if len(w) >= 3}
    orig_unique = _unique_words(text)
    new_unique = _unique_words(new_text)
    unique_retention = len(new_unique & orig_unique) / max(len(orig_unique), 1)
    new_words = len(new_text.split())
    retention = new_words / max(word_count, 1)
    if unique_retention < MIN_RETENTION:
        logger.warning(
            "[jd_reformat] reject: unique-retention %.2f < %.2f (orig=%d, new=%d words; uniq orig=%d, new=%d)",
            unique_retention, MIN_RETENTION, word_count, new_words, len(orig_unique), len(new_unique),
        )
        try: _cd_rf("reformat", events=0)
        except Exception: pass
        return text, "extracted", score

    new_score = score_structure(new_text)
    logger.info(
        "[agent:reformat] success: score %.2f → %.2f, retention %.2f, words %d → %d",
        score, new_score, retention, word_count, new_words,
    )
    try: _cd_rf("reformat", events=1)
    except Exception: pass
    return new_text, "ai_reformatted", new_score

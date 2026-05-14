"""Duplicate detection — score candidate/JD pairs and propose merges."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    try:
        return str(o)
    except Exception:
        return None


def _jdump(obj) -> str:
    return json.dumps(obj, default=_json_default)

from backend.core.database import get_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _digits(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\D", "", s)


def _norm_email(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.strip().lower()


def _norm_url(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


def _trgm_similarity(a: str, b: str) -> float:
    """pg_trgm similarity via DB."""
    if not a or not b:
        return 0.0
    try:
        with get_cursor() as cur:
            cur.execute("SELECT similarity(%s, %s)", (a, b))
            return float(cur.fetchone()[0] or 0)
    except Exception:
        return 0.0


def _jaccard(a: list, b: list) -> float:
    if not a or not b:
        return 0.0
    sa = {str(x).strip().lower() for x in a if x}
    sb = {str(x).strip().lower() for x in b if x}
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Candidate signals
# ---------------------------------------------------------------------------
def candidate_dup_signals(new: dict, existing: dict) -> dict:
    """Score (0..1) and signals for a candidate pair."""
    signals: list[str] = []
    score = 0.0

    e1, e2 = _norm_email(new.get("email")), _norm_email(existing.get("email"))
    if e1 and e2 and e1 == e2:
        score += 0.6
        signals.append("email_exact")

    p1, p2 = _digits(new.get("phone")), _digits(existing.get("phone"))
    if p1 and p2 and len(p1) >= 7 and p1[-10:] == p2[-10:]:
        score += 0.3
        signals.append("phone_exact")

    l1, l2 = _norm_url(new.get("linkedin_url")), _norm_url(existing.get("linkedin_url"))
    if l1 and l2 and l1 == l2:
        score += 0.5
        signals.append("linkedin_exact")

    n1, n2 = (new.get("name") or "").strip(), (existing.get("name") or "").strip()
    if n1 and n2:
        sim = _trgm_similarity(n1, n2)
        if sim > 0.7:
            score += 0.2 * sim
            signals.append(f"name_trgm:{sim:.2f}")

    return {"score": min(score, 1.0), "signals": signals}


def jd_dup_signals(new: dict, existing: dict) -> dict:
    """Score (0..1) and signals for a JD pair."""
    signals: list[str] = []
    score = 0.0

    t1, t2 = (new.get("title") or "").strip(), (existing.get("title") or "").strip()
    if t1 and t2:
        sim = _trgm_similarity(t1, t2)
        if sim > 0.5:
            score += 0.4 * sim
            signals.append(f"title_trgm:{sim:.2f}")

    s1 = list(new.get("required_skills") or [])
    s2 = list(existing.get("required_skills") or [])
    jac = _jaccard(s1, s2)
    if jac > 0:
        score += 0.4 * jac
        signals.append(f"skills_jaccard:{jac:.2f}")

    d1 = (new.get("department") or "").strip().lower()
    d2 = (existing.get("department") or "").strip().lower()
    if d1 and d2 and d1 == d2:
        score += 0.2
        signals.append("dept_exact")

    return {"score": min(score, 1.0), "signals": signals}


# ---------------------------------------------------------------------------
# Helpers for proposal management
# ---------------------------------------------------------------------------
def _is_not_duplicate(entity_type: str, a: int, b: int) -> bool:
    lo, hi = min(a, b), max(a, b)
    with get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM not_duplicates WHERE entity_type=%s AND LEAST(a_id,b_id)=%s AND GREATEST(a_id,b_id)=%s LIMIT 1",
            (entity_type, lo, hi),
        )
        return cur.fetchone() is not None


def _existing_proposal(entity_type: str, a: int, b: int) -> Optional[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, status FROM merge_proposals
               WHERE entity_type=%s
                 AND ((winner_id=%s AND loser_id=%s) OR (winner_id=%s AND loser_id=%s))
               ORDER BY id DESC LIMIT 1""",
            (entity_type, a, b, b, a),
        )
        row = cur.fetchone()
        if row:
            return {"id": row[0], "status": row[1]}
        return None


def _build_diff(new: dict, existing: dict, fields: list[str]) -> dict:
    diff: dict = {}
    for f in fields:
        a = new.get(f)
        b = existing.get(f)
        if a != b:
            diff[f] = {"winner": a if _quality(new) >= _quality(existing) else b,
                       "loser": b if _quality(new) >= _quality(existing) else a,
                       "new": a, "existing": b}
    return diff


def _quality(c: dict) -> float:
    return float(c.get("quality_score") or 0)


# ---------------------------------------------------------------------------
# Candidate dedup proposal
# ---------------------------------------------------------------------------
CANDIDATE_DIFF_FIELDS = [
    "name", "email", "phone", "location", "linkedin_url",
    "current_role", "current_company", "total_experience_years",
    "seniority_level", "summary_short",
]


def propose_candidate_dups(candidate_id: int) -> list[int]:
    """Find dups for a candidate; auto-merge >=0.95, propose 0.70-0.95. Returns proposal ids created."""
    proposals_created: list[int] = []

    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM candidates WHERE id = %s",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            return []
        cols = [d[0] for d in cur.description]
        new_c = dict(zip(cols, row))

        if (new_c.get("status") or "active") == "merged":
            return []

        cur.execute(
            "SELECT * FROM candidates WHERE id != %s AND COALESCE(status,'active') NOT IN ('merged')",
            (candidate_id,),
        )
        cols = [d[0] for d in cur.description]
        others = [dict(zip(cols, r)) for r in cur.fetchall()]

    auto_merge_targets: list[tuple[int, int, float, str, dict]] = []

    for ex in others:
        if _is_not_duplicate("candidate", new_c["id"], ex["id"]):
            continue
        sig = candidate_dup_signals(new_c, ex)
        score = sig["score"]
        if score < 0.70:
            continue

        existing_prop = _existing_proposal("candidate", new_c["id"], ex["id"])
        if existing_prop and existing_prop["status"] in ("pending", "applied", "approved"):
            continue

        # winner = higher quality
        if _quality(new_c) >= _quality(ex):
            winner_id, loser_id = new_c["id"], ex["id"]
            winner, loser = new_c, ex
        else:
            winner_id, loser_id = ex["id"], new_c["id"]
            winner, loser = ex, new_c

        if winner_id == loser_id:
            continue

        diff = _build_diff(new_c, ex, CANDIDATE_DIFF_FIELDS)
        method = "+".join(sig["signals"]) if sig["signals"] else "score"

        if score >= 0.95:
            auto_merge_targets.append((winner_id, loser_id, score, method, diff))
        else:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO merge_proposals
                       (entity_type, winner_id, loser_id, confidence, method, diff, status)
                       VALUES ('candidate', %s, %s, %s, %s, %s, 'pending')
                       RETURNING id""",
                    (winner_id, loser_id, score, method, _jdump(diff)),
                )
                pid = cur.fetchone()[0]
                proposals_created.append(pid)

    # Auto-merges happen outside loop to avoid mutating the iterator results
    for winner_id, loser_id, score, method, diff in auto_merge_targets:
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO merge_proposals
                       (entity_type, winner_id, loser_id, confidence, method, diff, status)
                       VALUES ('candidate', %s, %s, %s, %s, %s, 'pending')
                       RETURNING id""",
                    (winner_id, loser_id, score, method, _jdump(diff)),
                )
                pid = cur.fetchone()[0]
            from backend.agents.merge import apply_merge
            apply_merge(pid, field_choices={}, archive=True, user_id=None, auto=True)
            proposals_created.append(pid)
        except Exception as e:
            logger.warning(f"auto-merge failed for {winner_id}<-{loser_id}: {e}")

    return proposals_created


# ---------------------------------------------------------------------------
# JD dedup
# ---------------------------------------------------------------------------
JD_DIFF_FIELDS = ["title", "department", "seniority_level", "employment_type", "min_experience_years"]


def propose_jd_dups(jd_id: int) -> list[int]:
    """Find dups for a JD; auto-merge >=0.85, propose 0.65-0.85."""
    proposals_created: list[int] = []
    with get_cursor() as cur:
        cur.execute("SELECT * FROM jd_repository WHERE id=%s", (jd_id,))
        row = cur.fetchone()
        if not row:
            return []
        cols = [d[0] for d in cur.description]
        new_j = dict(zip(cols, row))
        if (new_j.get("status") or "active") in ("merged", "archived"):
            return []

        cur.execute(
            "SELECT * FROM jd_repository WHERE id != %s AND COALESCE(status,'active') NOT IN ('merged','archived')",
            (jd_id,),
        )
        cols = [d[0] for d in cur.description]
        others = [dict(zip(cols, r)) for r in cur.fetchall()]

    auto_targets = []
    for ex in others:
        if _is_not_duplicate("jd", new_j["id"], ex["id"]):
            continue
        sig = jd_dup_signals(new_j, ex)
        score = sig["score"]
        if score < 0.65:
            continue
        existing_prop = _existing_proposal("jd", new_j["id"], ex["id"])
        if existing_prop and existing_prop["status"] in ("pending", "applied", "approved"):
            continue

        # winner = higher used_count then newer
        if (new_j.get("used_count") or 0) >= (ex.get("used_count") or 0):
            winner_id, loser_id = new_j["id"], ex["id"]
        else:
            winner_id, loser_id = ex["id"], new_j["id"]

        if winner_id == loser_id:
            continue

        diff = {}
        for f in JD_DIFF_FIELDS:
            if new_j.get(f) != ex.get(f):
                diff[f] = {"new": new_j.get(f), "existing": ex.get(f)}

        method = "+".join(sig["signals"]) if sig["signals"] else "score"

        if score >= 0.85:
            auto_targets.append((winner_id, loser_id, score, method, diff))
        else:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO merge_proposals
                       (entity_type, winner_id, loser_id, confidence, method, diff, status)
                       VALUES ('jd', %s, %s, %s, %s, %s, 'pending')
                       RETURNING id""",
                    (winner_id, loser_id, score, method, _jdump(diff)),
                )
                pid = cur.fetchone()[0]
                proposals_created.append(pid)

    for winner_id, loser_id, score, method, diff in auto_targets:
        try:
            with get_cursor() as cur:
                cur.execute(
                    """INSERT INTO merge_proposals
                       (entity_type, winner_id, loser_id, confidence, method, diff, status)
                       VALUES ('jd', %s, %s, %s, %s, %s, 'pending')
                       RETURNING id""",
                    (winner_id, loser_id, score, method, _jdump(diff)),
                )
                pid = cur.fetchone()[0]
            from backend.agents.merge import apply_merge
            apply_merge(pid, field_choices={}, archive=True, user_id=None, auto=True)
            proposals_created.append(pid)
        except Exception as e:
            logger.warning(f"auto-merge JD failed: {e}")

    return proposals_created


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------
def dedup_sweep_candidates() -> dict:
    created: list[int] = []
    with get_cursor() as cur:
        cur.execute("SELECT id FROM candidates WHERE COALESCE(status,'active') NOT IN ('merged') ORDER BY id")
        ids = [r[0] for r in cur.fetchall()]
    for cid in ids:
        try:
            created.extend(propose_candidate_dups(cid))
        except Exception as e:
            logger.warning(f"sweep candidate {cid}: {e}")
    return {"scanned": len(ids), "proposals_created": len(created), "ids": created}


def dedup_sweep_jds() -> dict:
    created: list[int] = []
    with get_cursor() as cur:
        cur.execute("SELECT id FROM jd_repository WHERE COALESCE(status,'active') NOT IN ('merged','archived') ORDER BY id")
        ids = [r[0] for r in cur.fetchall()]
    for jid in ids:
        try:
            created.extend(propose_jd_dups(jid))
        except Exception as e:
            logger.warning(f"sweep jd {jid}: {e}")
    return {"scanned": len(ids), "proposals_created": len(created), "ids": created}

"""Analytics provider — wraps backend.routes.analytics.

Read-only. All metrics computed via existing helpers in routes/analytics.py.
"""
from __future__ import annotations

from typing import Optional

from backend.core.database import get_cursor


# ---------------------------------------------------------------------------
# Range helpers
# ---------------------------------------------------------------------------
_FUNNEL_STAGES = ["uploaded", "screened", "shortlisted", "offered", "hired"]


def _range_sql(range: str, column: str) -> str:
    """Return a SQL fragment like `AND col >= ...` (or empty for 'all').

    range: 'today', '7d', '30d', 'mtd', 'all'
    """
    r = (range or "30d").lower()
    if r == "all":
        return ""
    if r == "today":
        return f" AND {column} >= CURRENT_DATE"
    if r == "7d":
        return f" AND {column} >= NOW() - INTERVAL '7 days'"
    if r == "mtd":
        return f" AND {column} >= DATE_TRUNC('month', CURRENT_DATE)"
    # default 30d
    return f" AND {column} >= NOW() - INTERVAL '30 days'"


# ---------------------------------------------------------------------------
# 1. Funnel
# ---------------------------------------------------------------------------
def query_funnel(position_id: Optional[int] = None, range: str = "30d") -> dict:
    """Stage counts + conversion rates.

    Returns: {stages: [{name, count, conv_pct}], total_candidates}
    """
    range_clause = _range_sql(range, "pc.created_at")
    pos_clause = ""
    params: list = []
    if position_id is not None:
        pos_clause = " AND pc.position_id = %s"
        params.append(position_id)

    counts: dict[str, int] = {}
    with get_cursor() as cur:
        for i, stage in enumerate(_FUNNEL_STAGES):
            # Candidates that reached this stage or beyond
            stages_at_or_beyond = _FUNNEL_STAGES[i:]
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT pc.candidate_id)
                FROM position_candidates pc
                WHERE pc.stage = ANY(%s)
                {pos_clause}
                {range_clause}
                """,
                [stages_at_or_beyond, *params],
            )
            counts[stage] = cur.fetchone()[0] or 0

        # Total distinct candidates in funnel for this scope
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT pc.candidate_id)
            FROM position_candidates pc
            WHERE 1=1 {pos_clause} {range_clause}
            """,
            params,
        )
        total_candidates = cur.fetchone()[0] or 0

    top_count = counts[_FUNNEL_STAGES[0]]
    stages_out = []
    for i, stage in enumerate(_FUNNEL_STAGES):
        c = counts[stage]
        if i == 0:
            conv = 100.0 if c > 0 else 0.0
        else:
            prev = counts[_FUNNEL_STAGES[i - 1]]
            conv = round((c / prev) * 100, 1) if prev > 0 else 0.0
        stages_out.append({"name": stage, "count": c, "conv_pct": conv})

    return {"stages": stages_out, "total_candidates": total_candidates}


# ---------------------------------------------------------------------------
# 2. Time-to-hire
# ---------------------------------------------------------------------------
def query_time_to_hire(position_id: Optional[int] = None, range: str = "30d") -> dict:
    """Average days at each stage.

    Returns: {avg_days_total, by_stage: {stage: days}}
    """
    range_clause = _range_sql(range, "pc.stage_changed_at")
    pos_clause = ""
    params: list = []
    if position_id is not None:
        pos_clause = " AND pc.position_id = %s"
        params.append(position_id)

    with get_cursor() as cur:
        # Avg total days from candidate added to hire
        cur.execute(
            f"""
            SELECT ROUND(AVG(EXTRACT(EPOCH FROM (pc.stage_changed_at - pc.created_at)) / 86400)::numeric, 1)
            FROM position_candidates pc
            WHERE pc.stage = 'hired'
              AND pc.stage_changed_at IS NOT NULL
              {pos_clause}
              {range_clause}
            """,
            params,
        )
        avg_total = cur.fetchone()[0]

        # Per-stage average days from activity log (delta between candidate added → activity)
        ca_range_clause = _range_sql(range, "ca.created_at")
        ca_pos_clause = ""
        ca_params: list = []
        if position_id is not None:
            ca_pos_clause = " AND pc.position_id = %s"
            ca_params.append(position_id)

        cur.execute(
            f"""
            SELECT ca.activity_type,
                   ROUND(AVG(EXTRACT(EPOCH FROM (ca.created_at - pc.created_at)) / 86400)::numeric, 1) AS avg_days
            FROM candidate_activity ca
            JOIN position_candidates pc
              ON pc.candidate_id = ca.candidate_id
             AND pc.position_id = ca.position_id
            WHERE ca.activity_type IN (
                'stage_change', 'scorecard_submitted'
            )
            {ca_pos_clause}
            {ca_range_clause}
            GROUP BY ca.activity_type
            """,
            ca_params,
        )
        by_stage = {}
        for row in cur.fetchall():
            stage_name, days = row[0], row[1]
            by_stage[stage_name] = float(days) if days is not None else None

    return {
        "avg_days_total": float(avg_total) if avg_total is not None else None,
        "by_stage": by_stage,
    }


# ---------------------------------------------------------------------------
# 3. Sources
# ---------------------------------------------------------------------------
def query_sources(range: str = "30d") -> list[dict]:
    """Top sources by candidate count + hire conversion.

    Returns: [{source, count, hires, conv_pct}]
    """
    range_clause = _range_sql(range, "c.created_at")

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COALESCE(c.source, 'unknown') AS source,
                COUNT(DISTINCT c.id) AS count,
                COUNT(DISTINCT CASE WHEN pc.stage = 'hired' THEN c.id END) AS hires
            FROM candidates c
            LEFT JOIN position_candidates pc ON pc.candidate_id = c.id
            WHERE c.status = 'active'
              {range_clause}
            GROUP BY COALESCE(c.source, 'unknown')
            ORDER BY count DESC
            """
        )
        rows = cur.fetchall()

    out = []
    for source, count, hires in rows:
        c = count or 0
        h = hires or 0
        conv = round((h / c) * 100, 1) if c > 0 else 0.0
        out.append({"source": source, "count": c, "hires": h, "conv_pct": conv})
    return out


# ---------------------------------------------------------------------------
# 4. Overview
# ---------------------------------------------------------------------------
def query_overview(range: str = "30d") -> dict:
    """One-shot dashboard summary.

    Returns: {open_positions, candidates_added,
              offers_made, hires_count, avg_match_score}
    """
    cand_range = _range_sql(range, "created_at")
    offer_range = _range_sql(range, "created_at")
    hire_range = _range_sql(range, "stage_changed_at")

    with get_cursor() as cur:
        # Open positions (point-in-time, range-independent)
        cur.execute("SELECT COUNT(*) FROM positions WHERE status = 'active'")
        open_positions = cur.fetchone()[0] or 0

        cur.execute(
            f"SELECT COUNT(*) FROM candidates WHERE status = 'active' {cand_range}"
        )
        candidates_added = cur.fetchone()[0] or 0

        cur.execute(
            f"SELECT COUNT(*) FROM offers WHERE 1=1 {offer_range}"
        )
        offers_made = cur.fetchone()[0] or 0

        cur.execute(
            f"""
            SELECT COUNT(*) FROM position_candidates
            WHERE stage = 'hired' AND stage_changed_at IS NOT NULL
            {hire_range}
            """
        )
        hires_count = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT ROUND(AVG(match_score_composite)::numeric, 1)
            FROM position_candidates
            WHERE match_score_composite IS NOT NULL
            """
        )
        avg_match = cur.fetchone()[0]

    return {
        "open_positions": open_positions,
        "candidates_added": candidates_added,
        "offers_made": offers_made,
        "hires_count": hires_count,
        "avg_match_score": float(avg_match) if avg_match is not None else None,
    }

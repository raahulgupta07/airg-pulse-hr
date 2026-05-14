"""Analytics — dashboard metrics, funnel, time-to-hire, sources, AI insights, SLA tracking."""
from __future__ import annotations

import re
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import JSONResponse

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.config import llm_call, CHAT_MODEL
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/overview")
async def overview(request: Request):
    """Total positions, candidates, interviews, hires, avg time-to-hire."""
    get_current_user(request)

    from backend.core.cache import cache
    cached = cache.get("analytics_overview")
    if cached:
        return cached

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM positions WHERE status = 'active'")
        total_positions = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM candidates WHERE status = 'active'")
        total_candidates = cur.fetchone()[0]

        total_interviews = 0  # interviews feature removed

        cur.execute("SELECT COUNT(*) FROM position_candidates WHERE stage = 'hired'")
        total_hires = cur.fetchone()[0]

        cur.execute("""
            SELECT ROUND(AVG(EXTRACT(EPOCH FROM (stage_changed_at - created_at)) / 86400)::numeric, 1)
            FROM position_candidates
            WHERE stage = 'hired' AND stage_changed_at IS NOT NULL
        """)
        avg_time_to_hire = cur.fetchone()[0]

    result = {
        "total_positions": total_positions,
        "total_candidates": total_candidates,
        "total_interviews": total_interviews,
        "total_hires": total_hires,
        "avg_time_to_hire_days": float(avg_time_to_hire) if avg_time_to_hire else None,
    }
    cache.set("analytics_overview", result, ttl=30)
    return result


@router.get("/funnel")
async def funnel_alias(request: Request):
    """Alias for /pipeline-funnel — kept so frontend `/api/analytics/funnel`
    callers don't 404. Returns the same payload."""
    return await pipeline_funnel(request)


@router.get("/pipeline-funnel")
async def pipeline_funnel(request: Request):
    """Conversion rates between pipeline stages."""
    get_current_user(request)

    stages = ["uploaded", "screened", "shortlisted", "interviewed", "offered", "hired"]

    with get_cursor() as cur:
        counts = {}
        for stage in stages:
            cur.execute("""
                SELECT COUNT(*) FROM position_candidates
                WHERE stage = %s OR stage IN (
                    SELECT unnest(%s::text[])
                )
            """, (stage, stages[stages.index(stage):]))
            # Count candidates that reached this stage or beyond
            cur.execute("""
                SELECT COUNT(DISTINCT candidate_id) FROM position_candidates
                WHERE stage = ANY(%s)
            """, (stages[stages.index(stage):],))
            counts[stage] = cur.fetchone()[0]

    funnel = []
    for i, stage in enumerate(stages):
        entry = {"stage": stage, "count": counts[stage]}
        if i > 0 and counts[stages[i - 1]] > 0:
            entry["conversion_rate"] = round(counts[stage] / counts[stages[i - 1]] * 100, 1)
        else:
            entry["conversion_rate"] = 100.0 if counts[stage] > 0 else 0.0
        funnel.append(entry)

    return {"funnel": funnel}


@router.get("/time-to-hire")
async def time_to_hire(request: Request):
    """Average days per stage and total days to hire."""
    get_current_user(request)

    with get_cursor() as cur:
        # Average total time to hire
        cur.execute("""
            SELECT ROUND(AVG(EXTRACT(EPOCH FROM (stage_changed_at - created_at)) / 86400)::numeric, 1)
            FROM position_candidates
            WHERE stage = 'hired' AND stage_changed_at IS NOT NULL
        """)
        avg_total = cur.fetchone()[0]

        # Per-stage averages from activity log
        cur.execute("""
            SELECT activity_type,
                   ROUND(AVG(EXTRACT(EPOCH FROM (ca.created_at - pc.created_at)) / 86400)::numeric, 1) AS avg_days
            FROM candidate_activity ca
            JOIN position_candidates pc ON pc.candidate_id = ca.candidate_id AND pc.position_id = ca.position_id
            WHERE ca.activity_type IN ('stage_change', 'interview_scheduled', 'interview_completed', 'scorecard_submitted')
            GROUP BY ca.activity_type
        """)
        cols = [desc[0] for desc in cur.description]
        stage_times = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {
        "avg_total_days": float(avg_total) if avg_total else None,
        "stage_breakdown": stage_times,
    }


@router.get("/source-breakdown")
async def source_breakdown(request: Request):
    """Candidates by source."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT source, COUNT(*) AS count
            FROM candidates
            WHERE status = 'active'
            GROUP BY source
            ORDER BY count DESC
        """)
        cols = [desc[0] for desc in cur.description]
        sources = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"sources": sources}


@router.get("/position-health")
async def position_health(request: Request):
    """Health score per position with breakdown: pipeline activity, CV count, match quality, days open."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT
                p.id, p.slug, p.title, p.status, p.department,
                p.created_at,
                COUNT(pc.id) AS cv_count,
                ROUND(AVG(pc.match_score_composite)::numeric, 1) AS avg_match,
                COUNT(DISTINCT CASE WHEN pc.stage NOT IN ('uploaded', 'rejected') THEN pc.id END) AS active_pipeline,
                EXTRACT(DAY FROM NOW() - p.created_at)::int AS days_open
            FROM positions p
            LEFT JOIN position_candidates pc ON pc.position_id = p.id
            WHERE p.status = 'active'
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    results = []
    for pos in rows:
        cv_count = pos["cv_count"] or 0
        avg_match = float(pos["avg_match"]) if pos["avg_match"] else 0
        active_pipeline = pos["active_pipeline"] or 0
        days_open = pos["days_open"] or 0

        # Pipeline activity score (0-100): do we have candidates moving?
        pipeline_score = min(100, active_pipeline * 20) if cv_count > 0 else 0

        # CV count score (0-100): target is 10+ candidates
        cv_score = min(100, cv_count * 10)

        # Match quality score (0-100): avg match
        match_score = avg_match

        # Freshness score (0-100): penalize long open positions (> 60 days = 0)
        freshness_score = max(0, 100 - (days_open * 100 / 60)) if days_open <= 60 else 0

        # Weighted health score
        health = round(
            pipeline_score * 0.25
            + cv_score * 0.25
            + match_score * 0.30
            + freshness_score * 0.20
        )

        results.append({
            "position_id": pos["id"],
            "slug": pos["slug"],
            "title": pos["title"],
            "health_score": health,
            "breakdown": {
                "pipeline_activity": round(pipeline_score),
                "cv_count": round(cv_score),
                "match_quality": round(match_score),
                "freshness": round(freshness_score),
            },
            "raw": {
                "cv_count": cv_count,
                "avg_match": avg_match,
                "active_pipeline": active_pipeline,
                "days_open": days_open,
            },
        })

    return {"positions": results}


@router.get("/activity-heatmap")
async def activity_heatmap(request: Request):
    """Daily activity counts for the last year — GitHub-style heatmap data."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS count
            FROM candidate_activity
            WHERE created_at > NOW() - INTERVAL '365 days'
            GROUP BY DATE(created_at)
            ORDER BY day
        """)
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Convert dates to strings
    data = []
    for row in rows:
        data.append({
            "day": row["day"].isoformat() if hasattr(row["day"], "isoformat") else str(row["day"]),
            "count": row["count"],
        })

    return {"days": data}


@router.get("/pipeline-flow")
async def pipeline_flow(request: Request):
    """Sankey diagram data: candidate flow between pipeline stages."""
    get_current_user(request)

    stages_order = ["uploaded", "screened", "shortlisted", "interview_scheduled", "interviewed", "offered", "hired"]

    with get_cursor() as cur:
        # Try to derive transitions from activity log
        cur.execute("""
            SELECT
                details->>'from_stage' AS from_stage,
                details->>'to_stage' AS to_stage,
                COUNT(*) AS count
            FROM candidate_activity
            WHERE activity_type = 'stage_change'
              AND details->>'from_stage' IS NOT NULL
              AND details->>'to_stage' IS NOT NULL
            GROUP BY details->>'from_stage', details->>'to_stage'
            ORDER BY count DESC
        """)
        cols = [desc[0] for desc in cur.description]
        transitions = [dict(zip(cols, row)) for row in cur.fetchall()]

        # If no transition history, derive from current stage counts
        if not transitions:
            cur.execute("""
                SELECT stage, COUNT(*) AS count
                FROM position_candidates
                GROUP BY stage
                ORDER BY count DESC
            """)
            stage_counts = {row[0]: row[1] for row in cur.fetchall()}

            # Build synthetic transitions: assume linear flow
            transitions = []
            for i in range(len(stages_order) - 1):
                s_from = stages_order[i]
                s_to = stages_order[i + 1]
                # Count = candidates at or beyond the to_stage
                count = sum(
                    stage_counts.get(stages_order[j], 0)
                    for j in range(i + 1, len(stages_order))
                )
                if count > 0:
                    transitions.append({
                        "from_stage": s_from,
                        "to_stage": s_to,
                        "count": count,
                    })

    # Build nodes from all mentioned stages
    node_names = set()
    for t in transitions:
        node_names.add(t["from_stage"])
        node_names.add(t["to_stage"])

    label_map = {
        "uploaded": "Uploaded", "screened": "Screened", "shortlisted": "Shortlisted",
        "interview_scheduled": "Interview Scheduled", "interviewed": "Interviewed",
        "offered": "Offered", "hired": "Hired", "rejected": "Rejected",
    }

    nodes = [{"name": label_map.get(n, n.replace("_", " ").title())} for n in node_names]
    links = [
        {
            "source": label_map.get(t["from_stage"], t["from_stage"].replace("_", " ").title()),
            "target": label_map.get(t["to_stage"], t["to_stage"].replace("_", " ").title()),
            "value": t["count"],
        }
        for t in transitions
        if t["count"] > 0
    ]

    return {"nodes": nodes, "links": links}


@router.get("/leaderboard")
async def leaderboard(request: Request):
    """Team leaderboard — aggregate user activity counts."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT
                u.id,
                u.display_name,
                u.avatar_url,
                COUNT(*) FILTER (WHERE ca.activity_type IN ('scorecard_submitted', 'screening_completed')) AS reviews,
                COUNT(*) FILTER (WHERE ca.activity_type IN ('interview_scheduled', 'interview_completed')) AS interviews,
                COUNT(*) FILTER (WHERE ca.activity_type = 'note_added') AS notes,
                COUNT(*) AS total_actions
            FROM users u
            JOIN candidate_activity ca ON ca.user_id = u.id
            WHERE u.is_active = TRUE
            GROUP BY u.id, u.display_name, u.avatar_url
            ORDER BY total_actions DESC
            LIMIT 20
        """)
        cols = [desc[0] for desc in cur.description]
        members = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Compute a score: reviews*3 + interviews*2 + notes*1
    for m in members:
        m["score"] = (m["reviews"] or 0) * 3 + (m["interviews"] or 0) * 2 + (m["notes"] or 0)

    return {"members": members}


@router.get("/positions-summary")
async def positions_summary(request: Request):
    """Per-position stats: candidates, avg match, interviews, time open."""
    get_current_user(request)

    with get_cursor() as cur:
        cur.execute("""
            SELECT
                p.id, p.slug, p.title, p.status, p.department,
                p.created_at,
                COUNT(pc.id) AS candidate_count,
                ROUND(AVG(pc.match_score_composite)::numeric, 1) AS avg_match_score,
                COUNT(DISTINCT i.id) AS interview_count,
                EXTRACT(DAY FROM NOW() - p.created_at)::int AS days_open
            FROM positions p
            LEFT JOIN position_candidates pc ON pc.position_id = p.id
            LEFT JOIN interviews i ON i.position_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)
        cols = [desc[0] for desc in cur.description]
        positions = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"positions": positions}


# ---------------------------------------------------------------------------
# SLA Tracking
# ---------------------------------------------------------------------------
@router.get("/sla-status")
async def sla_status(
    request: Request,
    position_id: Optional[int] = Query(None),
):
    """Check all positions for SLA violations — candidates stuck in a stage too long."""
    get_current_user(request)

    conditions = []
    params = []
    if position_id is not None:
        conditions.append("sr.position_id = %s")
        params.append(position_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT sr.id AS rule_id, sr.position_id, sr.stage, sr.max_days, sr.alert_days,
                   p.title AS position_title, p.slug AS position_slug,
                   pc.candidate_id,
                   c.name AS candidate_name,
                   pc.stage AS candidate_stage,
                   EXTRACT(DAY FROM NOW() - COALESCE(pc.stage_changed_at, pc.created_at))::int AS days_in_stage
            FROM sla_rules sr
            JOIN positions p ON p.id = sr.position_id
            JOIN position_candidates pc ON pc.position_id = sr.position_id AND pc.stage = sr.stage
            JOIN candidates c ON c.id = pc.candidate_id
            {where}
            AND sr.is_active = TRUE
            ORDER BY days_in_stage DESC
        """, params)
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    results = []
    for row in rows:
        days = row["days_in_stage"] or 0
        max_d = row["max_days"]
        alert_d = row["alert_days"] or max_d
        results.append({
            "position_id": row["position_id"],
            "position_title": row["position_title"],
            "position_slug": row["position_slug"],
            "candidate_id": row["candidate_id"],
            "candidate_name": row["candidate_name"],
            "stage": row["stage"],
            "days_in_stage": days,
            "sla_max": max_d,
            "is_violated": days > max_d,
            "is_warning": days >= alert_d and days <= max_d,
        })

    return {"sla_status": results, "total": len(results),
            "violations": sum(1 for r in results if r["is_violated"]),
            "warnings": sum(1 for r in results if r["is_warning"])}


@router.post("/sla-rules", dependencies=[Depends(require_role("admin"))])
async def create_sla_rule(request: Request):
    """Create an SLA rule for a position stage."""
    get_current_user(request)
    body = await request.json()

    required = ["position_id", "stage", "max_days"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"{field} is required")

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO sla_rules (position_id, stage, max_days, alert_days)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
        """, (
            body["position_id"], body["stage"],
            body["max_days"], body.get("alert_days"),
        ))
        row = cur.fetchone()

    return {"id": row[0], "created_at": row[1]}


@router.get("/sla-rules")
async def list_sla_rules(
    request: Request,
    position_id: Optional[int] = Query(None),
):
    """List SLA rules."""
    get_current_user(request)

    conditions = []
    params = []
    if position_id is not None:
        conditions.append("sr.position_id = %s")
        params.append(position_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_cursor() as cur:
        cur.execute(f"""
            SELECT sr.*, p.title AS position_title
            FROM sla_rules sr
            LEFT JOIN positions p ON p.id = sr.position_id
            {where}
            ORDER BY sr.created_at DESC
        """, params)
        cols = [desc[0] for desc in cur.description]
        rules = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"rules": rules}


# ---------------------------------------------------------------------------
# AI Pipeline Insights
# ---------------------------------------------------------------------------
@router.get("/ai-insights")
async def ai_insights(request: Request):
    """AI analyzes current pipeline state and generates narrative insights with actions."""
    get_current_user(request)

    with get_cursor() as cur:
        # Candidates stuck in stages for >7 days
        cur.execute("""
            SELECT pc.candidate_id, c.name AS candidate_name, pc.stage,
                   p.title AS position_title, p.slug,
                   EXTRACT(DAY FROM NOW() - COALESCE(pc.stage_changed_at, pc.created_at))::int AS days_in_stage
            FROM position_candidates pc
            JOIN candidates c ON c.id = pc.candidate_id
            JOIN positions p ON p.id = pc.position_id
            WHERE p.status = 'active'
              AND pc.stage NOT IN ('hired', 'rejected')
              AND EXTRACT(DAY FROM NOW() - COALESCE(pc.stage_changed_at, pc.created_at)) > 7
            ORDER BY days_in_stage DESC
            LIMIT 20
        """)
        stuck_cols = [desc[0] for desc in cur.description]
        stuck_candidates = [dict(zip(stuck_cols, row)) for row in cur.fetchall()]

        # Positions with no activity for >5 days
        cur.execute("""
            SELECT p.id, p.title, p.slug, p.department,
                   EXTRACT(DAY FROM NOW() - p.created_at)::int AS days_open,
                   COUNT(pc.id) AS cv_count,
                   MAX(ca.created_at) AS last_activity
            FROM positions p
            LEFT JOIN position_candidates pc ON pc.position_id = p.id
            LEFT JOIN candidate_activity ca ON ca.position_id = p.id
            WHERE p.status = 'active'
            GROUP BY p.id
            HAVING MAX(ca.created_at) IS NULL OR MAX(ca.created_at) < NOW() - INTERVAL '5 days'
            ORDER BY days_open DESC
            LIMIT 10
        """)
        inactive_cols = [desc[0] for desc in cur.description]
        inactive_positions = [dict(zip(inactive_cols, row)) for row in cur.fetchall()]

        # Conversion rates
        cur.execute("""
            SELECT stage, COUNT(*) AS count
            FROM position_candidates
            GROUP BY stage
        """)
        stage_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Overall stats
        cur.execute("SELECT COUNT(*) FROM positions WHERE status = 'active'")
        total_active_positions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candidates WHERE status = 'active' AND is_processed = TRUE")
        total_candidates = cur.fetchone()[0]

    # Build data summary for LLM
    stuck_summary = "\n".join(
        f"- {s['candidate_name']} stuck in '{s['stage']}' for {s['days_in_stage']} days ({s['position_title']})"
        for s in stuck_candidates[:10]
    ) if stuck_candidates else "None"

    inactive_summary = "\n".join(
        f"- {p['title']} ({p['slug']}): {p['days_open']} days open, {p['cv_count']} CVs, last activity: {p.get('last_activity', 'never')}"
        for p in inactive_positions[:10]
    ) if inactive_positions else "None"

    stage_summary = ", ".join(f"{k}: {v}" for k, v in stage_counts.items())

    prompt = f"""You are an HR analytics AI. Analyze this pipeline data and generate actionable insights.

PIPELINE STATE:
Active Positions: {total_active_positions}
Processed Candidates: {total_candidates}
Stage Distribution: {stage_summary}

STUCK CANDIDATES (>7 days in same stage):
{stuck_summary}

INACTIVE POSITIONS (no activity >5 days):
{inactive_summary}

Generate 3-6 insights. Each insight should be specific and actionable.

Return ONLY valid JSON array:
[
  {{
    "type": "bottleneck|stale|anomaly|opportunity|risk",
    "title": "Short title",
    "description": "2-3 sentence description with specific data",
    "action": "Specific recommended action",
    "severity": "high|medium|low"
  }}
]"""

    result = llm_call(prompt, model=CHAT_MODEL, temperature=0.3, max_tokens=2000)

    insights = []
    if result:
        try:
            json_match = re.search(r'\[[\s\S]*\]', result)
            if json_match:
                insights = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse AI insights response")

    return {
        "insights": insights,
        "raw_data": {
            "stuck_candidates_count": len(stuck_candidates),
            "inactive_positions_count": len(inactive_positions),
            "stage_counts": stage_counts,
            "total_active_positions": total_active_positions,
            "total_candidates": total_candidates,
        },
    }

"""Analytics V2 — funnel/cohort/time, recruiter scorecards, DEI, cost-per-hire,
quality-of-hire, and predictive (forecast + likelihood-to-hire)."""
from __future__ import annotations

import math
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.core.database import get_cursor
from backend.core.permissions import require_role

logger = logging.getLogger(__name__)
router = APIRouter()

STAGES = [
    "uploaded", "screened", "shortlisted",
    "interview_scheduled", "interviewed", "offered", "hired",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sigmoid(x: float) -> float:
    try:
        if x < -50:
            return 0.0
        if x > 50:
            return 1.0
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return 0.5


def _date_range(frm: Optional[str], to: Optional[str]) -> tuple[str, list]:
    """Return WHERE-clause fragment + params for a generic created_at filter.

    Caller composes the full WHERE; this returns just the AND-fragment using
    a `created_at` reference. Adjust column name as needed in caller."""
    clauses = []
    params: list = []
    if frm:
        clauses.append("created_at >= %s")
        params.append(frm)
    if to:
        clauses.append("created_at <= %s")
        params.append(to)
    return (" AND ".join(clauses), params)


def _safe_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. Funnel + cohort + time
# ---------------------------------------------------------------------------
class GroupBy(str, Enum):
    source = "source"
    department = "department"
    channel = "channel"


@router.get("/funnel")
async def funnel(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    group_by: GroupBy = Query(GroupBy.source),
):
    """Pipeline funnel grouped by candidate.source (or other dimension)."""
    get_current_user(request)
    try:
        with get_cursor() as cur:
            # Stage totals
            params: list = []
            where = ["TRUE"]
            if frm:
                where.append("pc.created_at >= %s"); params.append(frm)
            if to:
                where.append("pc.created_at <= %s"); params.append(to)
            wh = " AND ".join(where)

            stages_out = []
            for stg in STAGES:
                cur.execute(
                    f"""SELECT COUNT(DISTINCT pc.candidate_id)
                          FROM position_candidates pc
                         WHERE {wh} AND pc.stage = ANY(%s)""",
                    (*params, STAGES[STAGES.index(stg):]),
                )
                stages_out.append({"stage": stg, "count": int(cur.fetchone()[0] or 0)})

            # Group breakdown
            grp_col = {
                GroupBy.source: "c.source",
                GroupBy.department: "p.department",
                GroupBy.channel: "c.utm_source",
            }[group_by]

            by_group = []
            for stg in STAGES:
                cur.execute(
                    f"""SELECT COALESCE({grp_col}, 'unknown') AS grp, COUNT(DISTINCT pc.candidate_id) AS n
                          FROM position_candidates pc
                          JOIN candidates c ON c.id = pc.candidate_id
                          JOIN positions p ON p.id = pc.position_id
                         WHERE {wh} AND pc.stage = ANY(%s)
                         GROUP BY 1""",
                    (*params, STAGES[STAGES.index(stg):]),
                )
                for r in cur.fetchall():
                    by_group.append({
                        group_by.value: r[0],
                        "stage": stg,
                        "count": int(r[1] or 0),
                    })
        return {"stages": stages_out, f"by_{group_by.value}": by_group}
    except Exception as e:
        logger.warning(f"funnel failed: {e}")
        return {"stages": [{"stage": s, "count": 0} for s in STAGES], f"by_{group_by.value}": []}


@router.get("/cohort")
async def cohort(
    request: Request,
    metric: str = Query("offer_rate"),
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Monthly cohorts × stage matrix (cohort = candidate.applied_at month)."""
    get_current_user(request)
    try:
        params: list = []
        where = ["c.applied_at IS NOT NULL"]
        if frm:
            where.append("c.applied_at >= %s"); params.append(frm)
        if to:
            where.append("c.applied_at <= %s"); params.append(to)
        wh = " AND ".join(where)

        with get_cursor() as cur:
            cur.execute(
                f"""SELECT TO_CHAR(date_trunc('month', c.applied_at), 'YYYY-MM') AS cohort,
                           pc.stage, COUNT(DISTINCT c.id) AS n
                      FROM candidates c
                      LEFT JOIN position_candidates pc ON pc.candidate_id = c.id
                     WHERE {wh}
                  GROUP BY 1, 2
                  ORDER BY 1""",
                params,
            )
            rows = cur.fetchall()

        cohorts: Dict[str, Dict[str, int]] = {}
        for cohort_key, stage, n in rows:
            if cohort_key is None:
                continue
            cohorts.setdefault(cohort_key, {})
            cohorts[cohort_key][stage or "unknown"] = int(n or 0)

        return {
            "metric": metric,
            "cohorts": [
                {"cohort": k, "stages": v, "total": sum(v.values())}
                for k, v in sorted(cohorts.items())
            ],
        }
    except Exception as e:
        logger.warning(f"cohort failed: {e}")
        return {"metric": metric, "cohorts": []}


@router.get("/time-to-fill")
async def time_to_fill(
    request: Request,
    department: Optional[str] = Query(None),
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Avg/median/p90 days from position.created_at → first hire."""
    get_current_user(request)
    try:
        params: list = []
        where = ["pc.stage = 'hired'"]
        if department:
            where.append("p.department = %s"); params.append(department)
        if frm:
            where.append("p.created_at >= %s"); params.append(frm)
        if to:
            where.append("p.created_at <= %s"); params.append(to)
        wh = " AND ".join(where)

        with get_cursor() as cur:
            cur.execute(
                f"""WITH hires AS (
                        SELECT p.id, p.department,
                               EXTRACT(EPOCH FROM (MIN(pc.stage_changed_at) - p.created_at))/86400 AS days
                          FROM positions p
                          JOIN position_candidates pc ON pc.position_id = p.id
                         WHERE {wh}
                      GROUP BY p.id, p.department
                    )
                    SELECT ROUND(AVG(days)::numeric, 1) AS avg_d,
                           ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days))::numeric, 1) AS med,
                           ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY days))::numeric, 1) AS p90
                      FROM hires""",
                params,
            )
            row = cur.fetchone() or (None, None, None)

            cur.execute(
                f"""WITH hires AS (
                        SELECT p.id, p.department,
                               EXTRACT(EPOCH FROM (MIN(pc.stage_changed_at) - p.created_at))/86400 AS days
                          FROM positions p
                          JOIN position_candidates pc ON pc.position_id = p.id
                         WHERE {wh}
                      GROUP BY p.id, p.department
                    )
                    SELECT COALESCE(department,'unknown'),
                           ROUND(AVG(days)::numeric, 1),
                           COUNT(*)
                      FROM hires
                  GROUP BY 1
                  ORDER BY 2""",
                params,
            )
            by_dept = [{"department": r[0], "avg_days": _safe_float(r[1]), "hires": int(r[2])}
                       for r in cur.fetchall()]

        return {
            "avg_days": _safe_float(row[0]),
            "median_days": _safe_float(row[1]),
            "p90_days": _safe_float(row[2]),
            "by_department": by_dept,
        }
    except Exception as e:
        logger.warning(f"time-to-fill failed: {e}")
        return {"avg_days": 0, "median_days": 0, "p90_days": 0, "by_department": []}


@router.get("/time-per-stage")
async def time_per_stage(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Average days candidates spend in each stage."""
    get_current_user(request)
    try:
        params: list = []
        where = ["TRUE"]
        if frm: where.append("pc.created_at >= %s"); params.append(frm)
        if to: where.append("pc.created_at <= %s"); params.append(to)
        wh = " AND ".join(where)

        with get_cursor() as cur:
            # Use stage_history when available
            cur.execute(
                f"""SELECT pc.id, pc.stage, pc.stage_history, pc.created_at, pc.updated_at
                      FROM position_candidates pc
                     WHERE {wh}""",
                params,
            )
            rows = cur.fetchall()

        # Compute per-stage durations
        durations: Dict[str, list] = {s: [] for s in STAGES}
        for _id, stage, hist, created_at, updated_at in rows:
            try:
                if hist and isinstance(hist, list) and len(hist) > 1:
                    # consecutive transitions
                    for i in range(len(hist) - 1):
                        a = hist[i]; b = hist[i + 1]
                        s = a.get("stage")
                        try:
                            ta = datetime.fromisoformat(a["at"].replace("Z", "+00:00"))
                            tb = datetime.fromisoformat(b["at"].replace("Z", "+00:00"))
                            d = (tb - ta).total_seconds() / 86400
                            if s in durations and d >= 0:
                                durations[s].append(d)
                        except Exception:
                            continue
                else:
                    # Fallback: full duration assigned to current stage
                    if stage in durations and created_at and updated_at:
                        d = (updated_at - created_at).total_seconds() / 86400
                        if d >= 0:
                            durations[stage].append(d)
            except Exception:
                continue

        out = []
        for s in STAGES:
            arr = durations.get(s) or []
            avg = round(sum(arr) / len(arr), 2) if arr else 0.0
            out.append({"stage": s, "avg_days": avg, "n": len(arr)})
        return {"stages": out}
    except Exception as e:
        logger.warning(f"time-per-stage failed: {e}")
        return {"stages": [{"stage": s, "avg_days": 0, "n": 0} for s in STAGES]}


@router.get("/interviewer-turnaround")
async def interviewer_turnaround(request: Request):
    """Per-interviewer avg hours to scorecard + completion rate."""
    get_current_user(request)
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT
                    u.id,
                    COALESCE(u.display_name, u.email, 'unknown') AS name,
                    COUNT(DISTINCT i.id) AS n_interviews,
                    COUNT(DISTINCT s.id) AS n_scorecards,
                    ROUND(AVG(EXTRACT(EPOCH FROM (s.created_at - i.scheduled_at))/3600)::numeric, 1) AS avg_hrs
                FROM users u
                JOIN interviews i ON i.interviewer_id = u.id
                LEFT JOIN interview_scorecards s ON s.interview_id = i.id AND s.interviewer_id = u.id
                GROUP BY u.id, u.display_name, u.email
                ORDER BY n_interviews DESC
                LIMIT 100
            """)
            rows = cur.fetchall()

        out = []
        for r in rows:
            n_int = int(r[2] or 0)
            n_sc = int(r[3] or 0)
            out.append({
                "interviewer_id": r[0],
                "name": r[1],
                "n_interviews": n_int,
                "avg_hrs_to_scorecard": _safe_float(r[4]) or 0.0,
                "completion_rate": round(n_sc / n_int * 100, 1) if n_int else 0.0,
            })
        return out
    except Exception as e:
        logger.warning(f"interviewer-turnaround failed: {e}")
        return []


# ---------------------------------------------------------------------------
# 2. Recruiter scorecard
# ---------------------------------------------------------------------------
@router.get("/recruiter-scorecard")
async def recruiter_scorecard(
    request: Request,
    recruiter_id: int = Query(...),
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Per-recruiter KPIs."""
    get_current_user(request)
    try:
        params: list = [str(recruiter_id)]
        date_w = ""
        if frm:
            date_w += " AND pc.created_at >= %s"; params.append(frm)
        if to:
            date_w += " AND pc.created_at <= %s"; params.append(to)

        with get_cursor() as cur:
            cur.execute(
                f"""SELECT COUNT(*) AS added,
                           COUNT(*) FILTER (WHERE stage='hired') AS hired,
                           COUNT(*) FILTER (WHERE stage='offered') AS offers
                      FROM position_candidates pc
                     WHERE pc.added_by = %s {date_w}""",
                params,
            )
            r = cur.fetchone() or (0, 0, 0)
            added, hired, offers = int(r[0] or 0), int(r[1] or 0), int(r[2] or 0)

            # Avg score given by recruiter (interview_scorecards) + harshness
            cur.execute(
                """SELECT AVG(s.overall_score) AS my_avg,
                          (SELECT AVG(overall_score) FROM interview_scorecards) AS org_avg,
                          (SELECT STDDEV_SAMP(overall_score) FROM interview_scorecards) AS org_std,
                          AVG(EXTRACT(EPOCH FROM (s.created_at - i.scheduled_at))/3600) AS turnaround
                     FROM interview_scorecards s
                     JOIN interviews i ON i.id = s.interview_id
                    WHERE s.interviewer_id = %s""",
                (recruiter_id,),
            )
            sc = cur.fetchone() or (None, None, None, None)
            my_avg = _safe_float(sc[0])
            org_avg = _safe_float(sc[1])
            org_std = _safe_float(sc[2]) or 1.0
            turnaround = _safe_float(sc[3])

            harshness = 0.0
            if my_avg is not None and org_avg is not None and org_std:
                harshness = round((org_avg - my_avg) / (org_std or 1.0), 2)

        return {
            "recruiter_id": recruiter_id,
            "added": added,
            "hired": hired,
            "offers": offers,
            "avg_score_given": round(my_avg, 2) if my_avg is not None else None,
            "harshness_index": harshness,
            "avg_turnaround_hrs": round(turnaround, 1) if turnaround is not None else None,
            "std_dev_vs_org": round(org_std, 2) if org_std else None,
        }
    except Exception as e:
        logger.warning(f"recruiter-scorecard failed: {e}")
        return {"recruiter_id": recruiter_id, "added": 0, "hired": 0, "offers": 0,
                "avg_score_given": None, "harshness_index": 0.0,
                "avg_turnaround_hrs": None, "std_dev_vs_org": None}


@router.get("/recruiter-leaderboard")
async def recruiter_leaderboard(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Leaderboard sorted by hires desc."""
    get_current_user(request)
    try:
        params: list = []
        date_w = ""
        if frm:
            date_w += " AND pc.created_at >= %s"; params.append(frm)
        if to:
            date_w += " AND pc.created_at <= %s"; params.append(to)

        with get_cursor() as cur:
            cur.execute(
                f"""SELECT u.id, COALESCE(u.display_name, u.email, 'unknown') AS name, u.role,
                           COUNT(*) AS added,
                           COUNT(*) FILTER (WHERE pc.stage='hired') AS hired,
                           COUNT(*) FILTER (WHERE pc.stage='offered') AS offers
                      FROM users u
                      LEFT JOIN position_candidates pc
                             ON pc.added_by = u.id::text {date_w}
                     WHERE u.role IN ('recruiter','admin','hiring_manager')
                  GROUP BY u.id, u.display_name, u.email, u.role
                  ORDER BY hired DESC, added DESC
                  LIMIT 100""",
                params,
            )
            rows = cur.fetchall()

        return [
            {
                "recruiter_id": r[0], "name": r[1], "role": r[2],
                "added": int(r[3] or 0), "hired": int(r[4] or 0), "offers": int(r[5] or 0),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"recruiter-leaderboard failed: {e}")
        return []


# ---------------------------------------------------------------------------
# 3. DEI dashboard
# ---------------------------------------------------------------------------
class DEIDimension(str, Enum):
    gender = "gender"
    ethnicity = "ethnicity"
    veteran = "veteran"
    disability = "disability"


def _dim_col(d: DEIDimension) -> str:
    return {
        DEIDimension.gender: "gender",
        DEIDimension.ethnicity: "ethnicity",
        DEIDimension.veteran: "veteran_status",
        DEIDimension.disability: "disability_status",
    }[d]


@router.get("/diversity")
async def diversity(
    request: Request,
    dimension: DEIDimension = Query(DEIDimension.gender),
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Diversity counts per stage by dimension."""
    get_current_user(request)
    try:
        col = _dim_col(dimension)
        params: list = []
        where = ["TRUE"]
        if frm: where.append("pc.created_at >= %s"); params.append(frm)
        if to: where.append("pc.created_at <= %s"); params.append(to)
        wh = " AND ".join(where)

        with get_cursor() as cur:
            cur.execute(
                f"""SELECT pc.stage, COALESCE(e.{col}, 'prefer_not_to_say') AS grp, COUNT(*) AS n
                      FROM position_candidates pc
                      JOIN candidates c ON c.id = pc.candidate_id
                      LEFT JOIN eeo_data e ON e.candidate_id = c.id
                     WHERE {wh}
                  GROUP BY 1, 2""",
                params,
            )
            rows = cur.fetchall()

        by_stage: Dict[str, Dict[str, Any]] = {}
        for stage, grp, n in rows:
            stage = stage or "unknown"
            entry = by_stage.setdefault(stage, {"stage": stage, "total": 0, "groups": {}})
            entry["groups"][grp] = int(n or 0)
            entry["total"] += int(n or 0)

        return {"dimension": dimension.value, "by_stage": list(by_stage.values())}
    except Exception as e:
        logger.warning(f"diversity failed: {e}")
        return {"dimension": dimension.value, "by_stage": []}


@router.get("/diversity-dropoff")
async def diversity_dropoff(
    request: Request,
    dimension: DEIDimension = Query(DEIDimension.gender),
):
    """Pass-through % per group per stage transition."""
    get_current_user(request)
    try:
        col = _dim_col(dimension)
        with get_cursor() as cur:
            cur.execute(
                f"""SELECT pc.stage, COALESCE(e.{col}, 'prefer_not_to_say') AS grp, COUNT(*) AS n
                      FROM position_candidates pc
                      JOIN candidates c ON c.id = pc.candidate_id
                      LEFT JOIN eeo_data e ON e.candidate_id = c.id
                  GROUP BY 1, 2""",
            )
            rows = cur.fetchall()

        # group -> stage -> n
        gmap: Dict[str, Dict[str, int]] = {}
        for stage, grp, n in rows:
            gmap.setdefault(grp, {})[stage or "unknown"] = int(n or 0)

        out = []
        for grp, smap in gmap.items():
            base = smap.get("uploaded") or sum(smap.values()) or 1
            out.append({
                "group": grp,
                "stages": [
                    {
                        "stage": s,
                        "count": smap.get(s, 0),
                        "pass_through_pct": round((smap.get(s, 0) / base) * 100, 1) if base else 0,
                    }
                    for s in STAGES
                ],
            })
        return {"dimension": dimension.value, "groups": out}
    except Exception as e:
        logger.warning(f"diversity-dropoff failed: {e}")
        return {"dimension": dimension.value, "groups": []}


# ---------------------------------------------------------------------------
# 4. Cost-per-hire
# ---------------------------------------------------------------------------
class CostGroupBy(str, Enum):
    channel = "channel"
    department = "department"


class CostIn(BaseModel):
    period_start: str
    period_end: str
    category: str
    channel: Optional[str] = None
    amount: float
    currency: Optional[str] = "USD"
    position_id: Optional[int] = None
    notes: Optional[str] = None


@router.get("/cost-per-hire")
async def cost_per_hire(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    group_by: CostGroupBy = Query(CostGroupBy.channel),
):
    """Total spend, hires, CPH, ROI per channel/dept."""
    get_current_user(request)
    try:
        params: list = []
        where = ["TRUE"]
        if frm: where.append("rc.period_start >= %s"); params.append(frm)
        if to: where.append("rc.period_end <= %s"); params.append(to)
        wh = " AND ".join(where)

        params_h: list = []
        h_where = ["pc.stage = 'hired'"]
        if frm: h_where.append("pc.stage_changed_at >= %s"); params_h.append(frm)
        if to: h_where.append("pc.stage_changed_at <= %s"); params_h.append(to)
        h_wh = " AND ".join(h_where)

        with get_cursor() as cur:
            cur.execute(f"SELECT COALESCE(SUM(amount),0) FROM recruitment_costs rc WHERE {wh}", params)
            total_spend = float(cur.fetchone()[0] or 0)

            cur.execute(
                f"""SELECT COUNT(*) FROM position_candidates pc WHERE {h_wh}""",
                params_h,
            )
            hires = int(cur.fetchone()[0] or 0)

            if group_by == CostGroupBy.channel:
                cur.execute(
                    f"""SELECT COALESCE(rc.channel,'unknown'), SUM(rc.amount)
                          FROM recruitment_costs rc
                         WHERE {wh}
                      GROUP BY 1""", params,
                )
                spend_rows = cur.fetchall()
                cur.execute(
                    f"""SELECT COALESCE(c.utm_source,'unknown'), COUNT(*)
                          FROM position_candidates pc
                          JOIN candidates c ON c.id = pc.candidate_id
                         WHERE {h_wh}
                      GROUP BY 1""", params_h,
                )
                hire_rows = cur.fetchall()
            else:
                cur.execute(
                    f"""SELECT COALESCE(p.department,'unknown'), SUM(rc.amount)
                          FROM recruitment_costs rc
                          LEFT JOIN positions p ON p.id = rc.position_id
                         WHERE {wh}
                      GROUP BY 1""", params,
                )
                spend_rows = cur.fetchall()
                cur.execute(
                    f"""SELECT COALESCE(p.department,'unknown'), COUNT(*)
                          FROM position_candidates pc
                          JOIN positions p ON p.id = pc.position_id
                         WHERE {h_wh}
                      GROUP BY 1""", params_h,
                )
                hire_rows = cur.fetchall()

        spend_map = {r[0]: float(r[1] or 0) for r in spend_rows}
        hire_map = {r[0]: int(r[1] or 0) for r in hire_rows}
        keys = set(spend_map) | set(hire_map)

        by = []
        for k in keys:
            sp = spend_map.get(k, 0.0)
            h = hire_map.get(k, 0)
            cph = round(sp / h, 2) if h else None
            roi = round((h * 50000 - sp) / sp * 100, 1) if sp > 0 else None  # assume 50k value/hire
            by.append({group_by.value: k, "hires": h, "spend": sp, "cph": cph, "roi": roi})

        return {
            "total_spend": round(total_spend, 2),
            "hires": hires,
            "cost_per_hire": round(total_spend / hires, 2) if hires else None,
            "by": sorted(by, key=lambda x: -(x["spend"] or 0)),
        }
    except Exception as e:
        logger.warning(f"cost-per-hire failed: {e}")
        return {"total_spend": 0, "hires": 0, "cost_per_hire": None, "by": []}


@router.post("/costs", dependencies=[Depends(require_role("admin"))])
async def create_cost(request: Request, body: CostIn):
    user = get_current_user(request)
    try:
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO recruitment_costs
                       (period_start, period_end, category, channel, amount,
                        currency, position_id, notes, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id, created_at""",
                (body.period_start, body.period_end, body.category, body.channel,
                 body.amount, body.currency, body.position_id, body.notes,
                 user.get("user_id")),
            )
            r = cur.fetchone()
        return {"id": r[0], "created_at": r[1]}
    except Exception as e:
        logger.exception("create_cost")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/costs")
async def list_costs(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    try:
        params: list = []
        where = ["TRUE"]
        if frm: where.append("period_start >= %s"); params.append(frm)
        if to: where.append("period_end <= %s"); params.append(to)
        wh = " AND ".join(where)
        with get_cursor() as cur:
            cur.execute(
                f"""SELECT id, period_start, period_end, category, channel, amount, currency,
                           position_id, notes, created_by, created_at
                      FROM recruitment_costs
                     WHERE {wh}
                  ORDER BY period_start DESC, id DESC""",
                params,
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for row in rows:
                row["amount"] = float(row["amount"]) if row.get("amount") is not None else 0.0
        return {"items": rows}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"list_costs failed: {e}")
        return {"items": []}


# ---------------------------------------------------------------------------
# 5. Quality of hire
# ---------------------------------------------------------------------------
class QohIn(BaseModel):
    period: str  # '90d' | '180d' | '360d'
    rating: float
    retained: bool
    notes: Optional[str] = None


@router.post("/qoh/{candidate_id}", dependencies=[Depends(require_role("recruiter"))])
async def submit_qoh(candidate_id: int, request: Request, body: QohIn):
    user = get_current_user(request)
    if body.period not in ("90d", "180d", "360d"):
        raise HTTPException(400, "period must be 90d|180d|360d")
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT pc.position_id, pc.stage_changed_at
                     FROM position_candidates pc
                    WHERE pc.candidate_id = %s AND pc.stage = 'hired'
                 ORDER BY pc.stage_changed_at DESC LIMIT 1""",
                (candidate_id,),
            )
            row = cur.fetchone()
            position_id = row[0] if row else None
            hired_at = row[1] if row else None

            cur.execute(
                """INSERT INTO qoh_reviews
                       (candidate_id, position_id, hired_at, period, manager_rating,
                        retained, notes, submitted_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id, created_at""",
                (candidate_id, position_id, hired_at, body.period,
                 body.rating, body.retained, body.notes, user.get("user_id")),
            )
            r = cur.fetchone()
        return {"id": r[0], "created_at": r[1]}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("submit_qoh")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/qoh/pending")
async def qoh_pending(request: Request):
    """Hires whose 90/180/360 review is due and missing."""
    get_current_user(request)
    try:
        out = []
        with get_cursor() as cur:
            cur.execute("""
                SELECT pc.candidate_id, c.name, pc.stage_changed_at
                  FROM position_candidates pc
                  JOIN candidates c ON c.id = pc.candidate_id
                 WHERE pc.stage = 'hired' AND pc.stage_changed_at IS NOT NULL
            """)
            hires = cur.fetchall()

            for cand_id, name, hired_at in hires:
                if not hired_at:
                    continue
                hired_dt = hired_at if isinstance(hired_at, datetime) else datetime.fromisoformat(str(hired_at))
                # Treat as UTC-naive for comparison
                now_naive = datetime.utcnow()
                hired_naive = hired_dt.replace(tzinfo=None) if hired_dt.tzinfo else hired_dt
                days = (now_naive - hired_naive).days
                for period, threshold in (("90d", 90), ("180d", 180), ("360d", 360)):
                    if days >= threshold:
                        cur.execute(
                            "SELECT 1 FROM qoh_reviews WHERE candidate_id=%s AND period=%s LIMIT 1",
                            (cand_id, period),
                        )
                        if not cur.fetchone():
                            out.append({
                                "candidate_id": cand_id,
                                "name": name,
                                "hired_at": hired_naive.isoformat(),
                                "period_due": period,
                                "days_since_hire": days,
                            })
        return {"items": out}
    except Exception as e:
        logger.warning(f"qoh_pending failed: {e}")
        return {"items": []}


@router.get("/quality-of-hire")
async def quality_of_hire(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    period: str = Query("90d"),
):
    get_current_user(request)
    try:
        params: list = [period]
        where = ["q.period = %s"]
        if frm: where.append("q.review_at >= %s"); params.append(frm)
        if to: where.append("q.review_at <= %s"); params.append(to)
        wh = " AND ".join(where)

        with get_cursor() as cur:
            cur.execute(
                f"""SELECT AVG(manager_rating),
                           AVG(CASE WHEN retained THEN 1.0 ELSE 0.0 END) * 100
                      FROM qoh_reviews q WHERE {wh}""",
                params,
            )
            r = cur.fetchone() or (None, None)
            avg_rating = _safe_float(r[0])
            retention_pct = _safe_float(r[1])

            cur.execute(
                f"""SELECT COALESCE(c.source,'unknown'),
                           AVG(q.manager_rating), COUNT(*)
                      FROM qoh_reviews q
                      JOIN candidates c ON c.id = q.candidate_id
                     WHERE {wh}
                  GROUP BY 1""",
                params,
            )
            by_source = [{"source": r[0], "avg_rating": _safe_float(r[1]), "n": int(r[2])}
                         for r in cur.fetchall()]

            cur.execute(
                f"""SELECT q.submitted_by,
                           COALESCE(u.display_name, u.email, 'unknown'),
                           AVG(q.manager_rating), COUNT(*)
                      FROM qoh_reviews q
                      LEFT JOIN users u ON u.id = q.submitted_by
                     WHERE {wh}
                  GROUP BY 1, 2""",
                params,
            )
            by_recruiter = [{"recruiter_id": r[0], "name": r[1],
                             "avg_rating": _safe_float(r[2]), "n": int(r[3])}
                            for r in cur.fetchall()]

        return {
            "period": period,
            "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
            "retention_pct": round(retention_pct, 1) if retention_pct is not None else None,
            "by_source": by_source,
            "by_recruiter": by_recruiter,
        }
    except Exception as e:
        logger.warning(f"quality-of-hire failed: {e}")
        return {"period": period, "avg_rating": None, "retention_pct": None,
                "by_source": [], "by_recruiter": []}


# ---------------------------------------------------------------------------
# 6. Predictive
# ---------------------------------------------------------------------------
@router.get("/forecast/{slug}")
async def forecast(slug: str, request: Request):
    get_current_user(request)
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, department, title, forecast_days_to_fill, forecast_confidence
                     FROM positions WHERE slug = %s""",
                (slug,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Position not found")
            pos_id, dept, title, cached_days, cached_conf = row

            # Find comparable positions
            cur.execute(
                """SELECT p.id, p.title,
                          EXTRACT(EPOCH FROM (MIN(pc.stage_changed_at) - p.created_at))/86400 AS days
                     FROM positions p
                     JOIN position_candidates pc ON pc.position_id = p.id
                    WHERE pc.stage = 'hired'
                      AND p.id <> %s
                      AND COALESCE(p.department,'') = COALESCE(%s,'')
                 GROUP BY p.id, p.title
                 ORDER BY days ASC
                    LIMIT 50""",
                (pos_id, dept),
            )
            comps = cur.fetchall()

        days_list = [float(c[2]) for c in comps if c[2] is not None]
        if days_list:
            days_list.sort()
            mid = len(days_list) // 2
            median = days_list[mid] if len(days_list) % 2 else (days_list[mid - 1] + days_list[mid]) / 2
        else:
            median = _safe_float(cached_days)

        confidence = "high" if len(days_list) >= 5 else ("medium" if len(days_list) >= 3 else "low")

        return {
            "slug": slug,
            "title": title,
            "days_to_fill": round(median, 1) if median is not None else None,
            "confidence": confidence,
            "comparable_positions": [
                {"id": c[0], "title": c[1], "days": round(float(c[2]), 1)}
                for c in comps[:10] if c[2] is not None
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"forecast failed: {e}")
        return {"slug": slug, "days_to_fill": None, "confidence": "low",
                "comparable_positions": []}


def compute_lth(pc: dict, flags: list[dict]) -> tuple[float, list[dict]]:
    """Heuristic: sigmoid(0.4*composite + 0.3*green - 0.2*red - 0.1*age/30 + 0.2*pos_sc)."""
    composite = float(pc.get("match_score_composite") or 0) / 100.0  # normalize
    green = sum(1 for f in flags if f.get("flag_type") == "green")
    red = sum(1 for f in flags if f.get("flag_type") == "red")
    pos_sc = float(pc.get("avg_scorecard") or 0) / 5.0  # normalize 1..5 → 0..1
    age_days = float(pc.get("stage_age_days") or 0)

    x = (0.4 * composite) + (0.3 * green) - (0.2 * red) - (0.1 * age_days / 30.0) + (0.2 * pos_sc)
    p = _sigmoid(x)

    features = [
        {"name": "composite_match", "contribution": round(0.4 * composite, 3)},
        {"name": "green_flags", "contribution": round(0.3 * green, 3)},
        {"name": "red_flags", "contribution": round(-0.2 * red, 3)},
        {"name": "stage_age_penalty", "contribution": round(-0.1 * age_days / 30.0, 3)},
        {"name": "positive_scorecard", "contribution": round(0.2 * pos_sc, 3)},
    ]
    return round(p, 4), features


@router.get("/likelihood/{candidate_id}")
async def likelihood(
    candidate_id: int, request: Request,
    position_id: Optional[int] = Query(None),
):
    get_current_user(request)
    try:
        with get_cursor() as cur:
            params = [candidate_id]
            cond = "pc.candidate_id = %s"
            if position_id:
                cond += " AND pc.position_id = %s"
                params.append(position_id)
            cur.execute(
                f"""SELECT pc.id, pc.position_id, pc.match_score_composite, pc.stage,
                           pc.created_at, pc.stage_changed_at,
                           (SELECT AVG(s.overall_score)
                              FROM interview_scorecards s
                              JOIN interviews i ON i.id = s.interview_id
                             WHERE i.candidate_id = pc.candidate_id
                               AND i.position_id = pc.position_id) AS avg_scorecard
                      FROM position_candidates pc
                     WHERE {cond}
                  ORDER BY pc.created_at DESC LIMIT 1""",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "No position_candidate found")
            cols = [d[0] for d in cur.description]
            pc = dict(zip(cols, row))

            cur.execute(
                """SELECT flag_type, category, title FROM candidate_flags
                    WHERE candidate_id = %s AND position_id = %s""",
                (candidate_id, pc["position_id"]),
            )
            fcols = [d[0] for d in cur.description]
            flags = [dict(zip(fcols, r)) for r in cur.fetchall()]

        ref = pc.get("stage_changed_at") or pc.get("created_at")
        age_days = 0
        if ref:
            try:
                ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
                age_days = (datetime.utcnow() - ref_naive).days
            except Exception:
                age_days = 0
        pc["stage_age_days"] = age_days

        prob, features = compute_lth(pc, flags)
        return {
            "candidate_id": candidate_id,
            "position_id": pc["position_id"],
            "probability": prob,
            "top_features": sorted(features, key=lambda f: -abs(f["contribution"])),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"likelihood failed: {e}")
        return {"candidate_id": candidate_id, "probability": 0.0, "top_features": []}


# ---------------------------------------------------------------------------
# Competency analytics
# ---------------------------------------------------------------------------
@router.get("/competency-calibration")
async def competency_calibration(
    request: Request,
    frm: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    """Per-interviewer per-competency avg + std-dev + harshness vs org."""
    get_current_user(request)
    conds = ["cc.source = 'scorecard'"]
    params: list = []
    if frm:
        conds.append("cc.rated_at >= %s::timestamptz"); params.append(frm)
    if to:
        conds.append("cc.rated_at <= %s::timestamptz"); params.append(to)
    where = "WHERE " + " AND ".join(conds)
    with get_cursor() as cur:
        # Per-comp org averages
        cur.execute(f"""
            SELECT cc.competency_id, c.key, c.label,
                   AVG(cc.level)::numeric AS org_avg,
                   STDDEV_POP(cc.level)::numeric AS org_std,
                   COUNT(*) AS org_n
            FROM candidate_competencies cc
            JOIN competencies c ON c.id = cc.competency_id
            {where}
            GROUP BY cc.competency_id, c.key, c.label
        """, params)
        org_by_comp = {r[0]: {"key": r[1], "label": r[2], "org_avg": float(r[3] or 0), "org_std": float(r[4] or 0), "org_n": r[5]} for r in cur.fetchall()}

        cur.execute(f"""
            SELECT cc.rated_by, u.display_name,
                   cc.competency_id,
                   AVG(cc.level)::numeric AS avg_lvl,
                   STDDEV_POP(cc.level)::numeric AS std_lvl,
                   COUNT(*) AS n
            FROM candidate_competencies cc
            LEFT JOIN users u ON u.id = cc.rated_by
            JOIN competencies c ON c.id = cc.competency_id
            {where}
            GROUP BY cc.rated_by, u.display_name, cc.competency_id
            ORDER BY cc.rated_by, cc.competency_id
        """, params)
        rows = cur.fetchall()

    by_user: dict = {}
    for uid, uname, comp_id, avg, std, n in rows:
        org = org_by_comp.get(comp_id, {})
        org_avg = org.get("org_avg", 0)
        harshness = float(avg or 0) - org_avg
        u_entry = by_user.setdefault(uid or 0, {
            "user_id": uid,
            "display_name": uname,
            "per_comp": [],
        })
        u_entry["per_comp"].append({
            "competency_id": comp_id,
            "key": org.get("key"),
            "label": org.get("label"),
            "avg": round(float(avg or 0), 2),
            "std": round(float(std or 0), 2),
            "n": n,
            "org_avg": round(org_avg, 2),
            "harshness": round(harshness, 2),
        })
    return {"interviewers": list(by_user.values()), "competencies": list(org_by_comp.values())}


@router.get("/competency-gaps")
async def competency_gaps(
    request: Request,
    slug: Optional[str] = Query(None),
):
    """Org-wide gap distribution per competency."""
    get_current_user(request)
    conds = []
    params: list = []
    join = ""
    if slug:
        join = "JOIN positions p ON p.id = pc.position_id"
        conds.append("p.slug = %s"); params.append(slug)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_cursor() as cur:
        cur.execute(f"""
            SELECT pc.position_id, pc.competency_id, c.key, c.label,
                   pc.required_level, pc.importance,
                   COUNT(DISTINCT cand.candidate_id) AS pcand_count,
                   AVG(cc.level)::numeric AS avg_actual
            FROM position_competencies pc
            JOIN competencies c ON c.id = pc.competency_id
            {join}
            LEFT JOIN position_candidates cand ON cand.position_id = pc.position_id
            LEFT JOIN candidate_competencies cc
                   ON cc.candidate_id = cand.candidate_id
                  AND cc.competency_id = pc.competency_id
            {where}
            GROUP BY pc.position_id, pc.competency_id, c.key, c.label, pc.required_level, pc.importance
            ORDER BY c.label
        """, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        avg = float(r.get("avg_actual") or 0)
        req = float(r.get("required_level") or 0)
        r["avg_actual"] = round(avg, 2)
        r["avg_gap"] = round(avg - req, 2)
    return {"gaps": rows, "total": len(rows)}

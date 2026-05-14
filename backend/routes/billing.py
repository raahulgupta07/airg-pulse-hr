"""Billing / LLM cost dashboard endpoints.

Reads from `llm_call_log` (per-call ledger) and `pipeline_trace`
(per-step CV pipeline cost). All endpoints superadmin-gated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import csv
import io

from backend.core.auth import get_current_user
from backend.core.database import get_cursor

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _require_admin(request: Request):
    user = get_current_user(request)
    if user.get("role") not in ("superadmin", "admin"):
        raise HTTPException(403, "BILLING_ADMIN_ONLY")
    return user


def _range_to_window(rng: str):
    now = datetime.now(timezone.utc)
    if rng == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif rng == "7d":
        start = now - timedelta(days=7)
    elif rng == "30d":
        start = now - timedelta(days=30)
    elif rng == "mtd":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=1)
    return start, now


@router.get("/summary")
def summary(range: str = Query("today"), user=Depends(_require_admin)):
    start, end = _range_to_window(range)
    with get_cursor() as cur:
        cur.execute(
            """SELECT
                 COALESCE(SUM(cost_usd),0)        AS total_cost,
                 COALESCE(SUM(in_tokens),0)       AS in_tokens,
                 COALESCE(SUM(out_tokens),0)      AS out_tokens,
                 COUNT(*)                         AS calls,
                 COALESCE(AVG(latency_ms),0)::int AS avg_latency,
                 COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms),0)::int AS p95_latency,
                 SUM(CASE WHEN status LIKE 'timeout%%' THEN 1 ELSE 0 END) AS timeouts,
                 SUM(CASE WHEN status LIKE 'error%%' OR status LIKE 'cap_%%' THEN 1 ELSE 0 END) AS fails
               FROM llm_call_log
               WHERE ts >= %s AND ts <= %s""",
            (start, end),
        )
        row = cur.fetchone()
        cur.execute(
            "SELECT COUNT(DISTINCT run_id) FROM llm_call_log WHERE ts >= %s AND ts <= %s AND run_id IS NOT NULL",
            (start, end),
        )
        jobs = cur.fetchone()[0]
    import os
    cap = float(os.getenv("LLM_DAILY_CAP_USD", "200"))
    total = float(row[0])
    def _i(v): return int(v or 0)
    return {
        "range": range,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_cost": round(total, 4),
        "cap_usd": cap,
        "cap_used_pct": round(min(100.0, (total / cap * 100) if cap > 0 else 0), 2),
        "in_tokens": _i(row[1]),
        "out_tokens": _i(row[2]),
        "total_tokens": _i(row[1]) + _i(row[2]),
        "calls": _i(row[3]),
        "avg_latency_ms": _i(row[4]),
        "p95_latency_ms": _i(row[5]),
        "timeouts": _i(row[6]),
        "fails": _i(row[7]),
        "jobs": _i(jobs),
        "fail_rate_pct": round((_i(row[7]) / _i(row[3]) * 100) if row[3] else 0, 2),
    }


@router.get("/by-model")
def by_model(range: str = Query("today"), user=Depends(_require_admin)):
    start, end = _range_to_window(range)
    with get_cursor() as cur:
        cur.execute(
            """SELECT model, COUNT(*) AS calls,
                      COALESCE(SUM(in_tokens+out_tokens),0) AS tokens,
                      COALESCE(SUM(cost_usd),0) AS cost
               FROM llm_call_log
               WHERE ts >= %s AND ts <= %s
               GROUP BY model ORDER BY cost DESC""",
            (start, end),
        )
        rows = cur.fetchall()
    return [{"model": r[0], "calls": int(r[1]), "tokens": int(r[2]), "cost_usd": round(float(r[3]), 4)} for r in rows]


@router.get("/by-step")
def by_step(range: str = Query("today"), user=Depends(_require_admin)):
    start, end = _range_to_window(range)
    with get_cursor() as cur:
        cur.execute(
            """SELECT COALESCE(step,'(other)') AS step, COUNT(*) AS calls,
                      COALESCE(AVG(cost_usd),0)::numeric(10,4) AS avg_cost,
                      COALESCE(SUM(cost_usd),0) AS total_cost
               FROM llm_call_log
               WHERE ts >= %s AND ts <= %s
               GROUP BY step ORDER BY total_cost DESC""",
            (start, end),
        )
        rows = cur.fetchall()
    return [{"step": r[0], "calls": int(r[1]), "avg_cost": float(r[2]), "total_cost": round(float(r[3]), 4)} for r in rows]


@router.get("/hourly")
def hourly(range: str = Query("today"), user=Depends(_require_admin)):
    start, end = _range_to_window(range)
    with get_cursor() as cur:
        cur.execute(
            """SELECT date_trunc('hour', ts) AS hr,
                      COALESCE(SUM(cost_usd),0) AS cost
               FROM llm_call_log
               WHERE ts >= %s AND ts <= %s
               GROUP BY hr ORDER BY hr""",
            (start, end),
        )
        rows = cur.fetchall()
    return [{"hour": r[0].isoformat(), "cost_usd": round(float(r[1]), 4)} for r in rows]


@router.get("/jobs")
def jobs(range: str = Query("today"), page: int = Query(1, ge=1),
         per_page: int = Query(25, ge=1, le=200), user=Depends(_require_admin)):
    start, end = _range_to_window(range)
    offset = (page - 1) * per_page
    with get_cursor() as cur:
        cur.execute(
            """SELECT run_id,
                      MIN(candidate_id)         AS cand_id,
                      MIN(ts)                   AS started,
                      COUNT(*)                  AS steps,
                      COALESCE(SUM(cost_usd),0) AS total_cost,
                      COALESCE(SUM(in_tokens+out_tokens),0) AS tokens,
                      EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts)))::int AS duration_s,
                      MAX(CASE WHEN status NOT LIKE 'ok%%' THEN status END) AS bad_status
               FROM llm_call_log
               WHERE ts >= %s AND ts <= %s AND run_id IS NOT NULL
               GROUP BY run_id
               ORDER BY started DESC
               LIMIT %s OFFSET %s""",
            (start, end, per_page, offset),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT COUNT(DISTINCT run_id) FROM llm_call_log WHERE ts >= %s AND ts <= %s AND run_id IS NOT NULL",
            (start, end),
        )
        total = cur.fetchone()[0]

        # Resolve candidate names
        cand_ids = [r[1] for r in rows if r[1]]
        names = {}
        if cand_ids:
            cur.execute("SELECT id, COALESCE(name,'unnamed') FROM candidates WHERE id = ANY(%s)", (cand_ids,))
            names = {r[0]: r[1] for r in cur.fetchall()}
    return {
        "total": int(total),
        "page": page,
        "per_page": per_page,
        "rows": [
            {
                "run_id": r[0],
                "candidate_id": r[1],
                "candidate_name": names.get(r[1], "—"),
                "started": r[2].isoformat() if r[2] else None,
                "steps": int(r[3]),
                "total_cost": round(float(r[4]), 4),
                "tokens": int(r[5]),
                "duration_s": int(r[6] or 0),
                "status": r[7] or "ok",
            }
            for r in rows
        ],
    }


@router.get("/top")
def top(range: str = Query("today"), limit: int = Query(5, ge=1, le=50), user=Depends(_require_admin)):
    start, end = _range_to_window(range)
    with get_cursor() as cur:
        cur.execute(
            """SELECT ts, model, step, candidate_id, in_tokens, out_tokens, cost_usd, status
               FROM llm_call_log
               WHERE ts >= %s AND ts <= %s
               ORDER BY cost_usd DESC LIMIT %s""",
            (start, end, limit),
        )
        rows = cur.fetchall()
    return [
        {"ts": r[0].isoformat(), "model": r[1], "step": r[2], "candidate_id": r[3],
         "in_tokens": int(r[4]), "out_tokens": int(r[5]), "cost_usd": round(float(r[6]), 4),
         "status": r[7]}
        for r in rows
    ]


@router.get("/job/{run_id}")
def job_detail(run_id: str, user=Depends(_require_admin)):
    with get_cursor() as cur:
        cur.execute(
            """SELECT step, model, in_tokens, out_tokens, cost_usd, latency_ms, status, ts
               FROM llm_call_log WHERE run_id = %s ORDER BY ts""",
            (run_id,),
        )
        rows = cur.fetchall()
    return {
        "run_id": run_id,
        "steps": [
            {"step": r[0], "model": r[1], "in_tokens": int(r[2]), "out_tokens": int(r[3]),
             "cost_usd": round(float(r[4]), 4), "latency_ms": int(r[5] or 0),
             "status": r[6], "ts": r[7].isoformat()}
            for r in rows
        ],
        "totals": {
            "cost_usd": round(sum(float(r[4]) for r in rows), 4),
            "in_tokens": sum(int(r[2]) for r in rows),
            "out_tokens": sum(int(r[3]) for r in rows),
            "latency_ms": sum(int(r[5] or 0) for r in rows),
        },
    }


@router.get("/export.csv")
def export_csv(range: str = Query("today"), user=Depends(_require_admin)):
    start, end = _range_to_window(range)

    def stream():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "tenant", "operator", "candidate_id", "run_id", "step",
                    "model", "in_tokens", "out_tokens", "cost_usd", "latency_ms", "status"])
        yield buf.getvalue()
        buf.seek(0); buf.truncate()
        with get_cursor() as cur:
            cur.execute(
                """SELECT ts, tenant_id, operator_id, candidate_id, run_id, step,
                          model, in_tokens, out_tokens, cost_usd, latency_ms, status
                   FROM llm_call_log
                   WHERE ts >= %s AND ts <= %s ORDER BY ts""",
                (start, end),
            )
            for r in cur:
                w.writerow(r)
                yield buf.getvalue()
                buf.seek(0); buf.truncate()

    fname = f"pulse_billing_{range}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(stream(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})

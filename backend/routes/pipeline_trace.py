"""Pipeline trace API — per-CV stepwise pipeline visibility."""
from __future__ import annotations

from fastapi import APIRouter, Request, Query

from backend.core.auth import get_current_user
from backend.core.database import get_cursor

router = APIRouter()


@router.get("/candidates/{candidate_id}/pipeline_trace")
async def get_trace(candidate_id: int, request: Request, run_id: str | None = Query(None)):
    get_current_user(request)
    with get_cursor() as cur:
        if run_id:
            cur.execute("""
                SELECT id, run_id, step_order, step_name, model, status,
                       latency_ms, cost_usd, input_tokens, output_tokens,
                       details, error_msg, started_at, finished_at
                FROM pipeline_trace
                WHERE candidate_id = %s AND run_id = %s::uuid
                ORDER BY step_order ASC, started_at ASC
            """, (candidate_id, run_id))
        else:
            cur.execute("""
                SELECT id, run_id, step_order, step_name, model, status,
                       latency_ms, cost_usd, input_tokens, output_tokens,
                       details, error_msg, started_at, finished_at
                FROM pipeline_trace
                WHERE candidate_id = %s
                ORDER BY started_at DESC, step_order ASC
            """, (candidate_id,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            for k in ("started_at", "finished_at"):
                if r.get(k):
                    r[k] = r[k].isoformat()
            if r.get("cost_usd") is not None:
                r["cost_usd"] = float(r["cost_usd"])
            if r.get("run_id") is not None:
                r["run_id"] = str(r["run_id"])

    runs: dict[str, list] = {}
    for r in rows:
        runs.setdefault(r["run_id"], []).append(r)
    runs_list = []
    for k, v in runs.items():
        steps = sorted(v, key=lambda s: s["step_order"])
        runs_list.append({
            "run_id": k,
            "steps": steps,
            "total_cost": round(sum((s["cost_usd"] or 0) for s in v), 6),
            "total_latency_ms": sum((s["latency_ms"] or 0) for s in v),
            "started_at": min((s["started_at"] for s in v if s.get("started_at")), default=None),
        })
    runs_list.sort(key=lambda r: r["started_at"] or "", reverse=True)
    return {"runs": runs_list}

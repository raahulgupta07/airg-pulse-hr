"""Agent session helpers — agent_runs + tool_traces ledger writes.

- start_run(session_id, tenant_id, operator_id) -> run_id (uuid)
- record_tool_call(run_id, step_idx, tool, input, output, latency_ms, status, error)
- close_run(run_id, in_tokens, out_tokens, cost_usd, status, error)
- get_or_create_session(user_id, position_id, title) -> session_id
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from backend.core.database import get_cursor, create_chat_session

logger = logging.getLogger(__name__)


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return json.dumps({"_repr": str(obj)[:2000]})


def start_run(session_id: Optional[int], tenant_id: Optional[int],
              operator_id: Optional[int]) -> str:
    """Create an agent_runs row and return the new run_id (uuid hex)."""
    run_id = uuid.uuid4().hex
    try:
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO agent_runs
                   (run_id, session_id, tenant_id, operator_id, status)
                   VALUES (%s, %s, %s, %s, 'running')""",
                (run_id, session_id, tenant_id, operator_id),
            )
    except Exception as e:
        logger.warning(f"start_run insert failed: {e}")
    return run_id


def record_tool_call(run_id: str, step_idx: int, tool: str,
                     input: Any = None, output: Any = None,
                     latency_ms: int = 0, status: str = "ok",
                     error: Optional[str] = None) -> None:
    """Append a tool_traces row. Best-effort; never raises."""
    try:
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO tool_traces
                   (run_id, step_idx, tool, input, output, latency_ms, status, error)
                   VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)""",
                (run_id, int(step_idx), tool,
                 _safe_json(input), _safe_json(output),
                 int(latency_ms or 0), status, error),
            )
    except Exception as e:
        logger.warning(f"record_tool_call failed: {e}")


def close_run(run_id: str, in_tokens: int = 0, out_tokens: int = 0,
              cost_usd: float = 0.0, status: str = "ok",
              error: Optional[str] = None,
              steps: Optional[int] = None) -> None:
    """Mark agent_runs row finished with totals."""
    try:
        with get_cursor() as cur:
            if steps is not None:
                cur.execute(
                    """UPDATE agent_runs
                       SET ended_at = NOW(),
                           in_tokens = %s, out_tokens = %s, cost_usd = %s,
                           status = %s, error = %s, steps = %s
                       WHERE run_id = %s""",
                    (int(in_tokens), int(out_tokens), float(cost_usd),
                     status, error, int(steps), run_id),
                )
            else:
                cur.execute(
                    """UPDATE agent_runs
                       SET ended_at = NOW(),
                           in_tokens = %s, out_tokens = %s, cost_usd = %s,
                           status = %s, error = %s
                       WHERE run_id = %s""",
                    (int(in_tokens), int(out_tokens), float(cost_usd),
                     status, error, run_id),
                )
    except Exception as e:
        logger.warning(f"close_run failed: {e}")


def get_or_create_session(user_id: Optional[int],
                          position_id: Optional[int] = None,
                          title: Optional[str] = None) -> int:
    """Return an existing or newly created chat_sessions row id."""
    return create_chat_session(
        user_id=user_id, position_id=position_id, title=title,
    )

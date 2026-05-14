"""Per-tenant daily LLM cost cap with in-memory accounting.

Used by the central LLM client wrapper to bound runaway spend.
Resets daily (keyed by UTC date). For multi-tenant deployments wire
`tenant_id` from request context; otherwise pass "default".
"""
from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CostCapExceeded(Exception):
    """Raised when tenant exceeds the configured daily LLM spend cap."""


# $/1k tokens — rough order-of-magnitude only. Conservative default for unknowns.
PRICE_PER_1K: dict[str, float] = {
    "gemini-3-flash": 0.0001,
    "google/gemini-3-flash-preview": 0.0001,
    "google/gemini-3.1-flash-lite-preview": 0.00005,
    "gpt-5.4-mini": 0.0005,
    "openai/gpt-5.4-mini": 0.0005,
    "claude-opus-4-7": 0.015,
    "anthropic/claude-opus-4.7": 0.015,
}
DEFAULT_PRICE_PER_1K = 0.001


def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _cap() -> float:
    try:
        return float(os.getenv("LLM_DAILY_CAP_USD", "50"))
    except ValueError:
        return 50.0


def estimate_cost(model: str, est_tokens: int) -> float:
    rate = PRICE_PER_1K.get(model, DEFAULT_PRICE_PER_1K)
    return (est_tokens / 1000.0) * rate


# (tenant_id, date) -> cumulative USD
_spend: dict[tuple[str, str], float] = {}
_lock = asyncio.Lock()


async def check_and_record(tenant_id: str, model: str, est_tokens: int) -> None:
    """Raise CostCapExceeded if this call would push tenant over the daily cap.

    Otherwise, record the estimated cost and return.
    """
    tenant_id = tenant_id or "default"
    cost = estimate_cost(model, max(0, int(est_tokens)))
    cap = _cap()
    key = (tenant_id, _today_key())
    async with _lock:
        cur = _spend.get(key, 0.0)
        if cur + cost > cap:
            logger.warning(
                f"[cost_cap] tenant={tenant_id} model={model} would exceed cap: "
                f"current=${cur:.4f} +${cost:.4f} > cap=${cap:.2f}"
            )
            raise CostCapExceeded(
                f"Daily LLM spend cap ${cap:.2f} reached for tenant '{tenant_id}' "
                f"(current ${cur:.4f}, requested +${cost:.4f})"
            )
        _spend[key] = cur + cost


async def record_actual(tenant_id: str, model: str, actual_tokens: int) -> float:
    """Adjust spend after a call with the real token count. Returns updated total."""
    tenant_id = tenant_id or "default"
    cost = estimate_cost(model, max(0, int(actual_tokens)))
    key = (tenant_id, _today_key())
    async with _lock:
        _spend[key] = _spend.get(key, 0.0) + cost
        return _spend[key]


def get_spend(tenant_id: str = "default") -> float:
    return _spend.get((tenant_id, _today_key()), 0.0)


def reset(tenant_id: str | None = None) -> None:
    """Test/admin helper. If tenant_id is None, clear everything."""
    if tenant_id is None:
        _spend.clear()
        return
    key = (tenant_id, _today_key())
    _spend.pop(key, None)

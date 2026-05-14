"""Configuration — LLM models, embedding cascade, app settings."""
from __future__ import annotations

import os
import re
import json
import time
import asyncio
import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety primitives (timeouts, cost cap, structured call log)
# ---------------------------------------------------------------------------
LLM_CALL_TIMEOUT_S = float(os.getenv("LLM_CALL_TIMEOUT_S", "60"))


class LLMTimeoutError(Exception):
    """Raised when an LLM call exceeds LLM_CALL_TIMEOUT_S."""


_llm_call_logger = logging.getLogger("llm.calls")


def _log_llm_call(*, tenant: str, model: str, latency_ms: int,
                  in_tokens: int, out_tokens: int, cost_usd: float,
                  status: str, step: str | None = None,
                  candidate_id: int | None = None, run_id: str | None = None,
                  operator_id: str | None = None, error: str | None = None) -> None:
    payload = {
        "ts": time.time(),
        "tenant": tenant,
        "model": model,
        "latency_ms": latency_ms,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "cost_usd": round(cost_usd, 6),
        "status": status,
        "step": step,
        "candidate_id": candidate_id,
        "run_id": run_id,
    }
    _llm_call_logger.info(json.dumps(payload))
    # Persist to DB ledger so /billing dashboard can query historical cost.
    # Best-effort — never block / fail the actual LLM call.
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute(
                """INSERT INTO llm_call_log
                   (tenant_id, operator_id, candidate_id, run_id, step, model,
                    in_tokens, out_tokens, cost_usd, latency_ms, status, error)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (tenant, operator_id, candidate_id, run_id, step, model,
                 in_tokens, out_tokens, round(cost_usd, 6), latency_ms, status, error),
            )
    except Exception as _e:
        # Table missing during very-first boot or transient DB blip — log only.
        pass

# ---------------------------------------------------------------------------
# Instance config (branding, persona, categories)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
INSTANCE_PATH = PROJECT_ROOT / "instance.yaml"

_instance = {}
if INSTANCE_PATH.exists():
    with open(INSTANCE_PATH) as f:
        _instance = yaml.safe_load(f) or {}

APP_NAME = _instance.get("app", {}).get("name", "Hire")
APP_TAGLINE = _instance.get("app", {}).get("tagline", "Talent Intelligence")
AGENT_NAME = _instance.get("agent", {}).get("name", "HR Brain")
AGENT_ROLE = _instance.get("agent", {}).get("role", "talent intelligence assistant")
AGENT_FOCUS = _instance.get("agent", {}).get("focus", "")
AGENT_PERSONALITY = _instance.get("agent", {}).get("personality", "professional, efficient")

CATEGORIES = _instance.get("categories", [])
SENIORITY_LEVELS = _instance.get("seniority_levels", [])
PIPELINE_STAGES = _instance.get("pipeline_stages", [])
TEMPLATE_CATEGORIES = _instance.get("template_categories", [])
EXAMPLE_QUESTIONS = _instance.get("example_questions", [])

# ---------------------------------------------------------------------------
# OpenRouter API
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# 3-Model Architecture
CHAT_MODEL = os.getenv("VISION_MODEL", "google/gemini-3-flash-preview")
DEEP_MODEL = os.getenv("DEEP_MODEL", "openai/gpt-5.4-mini")
LITE_MODEL = os.getenv("ROUTER_MODEL", "google/gemini-3.1-flash-lite-preview")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "google/gemini-2.0-flash-001")

# OpenAI-only Embedding Cascade — small is primary (3-4x faster, ~5x cheaper than large,
# minor recall loss acceptable for HR matching). Override via EMBEDDING_MODEL env.
EMBEDDING_MODELS = [
    os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small"),
    "openai/text-embedding-3-small",
    "openai/text-embedding-3-large",
]
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))

# ---------------------------------------------------------------------------
# Matching behavior
# ---------------------------------------------------------------------------
# When True, every newly uploaded CV is auto-matched against ALL active positions
# (Step 12 of the CV pipeline). When False (default), CV→position matching ONLY
# happens when a position is created/updated — saves significant LLM/embedding
# spend on bulk CV ingestion.
MATCH_ON_CV_UPLOAD = os.getenv("MATCH_ON_CV_UPLOAD", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
ADMIN_USER = os.getenv("ADMIN_USER", "")
ADMIN_PASS = os.getenv("ADMIN_PASS", "")

# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------
_openai_client = None

# Per-process cap on parallel LLM calls. Default 8 → with 4 uvicorn workers
# = 32 concurrent LLM calls cluster-wide (well under OpenRouter 60/min limit).
# Tune via LLM_MAX_CONCURRENT env. Used by both sync (_call_with_timeout)
# and any future async paths.
import threading as _threading
LLM_GATE = _threading.Semaphore(int(os.getenv("LLM_MAX_CONCURRENT", "8")))


def get_llm_client():
    """Get OpenAI-compatible client for OpenRouter."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
    return _openai_client


def is_ai_available() -> bool:
    """Check if AI features are available (API key configured)."""
    return bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY != "sk-or-v1-your-key-here")


def _do_chat_completion(client, model: str, prompt: str, temperature: float, max_tokens: int):
    # Hold gate for the duration of the OpenRouter network call so we cap
    # in-flight requests per worker. Released even on exception.
    with LLM_GATE:
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )


def _call_with_timeout(client, model: str, prompt: str, temperature: float, max_tokens: int):
    """Run sync OpenAI call with hard timeout via thread executor.

    Raises LLMTimeoutError on timeout. Inner exceptions propagate as-is.
    """
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_do_chat_completion, client, model, prompt, temperature, max_tokens)
        try:
            return fut.result(timeout=LLM_CALL_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            logger.error(f"[llm-timeout] model={model} exceeded {LLM_CALL_TIMEOUT_S}s")
            raise LLMTimeoutError(f"LLM call to {model} exceeded {LLM_CALL_TIMEOUT_S}s")


def llm_call(prompt: str, model: str = None, temperature: float = 0.3, max_tokens: int = 4000,
             tenant_id: str = "default") -> str | None:
    """Single LLM call with timeout + per-tenant daily cost cap + structured log.

    On timeout raises LLMTimeoutError. On cost cap exhaustion raises CostCapExceeded.
    Returns None for soft failures (API errors after fallback).
    """
    if not is_ai_available():
        logger.warning("LLM call skipped — OPENROUTER_API_KEY not set")
        return None

    from backend.core.cost_cap import check_and_record, CostCapExceeded  # noqa

    client = get_llm_client()
    model = model or CHAT_MODEL
    # Rough estimate: chars/4 for prompt + max_tokens budget
    est_tokens = max(1, len(prompt) // 4) + int(max_tokens or 0)

    # Cap check (sync wrapper around async helper)
    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Best-effort sync path: run in a fresh loop in another thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    ex.submit(asyncio.run, check_and_record(tenant_id, model, est_tokens)).result()
            else:
                loop.run_until_complete(check_and_record(tenant_id, model, est_tokens))
        except RuntimeError:
            asyncio.run(check_and_record(tenant_id, model, est_tokens))
    except CostCapExceeded:
        _log_llm_call(tenant=tenant_id, model=model, latency_ms=0,
                      in_tokens=est_tokens, out_tokens=0, cost_usd=0.0,
                      status="cap_exceeded")
        raise

    t0 = time.time()
    try:
        resp = _call_with_timeout(client, model, prompt, temperature, max_tokens)
        latency_ms = int((time.time() - t0) * 1000)
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", est_tokens) if usage else est_tokens
        out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
        from backend.core.cost_cap import estimate_cost
        cost = estimate_cost(model, in_tok + out_tok)
        _log_llm_call(tenant=tenant_id, model=model, latency_ms=latency_ms,
                      in_tokens=in_tok, out_tokens=out_tok, cost_usd=cost,
                      status="ok")
        return resp.choices[0].message.content
    except LLMTimeoutError:
        _log_llm_call(tenant=tenant_id, model=model,
                      latency_ms=int((time.time()-t0)*1000),
                      in_tokens=est_tokens, out_tokens=0, cost_usd=0.0,
                      status="timeout")
        raise
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        _log_llm_call(tenant=tenant_id, model=model, latency_ms=latency_ms,
                      in_tokens=est_tokens, out_tokens=0, cost_usd=0.0,
                      status=f"error:{type(e).__name__}")
        logger.warning(f"LLM call failed ({model}): {e}, trying fallback")
        t1 = time.time()
        try:
            resp = _call_with_timeout(client, FALLBACK_MODEL, prompt, temperature, max_tokens)
            latency_ms = int((time.time() - t1) * 1000)
            usage = getattr(resp, "usage", None)
            in_tok = getattr(usage, "prompt_tokens", est_tokens) if usage else est_tokens
            out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
            from backend.core.cost_cap import estimate_cost
            cost = estimate_cost(FALLBACK_MODEL, in_tok + out_tok)
            _log_llm_call(tenant=tenant_id, model=FALLBACK_MODEL, latency_ms=latency_ms,
                          in_tokens=in_tok, out_tokens=out_tok, cost_usd=cost,
                          status="ok_fallback")
            return resp.choices[0].message.content
        except LLMTimeoutError:
            _log_llm_call(tenant=tenant_id, model=FALLBACK_MODEL,
                          latency_ms=int((time.time()-t1)*1000),
                          in_tokens=est_tokens, out_tokens=0, cost_usd=0.0,
                          status="timeout_fallback")
            raise
        except Exception as e2:
            _log_llm_call(tenant=tenant_id, model=FALLBACK_MODEL,
                          latency_ms=int((time.time()-t1)*1000),
                          in_tokens=est_tokens, out_tokens=0, cost_usd=0.0,
                          status=f"error_fallback:{type(e2).__name__}")
            logger.error(f"Fallback LLM also failed: {e2}")
            return None


# ---------------------------------------------------------------------------
# Model-ID audit (Task 4)
# ---------------------------------------------------------------------------
# TODO(audit): Verifier model id "anthropic/claude-opus-4.7" uses dotted minor
# version which is likely wrong — Anthropic IDs are dash-separated and typically
# include a date suffix (e.g. claude-opus-4-5-20250929). Confirm correct ID with
# Anthropic / OpenRouter docs before relying on this in production.
_SUSPECT_MODEL_RE = re.compile(r"claude-opus-4\.\d")


def audit_model_ids() -> list[str]:
    """Log a warning for any configured model id matching the suspect dotted format.

    Returns the list of suspect ids found (for tests/visibility).
    """
    candidates = {
        "VISION_VERIFIER_MODEL": os.getenv("VISION_VERIFIER_MODEL", "anthropic/claude-opus-4.7"),
        "CHAT_MODEL": CHAT_MODEL,
        "DEEP_MODEL": DEEP_MODEL,
        "LITE_MODEL": LITE_MODEL,
        "FALLBACK_MODEL": FALLBACK_MODEL,
    }
    suspects: list[str] = []
    for key, val in candidates.items():
        if val and _SUSPECT_MODEL_RE.search(val):
            logger.warning(
                f"[model-audit] {key}={val!r} uses dotted minor format "
                "(claude-opus-4.X) — likely wrong. Anthropic IDs use dashes and "
                "typically include a date suffix. See TODO(audit) in config.py."
            )
            suspects.append(val)
    return suspects


def _embed_text_sync(text: str) -> list[float] | None:
    client = get_llm_client()
    for model in EMBEDDING_MODELS:
        try:
            resp = client.embeddings.create(
                model=model,
                input=text,
                dimensions=EMBEDDING_DIMENSIONS,
                encoding_format="float",
            )
            return resp.data[0].embedding
        except Exception as e:
            logger.warning(f"Embedding failed ({model}): {e}")
            continue
    logger.error("All embedding models failed")
    return None


async def embed_text(text: str) -> list[float] | None:
    """Async-wrapped embedding (runs sync OpenAI call in thread pool so asyncio.gather actually parallelizes)."""
    import asyncio as _aio
    return await _aio.to_thread(_embed_text_sync, text)

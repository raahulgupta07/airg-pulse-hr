"""Health — basic + full component checks."""
from __future__ import annotations

import os
import time
import shutil
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_start_time = time.time()


def _version() -> str:
    v = os.getenv("APP_VERSION")
    if v:
        return v
    for sha_file in ("/app/GIT_SHA", "/app/.git_sha", "GIT_SHA"):
        try:
            if Path(sha_file).is_file():
                return Path(sha_file).read_text().strip()
        except Exception:
            pass
    return "1.0.0"


@router.get("/")
async def health_basic():
    return {"status": "ok"}


@router.get("/full")
async def health_full():
    checks = {}

    db_check = {"ok": False}
    t0 = time.perf_counter()
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        db_check = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as e:
        db_check = {"ok": False, "error": str(e)[:200]}
    checks["db"] = db_check

    openai_check = {"ok": False}
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        openai_check = {"ok": False, "status": "not_configured"}
    else:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, timeout=3.0)
            client.models.list()
            openai_check = {"ok": True}
        except Exception as e:
            openai_check = {"ok": False, "error": str(e)[:200]}
    checks["openai"] = openai_check

    embed_check = {"ok": False}
    try:
        if not api_key:
            embed_check = {"ok": False, "status": "not_configured"}
        else:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, timeout=3.0)
            model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            client.embeddings.create(model=model, input="ping")
            embed_check = {"ok": True}
    except Exception as e:
        embed_check = {"ok": False, "error": str(e)[:200]}
    checks["embeddings"] = embed_check

    try:
        usage = shutil.disk_usage("/")
        free_gb = round(usage.free / (1024 ** 3), 1)
        checks["disk"] = {"ok": free_gb > 1.0, "free_gb": free_gb}
    except Exception as e:
        checks["disk"] = {"ok": False, "error": str(e)[:200]}

    critical_ok = checks["db"]["ok"] and checks["disk"]["ok"]
    any_degraded = not all(c.get("ok") for c in checks.values())
    if not critical_ok:
        status = "down"
    elif any_degraded:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "checks": checks,
        "version": _version(),
        "uptime_s": round(time.time() - _start_time),
    }

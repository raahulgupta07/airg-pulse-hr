"""
PULSE — Org Heartbeat (People · Updates · Lifecycle · Sourcing · Engagement)
AI-powered hiring + internal comms + broadcast/ads platform.
FastAPI + Frontend (single port)
"""
from __future__ import annotations

import os
import logging
import time
import hashlib
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import json as json_mod

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, 'request_id'):
            log["request_id"] = record.request_id
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json_mod.dumps(log)

log_format = os.getenv("LOG_FORMAT", "text")  # "text" or "json"
if log_format == "json":
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
else:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
FRONTEND_DIR = Path("/app/static-frontend")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PULSE API",
    description="PULSE — Org Heartbeat. Hiring, internal comms, job posting, broadcast/ads, candidate matching, HR Brain chatbot. People · Updates · Lifecycle · Sourcing · Engagement.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    # Disable trailing-slash auto-redirect — breaks SSE EventSource (no follow on 307)
    # and confuses fetch() callers that expect explicit URLs.
    redirect_slashes=False,
)

# ---------------------------------------------------------------------------
# Rate Limiting (slowapi)
#   - Global default: 60/min per IP (applied via SlowAPIMiddleware default_limits)
#   - Stricter limits applied per-route via @limiter.limit decorators on the
#     handlers themselves (POST /candidates/upload, /chat, ai-summary, report.docx)
# ---------------------------------------------------------------------------
from backend.core.rate_limit import limiter
app.state.limiter = limiter
from fastapi.responses import JSONResponse as _RLJSONResponse
app.add_exception_handler(
    RateLimitExceeded,
    lambda req, exc: _RLJSONResponse(status_code=429, content={"error": "rate_limited", "detail": str(exc.detail)}),
)
app.add_middleware(SlowAPIMiddleware)

# ---------------------------------------------------------------------------
# CORS — env-driven allowlist (no wildcard in production)
# ---------------------------------------------------------------------------
_default_origins = "http://localhost:5173,http://localhost:8090"
origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]
logger.info(f"CORS allowed origins: {origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# CSRF Protection (Origin-based)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    # Skip for safe methods and public endpoints
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if request.url.path.startswith("/api/careers/"):  # public apply endpoint
        return await call_next(request)
    # For state-changing requests, verify Origin header matches allowed origins
    origin = request.headers.get("origin", "")
    allowed = origins
    if origin and origin not in allowed and "*" not in allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=403, content={"detail": "CSRF: Origin not allowed"})
    return await call_next(request)


# ---------------------------------------------------------------------------
# Request ID Tracking
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/assets/") or request.url.path.endswith((".webp", ".png", ".jpg")):
        response.headers["Cache-Control"] = "public, max-age=86400"  # 24 hours
    return response


# ---------------------------------------------------------------------------
# WebSocket Notifications
# ---------------------------------------------------------------------------
_ws_connections: dict[int, list[WebSocket]] = {}  # user_id -> [websockets]


@app.websocket("/ws/notifications/{user_id}")
async def ws_notifications(websocket: WebSocket, user_id: int):
    await websocket.accept()
    if user_id not in _ws_connections:
        _ws_connections[user_id] = []
    _ws_connections[user_id].append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        _ws_connections[user_id].remove(websocket)
        if not _ws_connections[user_id]:
            del _ws_connections[user_id]


async def push_notification(user_id: int, data: dict):
    """Push notification to connected WebSocket clients."""
    if user_id in _ws_connections:
        import json
        msg = json.dumps(data)
        dead = []
        for ws in _ws_connections[user_id]:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_connections[user_id].remove(ws)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
_server_start_time = time.time()


async def _sweep_stale_ai_scans():
    """Mark queued/running scans older than 10 min as error.
    Called once at startup. Prevents dedupe deadlock when api crashes mid-scan.
    """
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("""
                UPDATE position_ai_scans
                SET status='error',
                    error='stale_on_restart',
                    finished_at=NOW()
                WHERE status IN ('queued','running')
                  AND COALESCE(started_at, created_at) < NOW() - INTERVAL '10 minutes'
                RETURNING id
            """)
            ids = [r[0] for r in cur.fetchall()]
            if ids:
                logger.warning(f"[ai-scan] swept {len(ids)} stale scans on startup: {ids}")
    except Exception as e:
        logger.error(f"[ai-scan] sweeper failed: {e}")


async def _stale_sweeper_loop():
    """Periodic background loop — sweep stale ai-scans every 5 minutes."""
    import asyncio as _asyncio
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from backend.agents.registry import heartbeat as _hb, cycle_done as _cd
    while True:
        try:
            _hb("sweeper", status="idle", next_run_at=_dt.now(_tz.utc) + _td(seconds=300))
            await _asyncio.sleep(300)
            _hb("sweeper", status="running", action="scanning ai-scan rows")
            await _sweep_stale_ai_scans()
            _cd("sweeper", events=1)
        except _asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[agent:sweeper] iteration failed: {e}")
            _cd("sweeper", error=str(e))


@app.on_event("startup")
async def startup():
    """Initialize database tables and seed data."""
    # AWS SSM Parameter Store hydration — must run BEFORE any module that
    # captures env-vars at import time (db pool, JWT, etc.). Env LOAD_SSM=1
    # opts in; failures are silent so local dev keeps working.
    if os.getenv("LOAD_SSM") == "1":
        try:
            from backend.core.aws_secrets import load_secrets_from_ssm
            load_secrets_from_ssm(os.getenv("SSM_PREFIX", "/pulse/prod/"))
        except Exception as e:
            logger.warning(f"SSM hydration failed: {e}")

    # Verify storage adapter wires (no behaviour change yet — upload routes
    # still write directly; this just surfaces config errors at boot).
    try:
        from backend.core.storage import get_storage
        get_storage()
    except Exception as e:
        logger.warning(f"storage adapter init failed: {e}")

    try:
        from backend.core.database import ensure_schema
        ensure_schema()
        logger.info("PULSE started with database connection")
        try:
            from backend.core.migrations import run_migrations
            run_migrations()
        except Exception as e:
            logger.warning(f"Migrations failed: {e}")
        # Bootstrap superadmin from env (SUPERADMIN_ID + SUPERADMIN_PASS_HASH/PASS)
        try:
            from backend.routes.auth import bootstrap_superadmin
            bootstrap_superadmin()
        except Exception as e:
            logger.warning(f"bootstrap_superadmin failed: {e}")
        # Seed default settings (idempotent — preserves user-edited values
        # across container redeploys via ON CONFLICT DO NOTHING).
        try:
            from backend.core.settings import seed_defaults
            seed_defaults()
        except Exception as e:
            logger.warning(f"settings seed_defaults failed: {e}")
    except Exception as e:
        logger.warning(f"Database not available: {e}. Running in API-only mode.")
        logger.warning("Start PostgreSQL or use docker compose for full functionality.")
    # Launch Match Agent (CV ↔ JD sync)
    try:
        import asyncio
        from backend.agents.sync import worker_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(worker_loop())
        _hb("match", status="idle")
        logger.info("[agent:match] launched")
    except Exception as e:
        logger.warning(f"agent:match start failed: {e}")

    # Sweep stale ai-scans (queued/running > 10min) — prevents dedupe deadlock after crash
    await _sweep_stale_ai_scans()

    # Launch Sweeper Agent (every 5 min)
    try:
        asyncio.create_task(_stale_sweeper_loop())
        logger.info("[agent:sweeper] launched (5min interval)")
    except Exception as e:
        logger.warning(f"agent:sweeper start failed: {e}")

    # Launch JD Field Agent (poll fallback, 60s)
    try:
        import asyncio
        from backend.agents.jd_background import jd_background_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(jd_background_loop())
        _hb("jd-field-poll", status="idle")
        logger.info("[agent:jd-field-poll] launched (60s interval)")
    except Exception as e:
        logger.warning(f"agent:jd-field-poll start failed: {e}")

    # Launch JD Field Agent (realtime LISTEN/NOTIFY — primary path)
    try:
        from backend.agents.jd_enrich_listener import jd_enrich_listener_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(jd_enrich_listener_loop())
        _hb("jd-field-realtime", status="idle")
        logger.info("[agent:jd-field-realtime] launched (LISTEN/NOTIFY)")
    except Exception as e:
        logger.warning(f"agent:jd-field-realtime start failed: {e}")

    # Launch Brain agents (Brain Trainer / Doc Ingestor / Q&A Suggester / FAQ Builder)
    try:
        from backend.agents.brain_trainer import brain_trainer_loop
        from backend.agents.doc_ingestor import doc_ingestor_loop
        from backend.agents.qa_suggester import qa_suggester_loop
        from backend.agents.faq_builder import faq_builder_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(brain_trainer_loop()); _hb("brain-trainer", status="idle")
        asyncio.create_task(doc_ingestor_loop());  _hb("doc-ingestor", status="idle")
        asyncio.create_task(qa_suggester_loop());  _hb("qa-suggester", status="idle")
        asyncio.create_task(faq_builder_loop());   _hb("faq-builder", status="idle")
        logger.info("[agent:brain-trainer/doc-ingestor/qa-suggester/faq-builder] launched")
    except Exception as e:
        logger.warning(f"agent:brain group start failed: {e}")

    # Launch JD Bias Detector (30 min)
    try:
        from backend.agents.jd_bias_detector import jd_bias_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(jd_bias_loop())
        _hb("jd-bias", status="idle")
        logger.info("[agent:jd-bias] launched (1800s interval)")
    except Exception as e:
        logger.warning(f"agent:jd-bias start failed: {e}")

    # Launch JD Refresh Agent (6h)
    try:
        from backend.agents.jd_refresher import jd_refresh_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(jd_refresh_loop())
        _hb("jd-refresh", status="idle")
        logger.info("[agent:jd-refresh] launched (6h interval)")
    except Exception as e:
        logger.warning(f"agent:jd-refresh start failed: {e}")

    # Launch JD Translator (30 min)
    try:
        from backend.agents.jd_translator import jd_translator_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(jd_translator_loop())
        _hb("jd-translator", status="idle")
        logger.info("[agent:jd-translator] launched (1800s interval)")
    except Exception as e:
        logger.warning(f"agent:jd-translator start failed: {e}")

    # Launch JD Completeness Scorer (24h nightly)
    try:
        from backend.agents.jd_completeness import jd_completeness_loop
        from backend.agents.registry import heartbeat as _hb
        asyncio.create_task(jd_completeness_loop())
        _hb("jd-completeness", status="idle")
        logger.info("[agent:jd-completeness] launched (24h interval)")
    except Exception as e:
        logger.warning(f"agent:jd-completeness start failed: {e}")

    # Audit configured LLM model IDs (warn on suspect dotted-minor formats)
    try:
        from backend.core.config import audit_model_ids
        audit_model_ids()
    except Exception as e:
        logger.warning(f"model-id audit failed: {e}")

    # CV storage writability probe
    cvs_path = Path("/data/cvs")
    cvs_writable = False
    try:
        cvs_path.mkdir(parents=True, exist_ok=True)
        probe = cvs_path / ".write_test"
        probe.touch()
        probe.unlink()
        cvs_writable = True
    except Exception as e:
        logger.warning(f"[startup] /data/cvs write probe failed: {e}")
    app.state.cvs_path = str(cvs_path)
    app.state.cvs_writable = cvs_writable
    if cvs_writable:
        logger.info(f"[startup] CV storage path={cvs_path} writable=True")
    else:
        logger.warning(
            f"[startup] CV storage path={cvs_path} writable=False — "
            "uploads will fail until the volume is mounted r/w"
        )

    logger.info("PULSE started successfully")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
from backend.routes.auth import router as auth_router
from backend.routes.candidates import router as candidates_router
from backend.routes.positions import router as positions_router
from backend.routes.matching import router as matching_router
from backend.routes.chat import router as chat_router
from backend.routes.jd_repo import router as jd_repo_router
from backend.routes.candidate_extras import router as candidate_extras_router
from backend.routes.screening import router as screening_router
from backend.routes.emails import router as emails_router
from backend.routes.analytics import router as analytics_router
from backend.routes.bulk import router as bulk_router
from backend.routes.careers import router as careers_router
from backend.routes.notifications import router as notifications_router
from backend.routes.offers import router as offers_router
from backend.routes.eeo import router as eeo_router
from backend.routes.duplicates import router as duplicates_router
from backend.routes.export import router as export_router
from backend.routes.saved_searches import router as saved_searches_router
from backend.routes.automations import router as automations_router
from backend.routes.communicate import router as communicate_router
from backend.routes.board import router as board_router
from backend.routes.agents import router as agents_router
from backend.routes.evaluation import router as evaluation_router
from backend.routes.admin import router as admin_router, public_router as admin_public_router
from backend.routes.ingest import router as ingest_router
from backend.routes.merges import router as merges_router
from backend.routes.pipeline_trace import router as pipeline_trace_router
from backend.routes.settings import router as settings_router
from backend.routes.billing import router as billing_router
from backend.routes.email import router as email_router
from backend.routes.health import router as health_router

app.include_router(health_router, prefix="/api/health", tags=["health"])
app.include_router(billing_router)  # has its own /api/billing prefix
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
from backend.routes.auth import users_router as _users_router
app.include_router(_users_router, prefix="/api/users", tags=["users"])
from backend.routes.gdpr import router as _gdpr_router
app.include_router(_gdpr_router, prefix="/api/users", tags=["users-gdpr"])
app.include_router(candidates_router, prefix="/api/candidates", tags=["candidates"])
app.include_router(candidate_extras_router, prefix="/api/candidates", tags=["candidate-extras"])
app.include_router(positions_router, prefix="/api/positions", tags=["positions"])
app.include_router(matching_router, prefix="/api/matching", tags=["matching"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(jd_repo_router, prefix="/api/jds", tags=["jd-repository"])
from backend.agents.jd_background import router as jd_bg_router
app.include_router(jd_bg_router, prefix="/api/jd-background", tags=["jd-background"])
app.include_router(screening_router, prefix="/api", tags=["screening"])
app.include_router(emails_router, prefix="/api/emails", tags=["emails"])
app.include_router(email_router, prefix="/api/email", tags=["email"])
app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])
from backend.routes.analytics_v2 import router as analytics_v2_router
app.include_router(analytics_v2_router, prefix="/api/analytics/v2", tags=["analytics-v2"])
app.include_router(bulk_router, prefix="/api/bulk", tags=["bulk"])
app.include_router(careers_router, prefix="/api/careers", tags=["careers"])
app.include_router(notifications_router, prefix="/api/notifications", tags=["notifications"])
from backend.routes.feed import router as feed_router
app.include_router(feed_router, prefix="/api", tags=["feed"])
app.include_router(offers_router, prefix="/api/offers", tags=["offers"])
app.include_router(eeo_router, prefix="/api/eeo", tags=["eeo"])
app.include_router(duplicates_router, prefix="/api/duplicates", tags=["duplicates"])
app.include_router(export_router, prefix="/api/export", tags=["export"])
app.include_router(saved_searches_router, prefix="/api/saved-searches", tags=["saved-searches"])
app.include_router(automations_router, prefix="/api/automations", tags=["automations"])
app.include_router(communicate_router, prefix="/api/communicate", tags=["communicate"])
app.include_router(board_router, prefix="/api/board", tags=["board"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(evaluation_router, prefix="/api/evaluation", tags=["evaluation"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(admin_public_router, prefix="/api/system", tags=["system"])
app.include_router(ingest_router, prefix="/api/ingest", tags=["ingest"])
app.include_router(merges_router, prefix="/api/merges", tags=["merges"])
app.include_router(pipeline_trace_router, prefix="/api", tags=["pipeline-trace"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
from backend.routes.competencies import router as competencies_router
app.include_router(competencies_router, prefix="/api/competencies", tags=["competencies"])
from backend.routes.facets import router as facets_router
app.include_router(facets_router, prefix="/api/facets", tags=["facets"])
from backend.routes.interview_kit import router as interview_kit_router
app.include_router(interview_kit_router, prefix="/api", tags=["interview-kit"])
from backend.routes.templates import email_router as templates_email_router, offer_router as templates_offer_router
app.include_router(templates_email_router, prefix="/api/email-templates", tags=["email-templates"])
app.include_router(templates_offer_router, prefix="/api/offer-templates", tags=["offer-templates"])

# Brain / Q&A / FAQ (mig 058 + brain agent group)
from backend.routes.brain import (
    admin_router as brain_admin_router,
    qa_router as brain_qa_router,
    faq_router as brain_faq_router,
)
app.include_router(brain_admin_router, prefix="/api/admin/brain", tags=["brain-admin"])
app.include_router(brain_qa_router, prefix="/api/qa", tags=["qa-suggester"])
app.include_router(brain_faq_router, prefix="/api/faq", tags=["faq"])

# API v1 aliases (forward compatibility)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["v1-auth"])
app.include_router(candidates_router, prefix="/api/v1/candidates", tags=["v1-candidates"])
app.include_router(positions_router, prefix="/api/v1/positions", tags=["v1-positions"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    from backend.core.job_queue import get_job_status
    job = get_job_status(job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/health")
@limiter.exempt
async def health(request: Request):
    # ALB fast-path: skip expensive checks (LLM probes, OCR, migrations,
    # disk write) — just verify DB ping. Used by ECS/ALB target group.
    if request.headers.get("X-ALB-Probe"):
        try:
            from backend.core.database import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return {"status": "ok"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "fail"})

    from backend.core.config import is_ai_available
    try:
        from backend.core.database import get_pool
        pool = get_pool()
        pool_stats = {"min": pool.min_size, "max": pool.max_size}
    except Exception:
        pool_stats = None

    # DB ping (SELECT 1)
    db_status = "fail"
    try:
        from backend.core.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            db_status = "ok"
    except Exception as e:
        logger.debug(f"[health] db ping failed: {e}")

    # LLM models (configured only — no live call)
    try:
        from backend.core.config import (
            CHAT_MODEL, LITE_MODEL, EMBEDDING_MODELS,
        )
        try:
            from backend.core.config import DEEP_MODEL
        except Exception:
            DEEP_MODEL = None
        llm_info = {
            "configured": is_ai_available(),
            "chat": CHAT_MODEL,
            "lite": LITE_MODEL,
            "deep": DEEP_MODEL,
            "verifier": os.getenv("VISION_VERIFIER_MODEL"),
            "embeddings": list(EMBEDDING_MODELS) if EMBEDDING_MODELS else [],
        }
    except Exception as e:
        llm_info = {"configured": is_ai_available(), "error": str(e)}

    # Disk writability for /data/cvs
    cvs_path = Path("/data/cvs")
    disk_writable = False
    try:
        probe = cvs_path / ".write_test"
        cvs_path.mkdir(parents=True, exist_ok=True)
        probe.touch()
        probe.unlink()
        disk_writable = True
    except Exception:
        pass
    disk_info = {"path": str(cvs_path), "writable": disk_writable}

    # Version: APP_VERSION env, fallback to git sha file, fallback to static
    version = os.getenv("APP_VERSION")
    if not version:
        for sha_file in ("/app/GIT_SHA", "/app/.git_sha", "GIT_SHA"):
            try:
                if Path(sha_file).is_file():
                    version = Path(sha_file).read_text().strip()
                    break
            except Exception:
                pass
    if not version:
        version = "1.0.0"

    # Migrations health (pending => 503; drift alone => ok with list)
    try:
        from backend.core.migrations import migration_status
        mig = migration_status()
    except Exception as e:
        logger.debug(f"[health] migration_status failed: {e}")
        mig = {"applied": 0, "files": 0, "pending": [], "drift": [], "last_applied": None, "error": str(e)}

    overall = "ok" if (db_status == "ok" and disk_writable) else "degraded"
    if mig.get("pending"):
        overall = "degraded"

    # Redis status (True | False | "unavailable")
    try:
        from backend.core.cache import redis_status
        redis_state = redis_status()
    except Exception as e:
        logger.debug(f"[health] redis_status failed: {e}")
        redis_state = "unavailable"

    body = {
        "status": overall,
        "app": "pulse",
        "version": version,
        "uptime_s": round(time.time() - _server_start_time),
        "db": db_status,
        "llm": llm_info,
        "disk": disk_info,
        "ai_available": is_ai_available(),
        "db_pool": pool_stats,
        "migrations": mig,
        "redis": redis_state,
    }
    if mig.get("pending"):
        return JSONResponse(status_code=503, content=body)
    return body


@app.get("/api/health/ocr")
async def ocr_health():
    result = {"tesseract": False, "paddleocr": False, "vision_llm": False}
    # Check Tesseract
    try:
        import subprocess
        r = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5)
        result["tesseract"] = r.returncode == 0
    except Exception:
        pass
    # Check PaddleOCR
    try:
        from backend.core.cv_parser import _get_paddle_ocr
        result["paddleocr"] = _get_paddle_ocr() is not None
    except Exception:
        pass
    # Check Vision LLM
    from backend.core.config import is_ai_available
    result["vision_llm"] = is_ai_available()

    result["status"] = "healthy" if any(v for k, v in result.items() if k != "status") else "degraded"
    return result


@app.get("/api/ai-status")
async def ai_status():
    """Check if AI features are available."""
    from backend.core.config import is_ai_available, OPENROUTER_API_KEY
    available = is_ai_available()
    return {
        "available": available,
        "message": "AI features active" if available else "OPENROUTER_API_KEY not set — AI features disabled",
        "key_set": bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY != "sk-or-v1-your-key-here"),
    }


# ---------------------------------------------------------------------------
# Serve Frontend (SPA fallback)
# ---------------------------------------------------------------------------
if FRONTEND_DIR.exists():
    _assets_dir = FRONTEND_DIR / "_app"
    if _assets_dir.exists():
        app.mount("/_app", StaticFiles(directory=_assets_dir), name="assets")

    from fastapi import Request, HTTPException
    from fastapi.responses import RedirectResponse

    # Lazy cache of registered route paths for slash-variant fallback.
    _api_path_cache: dict[str, set[str]] = {"paths": set()}

    @app.get("/{path:path}")
    async def serve_frontend(path: str, request: Request):
        # For /api/* paths:
        #  - If `/api/X/` exists as a real route but client asked for `/api/X` (no slash),
        #    307 to the slash variant. Handles legacy callers that omit the slash
        #    on routers defined with `@router.get("/")`.
        #  - Otherwise return 404 (no SPA fallback for /api/).
        if path == "api" or path.startswith("api/"):
            if not _api_path_cache["paths"]:
                _api_path_cache["paths"] = {getattr(r, "path", "") for r in app.routes if getattr(r, "path", None)}
            full = "/" + path
            slashed = full + "/"
            paths = _api_path_cache["paths"]
            if slashed in paths and full not in paths:
                qs = request.url.query
                return RedirectResponse(slashed + (f"?{qs}" if qs else ""), status_code=307)
            raise HTTPException(status_code=404, detail="Not found")
        file_path = FRONTEND_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        return {"message": "PULSE API running. Frontend not built yet — run: cd frontend && npm run build"}

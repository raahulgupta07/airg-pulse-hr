# ARCHITECTURE.md — One-page system map

Read **AGENTS.md** first. This file = data flows + topology, no prose.

---

## Runtime topology (Docker Compose)

```
┌─────────────────────────────────────────────────────────────────┐
│  USER (browser)                                                 │
│      │                                                          │
│      ▼ HTTPS (TLS terminated upstream by Caddy / ALB)           │
│  ┌──────────────────────────────────────────────┐               │
│  │  pulse-api  (uvicorn × 4 workers)            │  8GB / 4 CPU  │
│  │  ┌────────────────────────────────────────┐  │               │
│  │  │ middleware:                            │  │               │
│  │  │   request-id, CORS, CSRF (origin),     │  │               │
│  │  │   rate-limit (slowapi 600/min),        │  │               │
│  │  │   auth (JWT first, hex fallback)       │  │               │
│  │  └────────────────────────────────────────┘  │               │
│  │  ┌────────────────────────────────────────┐  │               │
│  │  │ FastAPI routers (22 modules)           │  │               │
│  │  │  auth · candidates · positions ·       │  │               │
│  │  │  matching · evaluation · chat ·        │  │               │
│  │  │  jd_repo · interviews · screening ·    │  │               │
│  │  │  offers · emails · analytics ·         │  │               │
│  │  │  notifications · bulk · careers ·      │  │               │
│  │  │  pools · duplicates · saved_searches · │  │               │
│  │  │  export · eeo · automations · settings │  │               │
│  │  │  billing (admin: LLM cost ledger)      │  │               │
│  │  └────────────────────────────────────────┘  │               │
│  │  ┌────────────────────────────────────────┐  │               │
│  │  │ core/                                  │  │               │
│  │  │  config (LLM_GATE Sem(8))              │  │               │
│  │  │  database (pool 5..20)                 │  │               │
│  │  │  cv_parser (OCR_GATE Sem(2))           │  │               │
│  │  │  cv_pipeline (13-step)                 │  │               │
│  │  │  storage (Local/S3 adapter)            │  │               │
│  │  │  settings (30s TTL cache)              │  │               │
│  │  │  migrations (sha256 + advisory lock)   │  │               │
│  │  │  cost_cap (per-tenant daily $)         │  │               │
│  │  │  rate_limit (slowapi)                  │  │               │
│  │  │  cache + embed_cache + tool_cache      │  │               │
│  │  │  (Redis adapter, in-mem fallback)      │  │               │
│  │  └────────────────────────────────────────┘  │               │
│  │  ┌────────────────────────────────────────┐  │               │
│  │  │ agents/  (Chat v2 — flag-gated)        │  │               │
│  │  │  hr_agent.arun() async generator       │  │               │
│  │  │  session ($ cap → agent_runs)          │  │               │
│  │  │  memory (pgvector recall + write)      │  │               │
│  │  │  providers/{candidate,position,brain,  │  │               │
│  │  │            analytics,email}            │  │               │
│  │  │  eval/ (golden 30 + run_eval)          │  │               │
│  │  └────────────────────────────────────────┘  │               │
│  │  static-frontend/  ← SvelteKit prebuilt      │               │
│  └────┬─────────┬──────────────┬─────────┬────┘                 │
│       ▼         ▼              ▼         ▼                      │
│  ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐         │
│  │ pulse-db │ │ /data   │ │ pulse-   │ │ OpenRouter   │         │
│  │ PG 18    │ │  cvs/   │ │ redis    │ │  Gemini-3    │         │
│  │ pgvector │ │  backups│ │ (embed   │ │  GPT-5.4-mini│         │
│  │ pulsedb  │ │         │ │  24h /   │ │  Claude-Opus │         │
│  │ 100 conn │ │         │ │  tool    │ │  Cohere      │         │
│  │ 512MB sb │ │         │ │  60s)    │ └──────────────┘         │
│  └──────────┘ └─────────┘ └──────────┘                          │
│        ▲                                                        │
│  ┌──────────────┐                                               │
│  │ pulse-backup │  pg_dump every 24h, gzip, 14d retention       │
│  │ (postgres:18)│  → /data/backups/pulse_<TS>.dump.gz           │
│  │              │  → symlink latest.dump.gz                     │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## ECS Fargate topology (production)

```
┌─────────────────────────────────────────────────────────────────┐
│  Internet                                                       │
│     │                                                           │
│     ▼ HTTPS                                                     │
│  ┌──────────┐                                                   │
│  │  ALB     │  ACM cert · X-ALB-Probe fast-path                 │
│  │ (public) │                                                   │
│  └────┬─────┘                                                   │
│       │ target group (HTTP 8000)                                │
│       ▼                                                         │
│  ┌─────────────────────────────────────┐                        │
│  │  ECS Service (Fargate, N tasks)     │  scale 1..N            │
│  │   task-def: pulse:vN                │                        │
│  │   image: ECR <acct>.dkr.ecr...:vN   │                        │
│  │   secrets: from Secrets Manager     │                        │
│  │   env:    from SSM Parameter Store  │                        │
│  │   /data: EFS mount                  │                        │
│  └────┬────────────────────┬───────────┘                        │
│       ▼                    ▼                                    │
│  ┌──────────┐          ┌──────────┐                             │
│  │ Aurora   │          │ EFS      │  /data/cvs                  │
│  │ Serverless│         │ access   │                             │
│  │ v2 (PG)  │          │ point    │                             │
│  │ 0.5–2 ACU│          │ uid 1000 │                             │
│  │ pgvector │          └──────────┘                             │
│  └──────────┘                                                   │
│       ▲                                                         │
│  ┌────────────┐  daily snapshot, point-in-time restore          │
│  │ AWS Backup │                                                 │
│  └────────────┘                                                 │
│                                                                 │
│  Logs: stdout → CloudWatch Logs (30d retention)                 │
│  Metrics: CloudWatch + container insights                       │
│  Deploy: GitHub Actions OIDC → push ECR → update service        │
│  Rollback: aws ecs update-service --task-definition <prev>      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data flows

### Login

```
POST /api/auth/login {operator_id, access_key}
  → bcrypt verify (cost 12)
  → check failed_login_count, locked_until → 429 if locked
  → JWT HS256 (8h exp) signed with JWT_SECRET
  → response: {token, expires_at}
  → frontend setToken() → localStorage hire_token + hire_token_exp
  → goto('/')
```

### CV upload

```
POST /api/ingest/?auto_process=false (multipart, 20MB cap, MIME whitelist)
  → save → /data/cvs/<uuid>.<ext>
  → INSERT candidates (is_processed=false)
  → return 202 + candidate_id
  → frontend Pending Files Table renders row with ▶ RUN

User clicks ▶ RUN → POST /api/candidates/{id}/process
  → spawn background task
  → 13-step pipeline runs (see below)
  → events streamed to pipeline_trace table
  → frontend PipelineCli polls /candidates/pending?include_recent=true every 1.5s
  → ring buffer 500, dedup by run_id|step|status
```

### 13-step pipeline (per CV)

```
0. ENHANCE         → enhance_image_for_ocr (LANCZOS upscale + sharpen + contrast)
                     applied per-image before any OCR pass; skipped if already crisp
1. CLASSIFY        → cv_parser.classify_file (pdf/docx/image)
2. EXTRACT         → PyMuPDF / python-docx / OCR (PaddleOCR + Vision LLM)
2.5. VERIFY        → Claude Opus 4.7 (5 critical fields, handwritten only)
3. SCREENSHOTS     → 300 DPI WebP per page
4. STRUCTURE       → LLM extract → JSON {name, email, exp, edu, skills, ...}
5. ENRICH          → LLM (LITE) infer seniority, role family, location
6. SAVE            → UPDATE candidates SET ...
7. KNOWLEDGE       → extract Q&A pairs for chat
8. HyPE_EMBED      → hypothetical-question embeddings (Gemini-2)
9. CONTEXT_EMBED   → chunk embeddings
10. QUALITY        → score 0-100, list issues
11. TAG            → auto-tags (Backend, Senior, FAANG, etc.)
12. AUTO_MATCH     → score against ALL open positions, flag top matches
13. AI_SUMMARY     → executive brief (isolated; failure ≠ upload failure)
```

Each step writes to `pipeline_trace`: `{run_id, step_order, model, status, latency_ms, cost_usd, in/out_tokens}`. Pruned to 50 rows per candidate.

### CV-JD matching

```
JD save → backend/routes/positions.py
  → extract competencies (KF4D)
  → generate scoring rubric per dimension
  → backend/routes/matching.py auto-scan
  → for each candidate in repo:
      score 7 dims (skills, exp, industry, edu, certs, culture, competencies)
      weighted composite with weight inheritance: tenant→sector→JD→position
  → flag top N matches → notification
```

### Position AI Scan Lifecycle

Trigger model (2026-05-12): scan runs ONLY on position create / JD update / manual rescan.
Per-CV scanning is gated behind `MATCH_ON_CV_UPLOAD=false` (default off).

```
User → POST /api/positions/         → positions.py create handler
positions.py → INSERT position row
positions.py → _create_ai_scan_row  → INSERT position_ai_scans (status=queued)
                                      [partial unique idx uniq_pas_active]
                                      ├─ on UniqueViolation → return existing active scan_id (dedupe)
positions.py → asyncio.create_task → auto_scan_for_position (background)
auto_scan_for_position → UPDATE status=running, started_at=NOW()
auto_scan_for_position → loop candidates → score 7 dims
                       → INSERT position_candidates (match_source='auto_scan_on_create')
                       → UPDATE n_scored every 5 (live progress)
auto_scan_for_position → UPDATE status=done, finished_at=NOW(), n_matched=K
                       (on exception → status=error, error=<msg>)

User opens AI tab → GET /api/positions/{slug}/ai
                 → returns {position, scan, matches[]} (top 20, composite desc, 7-dim breakdown)
                 → if scan.status in (queued,running):
                       open EventSource /api/positions/{slug}/ai/events?token=<jwt>
                       (EventSource has no headers — query param shim in core/auth.py:189-196)
                 → SSE event:scan {n_scored, n_matched, status} every 1s
                 → on event:end (status=done/error) → close + reload matches
                 → on EventSource error → fall back to 2s poll of GET /ai
```

Rescan path:
```
User → POST /api/positions/{slug}/ai/rescan  (role ≥ hiring_manager)
     → pre-check active scan
         ├── exists → {scan_id, status:in_progress, dedup:true}
         └── none   → _create_ai_scan_row + asyncio.create_task(auto_scan_for_position)
                       match_source='auto_scan_rescan'
```

Promote / Reject (per-candidate, optimistic UI):
```
POST /api/positions/{slug}/ai/{cid}/promote  (recruiter+)
  → UPDATE position_candidates SET stage='screened', match_source='ai_promoted'
POST /api/positions/{slug}/ai/{cid}/reject   (recruiter+)
  → UPDATE position_candidates SET dismissed=true, stage='rejected'
```

JD-update path mirrors create: PATCH JD → re-trigger `_create_ai_scan_row` →
`auto_scan_for_position` with `match_source='auto_scan_on_jd_update'`.

### Chat (HR Brain, SSE streaming)

```
POST /api/chat/stream {session_id, message}
  → load session history (limit 20 turns)
  → load 17 tools (candidate search, JD lookup, analytics, etc.)
  → Gemini-3-Flash with tool_choice=auto
  → stream tokens via SSE
  → frontend renders incrementally
  → on tool call: invoke local function, feed result back
  → save session + feedback to chat_sessions / chat_feedback
```

### Chat v2 — Agno agent (AGENT_V2=true, flag-gated)

```
POST /api/chat/stream {session_id, message, role}
  → backend/routes/chat.py branches on AGENT_V2 env
        ├── false → legacy SSE keyword path (unchanged, preserved)
        └── true  → agents/hr_agent.arun(message, session, role) [async gen]
                     │
                     ▼
        1. session.start() → INSERT agent_runs (status='running')
                              check sum(cost_usd) < AGENT_SESSION_CAP_USD or 429
        2. memory.recall(query)
              → embed_cache.get_or_set(query)  [Redis 24h, cosine to agent_memory]
              → SELECT ... ORDER BY embedding <=> $1 LIMIT AGNO_MEMORY_TOPK
              → top-K snippets injected into system prompt
        3. tool-loop (≤ AGNO_MAX_STEPS):
              LLM call (logged → llm_call_log step='agent')
              ├── if tool_calls:
              │     for each call:
              │       ├── role allowlist check (recruiter ✗ update_brain,
              │       │   analyst ✗ draft_email, admin/superadmin ✓ all)
              │       ├── PII redact inputs (national_id, dob, phone, email)
              │       ├── tool_cache.get_or_call(provider_fn)  [Redis 60s]
              │       ├── timeout AGNO_TOOL_TIMEOUT_S
              │       └── INSERT tool_traces (input_redacted, output, latency)
              │     yield SSE {type:'tool', name, status, latency}
              └── else: yield SSE {type:'token', text}
        4. memory.write(summary) → embed + INSERT agent_memory
        5. session.finish() → UPDATE agent_runs (status, cost_usd, steps)
        Response header: X-Chat-Version: 2
        Frontend renders <AgentSteps /> + <ToolTrace /> when header present
```

Rollback: `AGENT_V2=false` + recreate api → traffic returns to legacy keyword path.
Tables `agent_runs`, `agent_memory`, `tool_traces` (mig 033/034/035) remain harmless.

---

## Concurrency gates (per worker)

```
OCR_GATE       = threading.Semaphore(2)     # cv_parser._OCR_GATE
LLM_GATE       = threading.Semaphore(8)     # config.LLM_GATE
DB pool        = 5..20 conns                # database.py
Rate limit     = 600/min global             # rate_limit.py
                 5/min upload+login         # per-route decorators
                 30/min LLM endpoints       # per-route decorators
```

## Feature flag layer (nav visibility)

```
DB:    system_flags (key TEXT PK, value JSONB, updated_by INT)
       seeded by migration 007; defaults flipped by migration 032
       (interviews + pools = false)

API:   GET  /api/system/features        public, returns {key: bool}
       PATCH /api/admin/system/config/{key}   admin/superadmin only

UI:    +layout.svelte fetches /api/system/features at mount
       NAV_ALL filtered via $derived: features[flag] !== false
       /admin → SYSTEM tab → FEATURES → SHOWN/HIDDEN button per flag
```

## Billing / cost ledger

```
Every LLM call → _log_llm_call() in config.py
                 ├── stdout structured JSON (CloudWatch)
                 └── INSERT INTO llm_call_log (best-effort, never blocks)
                         {ts, tenant, operator, candidate_id, run_id, step,
                          model, in_tokens, out_tokens, cost_usd,
                          latency_ms, status, error}

GET /api/billing/summary?range=today|7d|30d|mtd
                                          ↓
                              { total_cost, cap_usd, cap_used_pct,
                                in_tokens, out_tokens, calls,
                                avg_latency_ms, p95_latency_ms,
                                timeouts, fails, jobs, fail_rate_pct }

Other endpoints (all admin-gated):
  /by-model     GROUP BY model
  /by-step      GROUP BY step
  /hourly       date_trunc('hour') buckets
  /jobs         GROUP BY run_id, paginated
  /top          ORDER BY cost_usd DESC LIMIT N
  /job/{run_id} per-step trace for one CV pipeline run
  /export.csv   streaming CSV of raw rows in range
```

Cluster total (4 workers) = 8 OCR jobs · 32 LLM calls · 80 DB conns · 2400 req/min HTTP.

---

## Storage layout

```
/data
├── cvs/                          # source CVs (PDF/DOCX/images)
│   ├── <uuid>.pdf
│   └── ...
├── screenshots/                  # 300 DPI WebP per page
│   └── cand_<id>_page_<n>.webp
└── backups/                      # pg_dump nightly
    ├── pulse_20260505_0300.dump.gz
    ├── pulse_20260504_0300.dump.gz
    ├── ...
    └── latest.dump.gz → pulse_20260505_0300.dump.gz
```

In ECS: `/data` = EFS access point with uid 1000 mapping. Multi-task safe.

---

## Migration model

```
db/migrations/NNN_<name>.sql          ← write here
       │
       ▼
backend/core/migrations.py
  ├─ acquire pg_advisory_lock(13371337)
  ├─ scan db/migrations/*.sql in order
  ├─ for each:
  │    sha256 file content
  │    SELECT FROM _migrations WHERE name=? AND sha=?
  │    if missing → forbidden-pattern check (DROP/RENAME/ALTER TYPE/TRUNCATE)
  │                 if forbidden AND not ALLOW_DESTRUCTIVE_MIGRATIONS=1 → RAISE
  │                 else execute + INSERT _migrations
  │    if sha mismatch → RAISE drift
  └─ release lock
```

Health endpoint surfaces `{applied, files, pending, drift, last_applied}`. Returns 503 if `pending` non-empty.

---

## Auth + sessions

```
JWT HS256 signed with JWT_SECRET (env, 32-byte hex)
  ├─ payload: {sub: operator_id, role, iat, exp}
  ├─ exp: 8h (JWT_EXPIRY_H env)
  └─ stored: localStorage hire_token + hire_token_exp

validate_token (backend/core/auth.py):
  1. Try JWT decode (HS256, verify exp)
  2. Fallback: SELECT FROM auth_tokens WHERE token=? (legacy hex)
  3. Return user dict or raise 401

Bootstrap superadmin (backend/routes/auth.py):
  on startup → if SUPERADMIN_ID set:
    UPSERT users (operator_id, email, display_name, pass_hash, role='superadmin')
    reset failed_login_count + locked_until
```

File access:

```
GET /candidates/{id}/file/sign  (Bearer)
  → HMAC(FILE_SIGN_SECRET, "{id}|{exp}") → sig
  → return {url: /candidates/{id}/file?sig=...&exp=..., ttl_s: 300}

GET /candidates/{id}/file?sig=...&exp=...
  → verify HMAC + exp not stale
  → stream file (range support)
```

---

## LLM cost path

```
caller → llm_call(prompt, model, tenant_id)
  → cost_cap.check_and_record(tenant_id, model, est_tokens)
       if total_today > LLM_DAILY_CAP_USD → raise CostCapExceeded
  → with LLM_GATE:
       _call_with_timeout(client, model, prompt, timeout=LLM_CALL_TIMEOUT_S)
  → log {ts, tenant, model, latency, in_tokens, out_tokens, cost_usd, status}
  → return text
```

---

## Frontend stack

```
SvelteKit 5 (Runes) + Tailwind CSS 4.2 + Material Symbols
Built once in Docker → served as static files by FastAPI

Routes:
  /login              public, dark terminal + yellow card (isolated)
  /careers            public, apply form
  /                   positions grid
  /candidates         CV repo with filter rail
  /candidates/[id]    profile (split-view: source on left, tabs on right)
  /jds                JD repository
  /jds/[id]           JD detail
  /positions/[slug]   position workspace (7 tabs)
  /chat               HR Brain SSE chat
  /analytics          7 V2 dashboards (overview/funnel/time/recruiter/dei/cost/qoh/predictive)
  /interviews         calendar
  /pools              candidate pools
  /admin              tenant + roles + automations + competencies

Layout:
  +layout.svelte: header (dark) + main (yellow) + footer (green) — wraps everything
  +layout.svelte: skips wrap when isPublicRoute (login, careers)
  +layout.ts: route guard, calls /api/auth/me, redirects to /login on 401
```

---

## Background workers

```
backend/agents/sync.py          — sync worker (long-running thread, launched in main.py)
backend/core/job_queue.py       — PG-backed job queue (no Celery)
backend/agents/ingest.py        — ingest helpers
backend/agents/facet_miner.py   — auto-discover skill facets from CV corpus
```

Cron-style tasks live in `compose.yaml backup` sidecar (pg_dump loop) and could be moved to ECS scheduled tasks for prod.

---

## Health endpoint shape

```json
GET /api/health
{
  "status": "ok",
  "app": "pulse",
  "version": "1.0.0-beta",
  "uptime_s": 3600,
  "db": {"status": "connected", "latency_ms": 2},
  "db_pool": {"min": 5, "max": 20, "active": 3, "idle": 2},
  "disk": {"path": "/data/cvs", "writable": true},
  "ai_available": true,
  "models": {"chat": "...", "deep": "...", "lite": "...", "verifier": "..."},
  "migrations": {
    "applied": 30,
    "files": 30,
    "pending": [],
    "drift": [],
    "last_applied": "2026-05-04T..."
  }
}
```

Returns **503** if `migrations.pending` non-empty (blocks ALB from sending traffic until migrated).

---

## Costs (rough, at 10 users)

| Item | $/month |
|------|---------|
| Aurora Serverless v2 (0.5 ACU idle) | ~$45 |
| Fargate (1 task, 1 vCPU, 2GB) | ~$30 |
| EFS storage + req | ~$5 |
| ALB | ~$20 |
| CloudWatch logs (30d) | ~$5 |
| Secrets Manager (5 secrets) | ~$2 |
| ECR storage | ~$1 |
| Data transfer | ~$5 |
| LLM (OpenRouter, mixed Gemini + Opus verify) | ~$30–80 |
| **Total** | **~$140–200/mo** |

Local Docker Compose: $0 + LLM only.

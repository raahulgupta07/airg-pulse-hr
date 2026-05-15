# PULSE — Org Heartbeat

> **People · Updates · Lifecycle · Sourcing · Engagement**
>
> Unified org platform — AI hiring, internal communications, job posting, broadcast & ads, candidate matching, HR Brain chatbot. (Formerly HIRE / DASH.)

**Repo**: https://github.com/raahulgupta07/airg-pulse-hr
**License**: Proprietary — All Rights Reserved (see [`LICENSE`](./LICENSE)). Source visibility ≠ license grant. Commercial / partnership inquiries: raahulgupta07apple3@gmail.com.

> **For new agents / devs onboarding:** read [`AGENTS.md`](./AGENTS.md) (5-min orientation) + [`ARCHITECTURE.md`](./ARCHITECTURE.md) (one-page system map) before touching code.

## Recent changes (2026-05-14 final) — GitHub push + LICENSE + bulk delete

- Repo pushed to GitHub: `raahulgupta07/airg-pulse-hr`. 400 files, 98,644 lines, branch `main`.
- `.gitignore` hardened: excludes `.env`, `.env.*` (except `.env.example`), `data/`, `backups/` (PII pg_dump), `pgdata/`, `*.pem/.key/.crt`, `secrets/`, logs, pytest caches, ide files, local notes, bench xlsx.
- Pre-push secret scan: 0 live secrets staged (no OpenRouter key, JWT_SECRET, bcrypt hash, admin password). Confirmed via grep across all 400 files.
- `LICENSE` added — proprietary "All Rights Reserved" custom license. No use, copy, modify, distribute, reverse-engineer, or ML-training rights granted by repo visibility. View-for-evaluation only.
- Bulk delete shipped:
  - `POST /api/bulk/delete-candidates` (admin+, max 200, hard delete + cascade + file unlink)
  - `POST /api/bulk/delete-jds` (admin+, max 200, hard delete + cascade)
  - CV repo: select-all checkbox now branches on `compareMode` (was no-op when in compare mode). Added `Delete N` red + `Clear` buttons to bulk toolbar.
  - JD repo: existing `jdBulkDelete()` rewired from N parallel `DELETE /jds/{id}?hard=true` to single `/bulk/delete-jds` call. Optimistic remove + reload.

## Recent changes (2026-05-14) — Pipeline-aligned candidates + 8 new agents + expiry/audit + agent config

### Candidates table rebuilt — 1:1 mirror of Pipeline kanban
Tab strip now matches kanban columns exactly: `ALL · AI · UPLOADED · SCREENED · SHORTLISTED · OFFERED · HIRED · REJECTED`. Same labels, same warm colors, same order. STAGE column folded into ACTIONS as a per-row `<select>` dropdown — change stage inline (no kanban drag needed). Score column shrunk to make room. AI suggestions show `[+]` promote / `[×]` dismiss instead of stage select (no stage until promoted). Svelte 5 fix: per-option `selected={...}` + keyed `{#each}` defeats DOM-cache bug where browser retained user's stale dropdown choice across reloads.

### Bulk attachment_state sync (data-corruption fix)
`/bulk/move-stage` + `/bulk/reject` now write `attachment_state` ('rejected' if stage=rejected else 'attached') + `dismissed` flag. Re-promote from rejected via dropdown works. Matches `/ai/{cid}/reject` semantics — bulk + AI single-row endpoints now consistent.

### 8 new background agents (16 total)

**JD agents** (mig 057):
- **`jd-bias`** — 30 min loop. LITE_MODEL flags gendered/ageist/ableist phrases → `bias_report JSONB` + PULSE FEED notif.
- **`jd-refresh`** — 6h loop. Flags JDs unchanged > `JD_REFRESH_DAYS` (60d) on active positions.
- **`jd-translator`** — 30 min loop. Picks JDs with `translate_to TEXT[]` (e.g. `['my','th','id']`), upserts `jd_translations(jd_id, lang, body)`. Idempotent.
- **`jd-completeness`** — 24h nightly. Heuristic 0–100 score → `completeness_score`. Notif if <50.

**Brain/Copilot agents** (mig 058):
- **`brain-trainer`** — 6h loop. Classifies low-confidence Copilot answers → `brain_unanswered` table + admin notif.
- **`doc-ingestor`** — 5 min loop. Watches `org_brain_uploads`, parses PDF/DOCX/TXT, chunks (500 chars + 50 overlap), embeds via `embed_text`, inserts into `org_brain(chunk_text, embedding vector(1536))` (HNSW indexed).
- **`qa-suggester`** — 1 min loop. Reads `qa_suggestion_queue`, generates 3 candidate-tailored interview questions per request via LITE_MODEL.
- **`faq-builder`** — 24h nightly. Embeds 30d Copilot user msgs, greedy clusters at cosine ≥ 0.85, builds FAQ for clusters ≥3.

**New endpoints** (`backend/routes/brain.py`):
- `POST /api/admin/brain/upload` (multipart, ≤25MB, .pdf/.docx/.doc/.txt)
- `GET /api/admin/brain/unanswered` · `POST .../address`
- `GET /api/admin/brain/uploads` · `POST /api/qa/queue` · `GET /api/qa/{cid}/{pid}` · `GET /api/faq/`

### Agent config UI (mig 059)
Per-agent admin panel at **`/admin?tab=agent-config`**:
- `agent_configs(agent_id PK, enabled, interval_seconds, thresholds JSONB, updated_by_id)` table seeded for all 16 agents
- `RUN_ONCE` map in registry + 10s-cached `is_enabled(agent_id)` helper. Agents poll DB at start of each cycle for early-exit when disabled.
- Endpoints: `GET /api/agents/config`, `PATCH /api/agents/config/{id}` (admin+, 60–86400s validation), `POST /api/agents/{id}/test-run` (admin+, 120s timeout, 501 if `run_once` unregistered)
- `AgentsConfigPanel.svelte` — 3-col responsive grid. Per-card: status dot, enable switch (instant PATCH + revert on fail), interval slider, thresholds JSON textarea, last/next/errors strip, [Test run now], [Save] (coral when dirty). Auto-refresh 8s.

### Expiry + audit columns (mig 055, 056)
- `candidates` + `jd_repository` extended: `expires_at TIMESTAMPTZ` (default `created_at + 90d`), `created_by_id INT FK users`, `updated_by_id INT FK users`, `updated_at TIMESTAMPTZ`. Backfill from legacy `owner_id`/`created_by`/`updated_by`. Index on `expires_at`.
- `app_settings('expiry_defaults', '{"cv_days":90,"jd_days":90}'::jsonb)` seeded — admin-tunable.
- New `backend/core/expiry.py` helpers. INSERT/UPDATE paths in candidates + jd_repo + ingest stamp the audit cols.
- CV/JD list endpoints now return `created_by_name`, `updated_by_name`, `expires_at`, `is_expired`, `days_until_expiry`.
- New endpoints: `GET/POST /api/admin/retention` (validates 1–3650 days, audit-logged).
- `RetentionPanel.svelte` — two number inputs, mounted as `Retention` tab in `/admin`.
- CV repo + JD repo lists: new columns `Added by · Updated by · Expires`. Chip styling: red `Expired`, amber `<14d`, neutral otherwise.
- **Constraint**: chip is purely visual — does NOT block edits, does NOT exclude from AI scan. Soft signal only.

### Migration roll
055 expiry_audit · 056 retention_settings · 057 jd_agents · 058 brain_agents · 059 agent_configs

### Pre-deploy hardening (same day)
- All 8 new agent loops gated by `is_enabled(agent_id)` early-exit + 60s sleep when disabled. Disabling an agent in admin UI now actually silences it (was no-op before).
- All 8 new agent loops sleep `get_interval(agent_id, default)` instead of hardcoded `INTERVAL_S` — admin slider in Agent Config UI now changes cadence within 10s.
- Per-agent LLM daily cost cap helper in `registry.py` (`get_llm_daily_cap`, `check_agent_cost_cap`). Reads `agent_configs.thresholds.llm_daily_cap_usd` or env `AGENT_LLM_DAILY_CAP_USD` (default $5/day per agent). Sums `llm_call_log` rows tagged `step="agent:<id>"`.
- `/api/agents/{id}/test-run` rate-limited `10/minute` (admin can't spam parallel cycles).
- `/api/admin/brain/upload` filename hardened: `secrets.token_urlsafe(16)` (replaced uuid) + abspath escape check (raises 400 on traversal attempt).
- ~100 LOC dead pool tab code removed from `CandidatesTable.svelte` (TAB_HELP.pool entry + empty-state + picker render branches). Helper fns preserved for parent's pool-browse modal.
- pg_dump snapshot at `backups/pre-deploy-2026-05-14.sql` (7.1MB) — rollback point.
- `hub-hr-agent-api:latest` image rebuilt with all 8 agents + brain routes + agent config UI + retention panel baked in. 0 boot errors after recreate.

**Status: ready for staging.** Open GA-list items (HttpOnly cookies, MFA, password reset) carry over.

## Recent changes (2026-05-13 late) — Claude warm theme + white-label + 30 UX features

Full app reskin from brutalist (mustard/ink/neon) → Claude.ai warm theme (cream `#faf9f5` + coral `#c96342` + 12px radius + Tiempos serif headings + Inter body). 22 pages/components updated, backup at `app.css.brutalist-backup`. Login page rebuilt Claude.ai-style: split layout, animated cursor tour over 6 tiles, SSO + LDAP buttons.

**White-label admin panel** (`/admin/branding`) — customize app name, logo (PNG/SVG base64), accent color (live HSL preview), footer. Persists via `app_settings` table (mig 046) + `POST/GET /api/admin/branding`. Layout + login hydrate brand on mount.

**Brand renamed** "Pulse" → "City Agent Pulse" everywhere user-visible. Component names + localStorage keys + event names preserved for wiring.

**30 UX features** shipped via parallel agents:
- ⌘K command palette + `?` shortcut overlay + j/k row navigation
- Skeleton loading + empty states (positions / CVs / JDs)
- Avatar dropdown → Profile / Notifications / Change password (mig 049 adds `users.notification_prefs JSONB`)
- Mobile responsive: hamburger drawer <900px, CV card list <768px, full-screen modals
- Onboarding tour + "Try with demo" + What's new modal + hire confetti
- Page transitions, hover preview cards, smart defaults, print stylesheet, focus rings, drag-drop upload, undo bar
- Recent + saved searches, bulk actions on JDs+positions, visual workflow builder
- @mentions + comment threads + presence avatars + activity feed
- Email templates editor + offer templates editor + schedule interview panel (.ics fallback)
- Analytics depth (Source ROI + Predictive + Comparative)
- AI Nudges merged into Pulse Feed dropdown
- Careers status lookup, GDPR export + scrub, Slack/Teams/GCal/Outlook/DocuSign/LinkedIn integrations marketplace

**Admin consolidation** — 5 sub-pages extracted to `lib/admin/*Panel.svelte`, rendered inline via tab state in `/admin`. URL `?tab=X` deep-link supported.

**Backend additions:**
- New routes: `templates.py` (email + offer CRUD), `automations.py` (workflows), `gdpr.py` (export + scrub)
- Migrations: 045 cv_content_hash, 046 app_settings, 047 templates, 048 automations, 049 user notif prefs
- `routes/admin.py` + branding + integrations endpoints; `routes/auth.py` + change-password + notification prefs
- Analytics `/funnel` alias; smart `/api/*` 307/404 fallback in `serve_frontend` (slash variant lookup before redirect)
- `redirect_slashes=False` + `RATE_LIMIT=off` (per-route caps still active: login 5/min, upload 5/min, LLM 30/min)

**Performance:**
- AI_SUMMARY model `CHAT_MODEL` → `LITE_MODEL` (gemini-3.1-flash-lite). **~6x cheaper** per CV. Override via `SUMMARY_MODEL` env.
- CV content-hash dedup (mig 045) — re-uploading identical bytes skips pipeline, orange toast shows existing cv_id.
- Svelte 5 `$effect` infinite-loop audit — fixed 30+ bugs across 22 files (was causing endless skeleton on page load). Pattern: convert to `onMount` for mount-only, wrap mutating calls in `untrack()` for dep-tracked.

**Docker:**
- Frontend bind-mount `./frontend/build:/app/static-frontend:ro` in compose.yaml. Build changes survive container recreate.

## Recent changes (2026-05-13) — Interview Kit (per-position, generic + tailored)

New tab on the position page: **`Interview Kit`**. Generates audience-specific interview questions per role, optionally tailored to a specific AI-matched candidate using their match gaps + strengths.

**Backend**
- Migration `db/migrations/044_interview_kits.sql` — `interview_questions` table. Audience ∈ HR_BP / HIRING_MGR / PANEL / TECH. Category ∈ BEHAVIORAL / TECHNICAL / CULTURE / ROLE_SPECIFIC / GAP_PROBE / STRENGTH_VERIFY. Stage ∈ SCREEN / TECH / ONSITE / FINAL. Fields: `look_for[]`, `red_flags[]`, `source` (ai_generic / ai_tailored / manual), `used` flag.
- Agent `backend/agents/interview_kit_gen.py`: `generate_generic` (role-level bank) + `generate_tailored` (uses gaps/strengths + composite + match_explanation, weights toward GAP_PROBE/STRENGTH_VERIFY). LITE_MODEL ≈ $0.0005/batch. Per-audience focus + per-stage depth tuned in prompt.
- Routes (registered under `/api`):
  - `GET /positions/{slug}/interview-kit?candidate_id=&audience=&stage=` — list, grouped by category
  - `POST /positions/{slug}/interview-kit/generate` (recruiter+, 10/min) — body `{candidate_id?, audience, stage, count}` → batch INSERT
  - `PATCH /interview-kit/{qid}` — edit q / look_for / red_flags / category / audience / stage
  - `DELETE /interview-kit/{qid}` · `POST /interview-kit/{qid}/used` — mark used
  - `GET /positions/{slug}/interview-kit/export.md` — markdown handoff (sections per category)

**Frontend**
- `frontend/src/lib/interview-kit/InterviewKit.svelte` — toolbar (candidate dropdown = Generic + top-12 AI matches w/ score, audience pills, stage select, count), grouped sections, inline edit cards w/ COPY / EDIT / ✓ USED / x REMOVE, context strip. Brutalist style.
- Position page `+page.svelte` — added `Interview Kit` tab (icon=quiz) between Dashboard and Settings.

**Tests**
- `tests/test_interview_kit.py` — 10 tests: list empty/seed, audience filter, stage filter, edit, mark used, delete, export.md, bad audience reject, position 404, generate-generic (LLM-gated skip).

**Smoke (live)**: created `AI Software Engineer` position (id 37), uploaded CV `Aisha Zaw` (id 12, 6yr senior AI eng), AI rescan matched at **71%** (#1 of 4). Generated 4 generic HR_BP/SCREEN + 4 tailored TECH/TECH for Aisha — tailored hit GAP_PROBE on LLM pre-training and STRENGTH_VERIFY on pgvector multi-tenant.

## Recent changes (2026-05-12) — Pipeline parallelism + CLI + JD bg agent

**Pipeline performance**
- True 8-way parallel CV pipeline. Wrapped sync `llm_call` / `embed_text` / `extract_structured_data` / `enrich_candidate` / `generate_qa_pairs` / `compute_quality_score` with `asyncio.to_thread`; HYPE/CONTEXT embeddings now via `asyncio.gather`. Was serial because sync LLM blocked event loop.
- Default embed model → `text-embedding-3-small` (1536d, faster than `-large`)
- `STRUCTURE_MODEL` defaults to `LITE_MODEL` (Gemini-3.1-Flash-Lite faster for JSON than 3-Flash)
- **Queue worker system** (`MAX_PARALLEL_PIPELINES`) in `candidates.py`: `_pipeline_queue` + `_active_tasks` dict. `bulk_process` enqueues, returns instantly. `force` param: RUN ALL=true, RUN PENDING=false.
- **WORKERS=1** — single uvicorn worker for in-memory state cohesion (cancel/queue across worker boundaries doesn't work)

**Bulk CV upload + run controls**
- Single `Upload CV(s)` button (merged with old Bulk) — multi-select OS file picker, 50-file cap, email dedup
- CV REPO: `RUN ALL` / `RUN PENDING ONLY` / `STOP ALL` + per-row `▶ RUN` / `■ STOP`. Optimistic UI = button disables on click.
- 409 on `/run` → auto-retry `/reprocess`
- `GET /candidates/queue-status` returns `running ∪ active_alive` + `queue_positions`. Polled 1.5s.
- RUNNING NOW banner with cv-chips → click scrollToRow + flash animation. Queue-running rows pinned to top.
- Per-row badge: `RUNNING` or `QUEUED #N`
- Auto-prune dismissed IDs within 1h created_at (fixed empty repo after DB `RESTART IDENTITY`)

**Pipeline CLI terminal** (`PipelineTerminal.svelte`)
- Bottom-dock, default collapsed, auto-expands on `running > 0`
- Lines: info/success/error/warn/complete with distinct colors. `🎉 PIPELINE COMPLETE` = green gradient banner.
- Streams via `/pipeline-events?since_id=N` monotonic cursor, dedup by `${id}:${status}` (status transitions matter)
- Per-row progress bar from pipeline_trace running/done counts

**Compare CVs — AI summary + Excel export**
- `position_slug` now optional on `/compare` (was 404 without). New `_generate_open_comparison()` LLM fn.
- AI Executive Summary panel (green gradient) + `GET /matching/compare/export.xlsx?ids=` openpyxl 2-sheet workbook (Comparison + AI Summary)
- Uses `api()` helper for auth (fixed 401 from missing getToken)

**DOCX inline viewer**
- `mammoth.js` dynamic import → DOCX→HTML client-side render
- Both PDF + DOCX scroll inside viewer: outer `overflow:hidden` + inner `flex:1 1 auto; min-height:0; overflow-y:auto`

**JD Background Agent** (`backend/agents/jd_background.py` — NEW)
- Runs every `JD_BG_INTERVAL_S` (default 300s). **Fills MISSING fields only — does NOT rewrite jd_text.**
- Per JD: `required_skills`, `department`, `seniority_level`, `certifications`, `min_experience_years` (UPDATE only when empty); KF4D competencies via `_internal_extract_jd_competencies`
- STATE dict + EVENTS ring buffer (200) + `_emit(kind,msg,level)`. Lifecycle: `idle→scanning→sleeping`.
- `GET /api/jd-background/status?since_id=N` — state + events + max_id + interval_s

**JD Agent robot badge** (`JdAgentBadge.svelte` — NEW)
- **Placed in top nav header — replaces `ORG HEARTBEAT` text**
- Collapsed pill: `🤖 [dot] JD AGENT · STATUS [count]` with bob animation when active
- Expanded panel: status / current_action / last_run / next_scan countdown / total processed / recent activity (last 12)
- Mirrors all events to CLI terminal via `window.dispatchEvent('hire-cli')`
- Polls every 4s, tick every 1s

**Auth + login fixes**
- Black screen on login — gated `:global(body)` styles behind `.login-active` class, removed on unmount
- Login 401 — frontend was sending both `operator_id+access_key` AND `email+password`; backend tried email first → 401. Send only one shape based on `@` in operatorId.
- `bootstrap_superadmin` — added `gen_public_id("users")` (NULL public_id was failing)
- Reset credentials: `pulse_admin` / `admin`

**Delete modal fixes**
- Removed CSS `text-transform: uppercase` (input looked uppercase but value wasn't)
- Accept either position name OR `DELETE` literal (case-insensitive)
- Keyed `{#each positions as pos (pos.slug)}` + optimistic local filter (was requiring page refresh)

**Health endpoint** — moved `/health` → `/api/health`

**Deploy note** — Never `docker compose up --force-recreate` (wipes image). Use `docker cp` + `docker restart pulse-api`.

**Test fixtures** — generated 50 JDs + 110 CVs (.docx) for load testing

---

## Recent changes (2026-05-11) — MVP readiness pass

**Removed**
- **Interviews feature** — `/interviews` route, `backend/routes/interviews.py`, frontend tab/calendar/scorecards UI, DB tables (`interviews`, `interview_scorecards` dropped → replaced with empty SQL views for legacy analytics SQL compat), `feature_interviews` flag, Interview stages in kanban
- **Pools feature** — `/pools` route, `backend/routes/pools.py`, DB tables (`candidate_pools`, `pool_members`), nav entry, `feature_pools` flag, `add_to_pool` automation action

**Added / Reworked**
- **JD Generate** — 2-step flow: AI returns preview (no DB write) → user reviews rendered markdown → clicks **✓ Save to JD Pool** to persist
- **JD Paste** — separate modal (no internal tab toggle). 2 save modes: `Save As-Is` (raw text + AI extracts skills/years/cert/dept/seniority) or `✨ AI Enhance & Save` (LLM rewrites for DEI/clarity/completeness + DEI/completeness scores)
- **Markdown renderer** — rendered preview for generated/enhanced JD (H2/H3 headings, pipe tables, bold, lists). Toggle `Rendered` ↔ `Edit Markdown`
- **KF4D Competencies auto-extracted** on JD create / generate / enhance (was manual)
- **Hard-delete with double-confirm modal** — CV, JD, Position. Red modal + type-`DELETE` text input. Role-gated: creator OR superadmin (CV/JD); hiring_manager OR admin/superadmin (Position)
- **Public ID prefixes** — `cv_`, `jd_`, `pos_`, `usr_`, `sec_` (ULID Crockford base32, 26-char, time-sortable) + dual int/public_id resolution
- **OpenAI-only embedding cascade** — `text-embedding-3-large` (primary) → 3-small (fallback). Gemini-2-preview removed (rate-limit flaky)
- **JD semantic search** — `jd_embedding vector(1536)` + HNSW cosine index, `/jds/embeddings/backfill`, `/jds/search/semantic?q=...`
- **CV repo layout** — title + buttons + search moved INSIDE body (right of rail), top-aligned with rail (matches JD pattern)
- **Compare mode persistence** — selections + mode flag persist to localStorage across nav
- **Source badges** — Candidate cards on position page show `✨ AI` vs `👤 MANUAL` + filter chips (all / ai / manual), `auto_added` boolean + `added_by` text column
- **Kanban auto-sizing** — columns expand based on card count, sticky stage headers
- **Trailing-slash fix** — `POST /api/jds/`, `POST /api/positions/` (FastAPI strict-routing)
- **`superadmin` role** — added to `is_admin` checks in `jd_repo.py` for share-global (was admin/group_hr only)
- **Auto-switch scope → MINE** after JD save (new JDs default `visibility=private` so were hidden in SECTOR view)
- **Stage rollback** — Kanban now 5 stages: `uploaded · screened · shortlisted · offered · hired · rejected` (no `interview_scheduled`/`interviewed`)
- **Position route** — `DELETE /positions/{slug}?hard=true` (was archive-only)
- **Favicon** — green briefcase SVG, replaces globe; manifest + apple-touch-icon wired

**Known caveats (not blocking MVP)**
- `interviews` + `interview_scorecards` exist as empty SQL views so legacy analytics SQL in `analytics.py`/`analytics_v2.py`/`export.py`/`emails.py`/`candidates.py`/`evaluation.py` doesn't crash. Real fix = refactor those queries to drop the JOINs.
- Dev mode auth bypass (`DEV_MODE=true` → user_id=1, role=admin) still active — flip OFF for prod
- HTTPS not yet enforced; JWT in localStorage (XSS-stealable)

## Features

### Core Platform
- **Position Projects** — Create positions, add JDs (AI generate/paste/attach from repo), manage candidates
- **JD Repository** — Central JD library with AI generation, enhancement, DEI/legal/completeness checks. Per-JD `[ ✦ ENRICH FIELDS ]` button (next to `[ ✦ AI ENHANCE ]`) fills empty structured fields (department / seniority / min_exp / required_skills / nice_to_have_skills) without rewriting `jd_text`. **Real-time JD field enrichment via Postgres LISTEN/NOTIFY — no manual trigger needed** (3-5s latency, ~$0.0003/JD).
- **CV Repository** — Upload PDF/DOCX/PNG/JPG, hybrid OCR (PaddleOCR + Vision LLM + Opus verifier for digit precision), AI extraction
- **Manual Upload + Pending Queue** — Upload stages files; user clicks `▶ RUN` to trigger 13-step pipeline; multi-file parallel uploads (cap 4) with per-file progress bars
- **Global CLI Terminal** — Bottom-right docked terminal panel streams pipeline events live across all running uploads (color-coded, auto-scroll, MIN/CLEAR/SAVE)
- **Split-View Profile** — Source document permanently visible on left, extracted-data tabs on right (drag handle, localStorage persist, mobile-aware)
- **Demographics Extraction** — 9 fields (DOB, NRC, gender, marital, nationality, religion, height, weight, father) auto-extracted from handwritten forms via Opus verifier
- **CV-JD Matching** — 7-dim weighted scoring (skills/experience/education/certifications/industry/culture/competencies), auto-scan, auto-match
- **Competency Layer** — KF4D framework (12 seeded), per-source weighted aggregation, position fit chart with critical-gap detection
- **Pipeline Kanban** — Drag-drop candidates through stages (uploaded → hired)
- **HR Brain Chat** — SSE streaming chatbot with context injection, session history, suggestions

### Position AI Tab

Per-position auto-matching workspace. **As of 2026-05-12 (round 2) the standalone `AI` tab was removed** — position workspace is now **6 tabs**, and AI matches live inside the **CANDIDATES** tab as two stacked sections: **AI MATCH** (top, ranked top 20 with empty-state messaging) + **SHORTLISTED CVS** (below, with `✨ AI` / `MANUAL` source pill and `N TOTAL · M AI · K MANUAL` count). Promoted candidates auto-disappear from AI MATCH (filter `stage='uploaded'`).

When a position is created or its JD is updated, the backend launches a single ranked scan of the central CV repo and surfaces the top 20 candidates with full 7-dim score breakdowns. Hiring managers can promote, reject, or bulk-promote directly from the inline action bar; per-CV scanning on every upload is gated OFF by default (`MATCH_ON_CV_UPLOAD=false`).

- Auto-match CVs to position on creation (ranked top 20)
- Live SSE progress stream (`/ai/events`, 1s tick, 2s-poll fallback). HMAC-signed URL via `/ai/events/sign` (5-min TTL); legacy `?token=` deprecated.
- Filter (ALL / TOP 10 / ABOVE 80% / NEW THIS WEEK), sort, bulk select
- Promote / reject / **bulk-promote** (cap 50) from inline action bar; audit-logged
- Auto-rescan on JD update (incl. JD attach from repo); manual rescan endpoint (`POST /ai/rescan`) deduped via partial unique index
- Stale-sweeper marks queued/running scans >10min old as `error/stale_on_restart`
- Score chip color thresholded against `position.min_match_score`; tooltip surfaces `match_explanation` + strengths/gaps

### CandidateDrawer + PULSE FEED (round 2)

- **CandidateDrawer** — slide-in 600px right-side drawer triggered from AI MATCH / SHORTLISTED / PIPELINE rows. 6 tabs (PROFILE / SKILLS / EXPERIENCE / SCORE / DOCS / PIPELINE). DOCS probes signed URL with 404 fallback. SCORE tab shows 7-dim breakdown when invoked with position context. SUMMARY field renders markdown (escape-first).
- **PULSE FEED** — unified top-nav widget replacing the legacy bell + JD agent badge. Single `[🔔 PULSE FEED · N]` button + dropdown tabs ALL / NOTIF / JD / AI. Real-time SSE, mark-read / mark-all-read, 100-event cap. Aggregates 4 sources: `notifications`, recent AI scans, recent AI candidate attaches, JD background agent state.

### AI Intelligence
- **Auto-scan** — When JD saved, automatically finds and ranks matching CVs
- **Auto-match** — When CV uploaded, automatically matches against all open positions
- **JD Generation** — 500+ word JDs from bullet points with 7 sections
- **Smart NLP Search** — "Find backend engineers with 5+ years from FAANG"
- ~~AI Interview Questions~~ (interviews feature removed)
- **AI Candidate Summary** — One-click executive brief
- **AI Pipeline Insights** — "5 candidates stuck in screening for 7+ days"
- **AI Salary Recommender** — Market-based salary range suggestions
- **AI Email Composer** — Personalized rejection/offer emails

### LinkedIn-Style Features
- **Candidate Profile** — Tabs: profile / experience / skills / competencies / assignments / notes / scorecards / pipeline / activity (interviews tab removed)
- **Advanced Search** — Multi-filter with skill chips, boolean operators (AND/OR/NOT)
- **Interview Calendar** — Monthly view, ICS export, multi-stage interview definitions
- **Scorecards** — Structured feedback per interviewer, AI pre-fill
- **Offer Management** — Full workflow with approval chains
- **Notifications** — Bell icon with WebSocket real-time push
- **Career Page** — Public job board with apply flow + EEO data collection
- **Analytics** — ECharts dashboard (funnel, heatmap, Sankey, leaderboard, diversity)

### Evaluation Intelligence (auto-generated, zero clicks)
- **Scorecard Templates** — 6 role-type templates auto-matched to positions
- **Competency Rubrics** — Auto-generated from JD, 1-5 scoring with labels
- **Culture/Values Scoring** — 6th dimension, keyword-based cultural alignment
- **AI Red/Green/Amber Flags** — Job hopping, gaps, overqualified, missing skills detection
- **Consensus Scoring** — Auto-computed agreement level, lone dissent detection
- **Hiring Committee Votes** — SH/H/NH/SNH distribution from scorecards
- **Stack Ranking** — Composite + consensus + flags, #1/#2/#3 badges everywhere
- **Calibration Report** — Interviewer harshness index, consistency tracking

### Automation
- **Rules Engine** — Trigger → condition → action (auto-move stage, send email, tag)
- **Email Sequences** — Multi-step automated email campaigns
- **SLA Tracking** — Flag candidates stuck too long in a stage
- **Screening Questions** — Per-position with knockout criteria

### Integrations
- **LinkedIn Import** — Paste URL or profile text
- **GitHub Analysis** — Analyze repos, languages, contributions
- **CSV Export** — Candidates, positions, analytics
- **ICS Calendar** — Download interview invites
- **Email Sending** — SMTP integration with templates

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Backend** | FastAPI (Python 3.11) | Async, 165+ API endpoints |
| **Frontend** | SvelteKit 5 + Tailwind 4 | Reactive, compiler-based |
| **Database** | PostgreSQL 18 | 44 tables, job queue, migrations |
| **LLM / Agent** | OpenRouter (Gemini/GPT/Claude) + Agno (Chat v2, flag-gated) | 4-model + agent tool-loop with 11 tools |
| **OCR** | PaddleOCR + Vision LLM | Free local + paid handwriting |
| **Cache** | Redis (embed 24h, tool 60s) + in-memory fallback | Agent memory recall + tool dedup |
| **Design** | Brutalist/Newspaper | Space Grotesk, stamp shadows |

## Install

Two install paths. Same codebase, env decides target.

| Path | Use case | Time | Detail |
|---|---|---|---|
| **A. Docker Compose** | Beta / single-host prod / local dev | 5 min | Below — `compose.yaml` |
| **B. AWS ECS Fargate** | Production, multi-AZ, autoscale | 30–60 min one-time | Below + `DEPLOYMENT_AWS.md` |

---

### Path A — Docker Compose (local + beta)

**Prerequisites**: Docker 24+ with Compose V2, ~4 GB free RAM, ~5 GB disk.

Two ways to install. Pick one.

#### A1. Manual flow (most engineers)

```bash
# 1. Clone
git clone https://github.com/raahulgupta07/airg-pulse-hr.git
cd airg-pulse-hr

# 2. Create .env from template
cp .env.example .env

# 3. Edit ONLY the 4 values at the top of .env:
#    OPENROUTER_API_KEY=sk-or-v1-...   (leave blank to skip AI features)
#    SUPERADMIN_ID=pulse_admin
#    SUPERADMIN_PASS=<your-strong-password>
#    PORT=8090
nano .env

# 4. Build + start (4 containers: api, db, redis, backup sidecar)
docker compose up -d --build
# First build pulls images + installs deps: ~5–15 min.

# 5. Wait for healthy + verify
until curl -sf http://localhost:8090/api/health; do sleep 3; done
docker compose ps    # all should show "healthy"
```

Open `http://<host>:8090` → log in with the `SUPERADMIN_ID` / `SUPERADMIN_PASS` you set.

**Everything else is auto-handled by the app/compose defaults** — `JWT_SECRET` is
auto-generated and persisted to `/data/.jwt_secret`, `DB_PASS` defaults to
`pulse_secret`, CSRF/CORS accept same-host origins, `/data/cvs` is auto-created
and chmod'd, account lockouts clear every restart. Override anything in `.env`
if you need to (see the commented OPTIONAL section in `.env.example`).

#### A2. Interactive setup (no editor needed)

```bash
git clone https://github.com/raahulgupta07/airg-pulse-hr.git
cd airg-pulse-hr
./setup.sh
# Answers 4 prompts → writes .env → builds → boots → prints login URL.
```

#### Verify install

```bash
curl -s http://localhost:8090/api/health | jq .status        # "ok"
curl -s http://localhost:8090/api/health | jq .migrations    # applied N, pending []
docker logs pulse-api --tail 80 | grep -iE "error|started"   # spot check
```

If the API does not come up healthy within ~2 min, see [Troubleshooting](#troubleshooting).

---

### Upgrades (existing install → new commit)

Preserves all data, settings, users, CVs, and JD repository.

```bash
# 1. Snapshot DB + files
./scripts/pre_upgrade.sh
# Writes ./data/backups/pre_upgrade_<timestamp>.dump.gz

# 2. Pull latest
git fetch origin
git pull origin main

# 3. Rebuild + restart (migrations auto-run on boot, advisory-locked)
docker compose up -d --build

# 4. Verify
curl -s http://localhost:8090/api/health | jq '{status, migrations}'
docker logs pulse-api --tail 50 | grep -iE "migration|started"
```

**Roll back** if the new build is broken:
```bash
git reset --hard <previous-commit-sha>
docker compose up -d --build
# If a destructive migration ran, restore the dump:
./scripts/restore.sh ./data/backups/pre_upgrade_<timestamp>.dump.gz --confirm
```

The migration runner is **additive-only** by default (DROP / RENAME / ALTER
TYPE / TRUNCATE are blocked unless `ALLOW_DESTRUCTIVE_MIGRATIONS=1` is set),
so most rollbacks just need the code revert + container rebuild.

See `UPGRADE.md` for full upgrade flow + rollback details.

### Common operations

```bash
docker compose ps                       # container status
docker logs -f pulse-api                # tail api logs
docker logs -f pulse-db                 # tail db logs
docker compose restart api              # restart api only
docker compose down                     # stop, keep data
docker compose down -v                  # stop + WIPE all data (destructive)
docker exec -it pulse-db psql -U pulse -d pulsedb    # psql shell
docker exec -it pulse-api bash          # api shell
./scripts/backup.sh                     # manual pg_dump now
```

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `bind: address already in use` on `:8090` | Port busy on host | Set `PORT=8091` in `.env`, restart |
| Login returns 401 | Wrong `SUPERADMIN_PASS` | Edit `.env`, `docker compose restart api` (UPSERTs new hash on boot) |
| Login returns 403 | `Origin` header mismatch | Already auto-allowed for same host; check reverse-proxy passes `Origin` + `X-Forwarded-Host` |
| Account locked | 5 failed logins | Restart `pulse-api` — bootstrap clears lockout on every boot |
| `/api/health` returns 503 | Migration pending or DB unreachable | `docker logs pulse-api \| grep -i migration`, fix SQL, restart |
| `[startup] CV storage path=/data/cvs writable=False` | Volume perm issue | `docker exec pulse-api ls -la /data` — entrypoint auto-chmods, but custom bind mounts need `chmod 777 ./data` on host first |
| `[cache] Redis unavailable` | Redis container down | App still runs (in-mem fallback). `docker compose up -d redis` to recover |
| AI features return errors | `OPENROUTER_API_KEY` missing/invalid | Set valid key in `.env`, `docker compose restart api` |
| Vision verifier model warning | Anthropic alias deprecated | Set `ENABLE_VISION_VERIFIER=false` or pin `VISION_VERIFIER_MODEL` to a current ID |
| OOM kills on CV upload | Box <8 GB RAM, too many OCR workers | Set `OCR_CONCURRENCY=1 WORKERS=1` in `.env`, restart |
| Frontend 404 / blank page | Bind-mount shadowed image static dir | Already removed — make sure `compose.yaml` has no `./frontend/build:/app/static-frontend` |

Reset everything (last resort, **destroys all data**):
```bash
docker compose down -v
rm -rf data/   # if you had bind mounts
docker compose up -d --build
```

---

### Path B — AWS ECS Fargate (production)

Architecture: ALB → ECS Fargate → Aurora Postgres Serverless v2 + EFS + Secrets Manager + CloudWatch.

Prerequisites: AWS account, domain + ACM cert in us-east-1, Terraform 1.6+, AWS CLI v2, Docker buildx, GitHub repo with OIDC trust to AWS role.

**One-time bootstrap**:
```bash
# 1. State backend
aws s3 mb s3://pulse-tfstate-<your-org>
aws dynamodb create-table --table-name pulse-tflock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# 2. Configure Terraform
cd deploy/aws/terraform
cp backend.tf.example backend.tf       # edit bucket + table
cp terraform.tfvars.example terraform.tfvars
# Edit tfvars: certificate_arn, env_name, region, route53_zone_id (optional)

# 3. Apply ECR first so we can push image
terraform init
terraform apply -target=module.ecr

# 4. Build + push first image
bash ../scripts/push-image.sh latest

# 5. Apply full infra (VPC, ECS, Aurora, EFS, ALB, IAM, Secrets, SSM)
terraform apply

# 6. Enable pgvector inside Aurora (one-time)
aws rds-data execute-statement \
  --resource-arn $(terraform output -raw rds_cluster_arn) \
  --secret-arn $(terraform output -raw db_master_secret_arn) \
  --database pulsedb --sql "CREATE EXTENSION IF NOT EXISTS vector;"

# 7. Seed superadmin in Secrets Manager
bash ../scripts/bootstrap.sh           # prompts password, hashes, writes secret

# 8. First deploy via GitHub Actions
gh workflow run deploy-aws.yml -f env=prod
```

**Day-2 ops**:
```bash
bash deploy/aws/scripts/tail-logs.sh        # live CloudWatch logs
bash deploy/aws/scripts/exec-shell.sh       # shell into a running task
bash deploy/aws/scripts/db-snapshot.sh      # manual RDS snapshot
```

Estimated cost: ~$120/mo idle, ~$200–400/mo light usage. See `DEPLOYMENT_AWS.md` for full operator guide (architecture, security hardening, multi-app expansion, troubleshooting).

## OCR Architecture (Tiered)

```
Upload CV (manual run via ▶ RUN button on Pending Files table)
    │
    ├── Digital PDF       → PyMuPDF              FREE (instant)
    ├── DOCX              → python-docx          FREE (instant)
    ├── Scanned/Typed     → PaddleOCR            FREE (local, no GPU)
    ├── Handwritten/Image → Gemini-3-Flash       ~$0.0014/doc — vision OCR
    └── Tesseract                                FREE (last-resort fallback)

  Step 2.5 VERIFY (handwritten / image only):
    └── Claude Opus 4.7   → critical fields      ~$0.014/doc
        ├── name + dob + phone + national_id + email
        └── + 4 demographic fields (gender, marital, height, weight, father)

Combined tier = Flash + Opus verifier ≈ $0.015/doc, 17/17 fields, 3/3 critical exact
  4× cheaper than full Opus, matches Opus quality on Myanmar driver-form bench.
```

10-model bench results in `bench/vision_results.xlsx`.

## Scoring Engine

```
CV vs JD Match Score = Weighted Composite (7 dimensions):
  ├── Skills Match        — required + nice-to-have overlap
  ├── Experience Years    — fit vs minimum requirement
  ├── Industry Relevance  — company/domain keyword match
  ├── Education Fit       — degree level comparison
  ├── Certifications      — required cert match
  ├── Culture Fit         — keyword-based cultural alignment
  └── Competencies        — KF4D framework, per-source weighted (manual=1.0, scorecard=0.9, cv-extract=0.6)
```

Inheritance chain: tenant → sector → JD → position (with JD lock support).
Weights configurable per position. Knockout criteria supported.
AI weight suggestions: lower-knockout, boost-dim, drop-weak (concrete weight payloads).

## Evaluation Pipeline

```
Auto-Trigger Chain (zero button clicks):
  Position Created ──→ Template auto-matched to role type
  JD Saved/Enhanced ──→ Rubrics auto-generated from template
  Candidate Scored ───→ Flags auto-generated + culture scored
  Scorecard Submitted ─→ Consensus auto-recomputed
  Page Loads ─────────→ All eval data fetched (6 parallel API calls)

Stack Rank = Composite(60%) + Consensus(30%) + Flag Penalty(10%)
  Red flag:   -5 points    Amber flag: -2 points    Green flag: +1 point
```

## Pages

| URL | Page | Auth |
|---|---|---|
| `/` | Positions grid | Yes |
| `/jds` | JD Repository | Yes |
| `/jds/[id]` | JD Detail (full page) | Yes |
| `/candidates` | CV Repository | Yes |
| `/candidates/[id]` | Candidate Profile | Yes |
| `/positions/[slug]` | Position Workspace (7 tabs) | Yes |
| `/analytics` | Analytics Dashboard | Yes |
| `/chat` | HR Brain Chat | Yes |
| `/careers` | Public Career Page | No |
| `/login` | Login/Register | No |

## API Endpoints

165+ endpoints across 22 route modules. Full docs at `/api/docs`.

Key endpoints:
```
# CV intake (manual flow)
POST /api/ingest/                          # Upload + classify (auto_process=false to stage only)
POST /api/candidates/upload                # Direct upload (PDF/DOCX/PNG/JPG)
GET  /api/candidates/pending?include_recent=true   # Pending + last 24h DONE w/ cost+latency
POST /api/candidates/bulk_process          # Trigger pipeline for selected ids
POST /api/candidates/{id}/process          # Manual run pipeline → returns run_id
GET  /api/candidates/{id}/file             # Stream original file (preview/download)
GET  /api/candidates/{id}/pipeline_trace   # All runs grouped, w/ steps + cost
GET  /api/candidates/{id}/artifacts        # Counts: embeddings, qa_pairs, screenshots, verified

# Search/match
POST /api/candidates/smart-search          # NLP search
POST /api/matching/scan/{slug}             # Scan CV repo for position

# Position AI Tab (auto-match per position)
GET  /api/positions/{slug}/ai              # {position, scan, matches[]} — top 20 ranked
POST /api/positions/{slug}/ai/rescan       # Re-launch scan (hiring_manager+); deduped if active
GET  /api/positions/{slug}/ai/events       # SSE progress stream (?sig=&exp=&uid= signed; legacy ?token= deprecated)
GET  /api/positions/{slug}/ai/events/sign  # HMAC-sign SSE URL → {url, exp, ttl_s:300}
POST /api/positions/{slug}/ai/{cid}/promote     # Set stage='screened', match_source='ai_promoted'
POST /api/positions/{slug}/ai/{cid}/reject      # Set dismissed=true, stage='rejected'
POST /api/positions/{slug}/ai/bulk-promote      # {candidate_ids:[...]} cap 50, single txn

# Candidate AI matches
GET  /api/candidates/{id}/ai-recommendations    # Positions where candidate is AI-matched

# PULSE FEED (unified notifications + JD bg + AI events)
GET  /api/feed?limit=N                     # {events, unread_count, by_type}
GET  /api/feed/events                      # SSE stream (2s poll, : ping every 25s, 30min cap)
POST /api/feed/mark-read                   # {ids:[...]}
POST /api/feed/mark-all-read

# JDs / Competencies
POST /api/jds/generate                     # AI JD generate
POST /api/jds/{id}/enhance                 # AI enhance JD (rewrites jd_text)
POST /api/jds/{id}/enrich?force=false      # Fill empty structured fields only (no jd_text change). Owner/admin gated. Also auto-fired via LISTEN/NOTIFY trigger on insert/update.
POST /api/jds/{id}/competencies/auto-extract
GET  /api/competencies                     # KF4D library
GET  /api/positions/{slug}/competency-fit/{cid}

# HR Brain
POST /api/chat/                            # SSE streaming

# Analytics
GET  /api/analytics/overview
GET  /api/analytics/v2/competency-calibration
GET  /api/analytics/v2/competency-gaps
GET  /api/evaluation/positions/{slug}/stack-rank
GET  /api/health                           # Health + AI status
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | For AI | — | OpenRouter API key |
| `DB_USER` | Yes | `pulse` | PostgreSQL user |
| `DB_PASS` | Yes | `pulse_secret` | PostgreSQL password |
| `DB_DATABASE` | Yes | `pulsedb` | Database name |
| `DEV_MODE` | No | `false` | Bypass auth in development |
| `ALLOWED_ORIGINS` | Yes (prod) | `localhost:5173,localhost:8090` | Comma-separated CORS origins. No wildcard in prod |
| `LOG_FORMAT` | No | `text` | `text` or `json` |
| `PRELOAD_OCR` | No | `false` | Pre-warm PaddleOCR on startup |
| `DISABLE_PADDLE_OCR` | No | `false` | Use Vision LLM only |
| `ENABLE_VISION_VERIFIER` | No | `false` | Enable Step 2.5 critical-field verifier |
| `VISION_VERIFIER_MODEL` | No | `anthropic/claude-opus-4.7` | Verifier model (digit precision) |
| **Auth (login system)** | | | |
| `JWT_SECRET` | Yes | — | HS256 signing key (≥32 bytes random) |
| `JWT_EXPIRY_H` | No | `8` | Token lifetime hours |
| `SUPERADMIN_ID` | Yes | — | Superadmin operator_id (e.g. `admin`) |
| `SUPERADMIN_PASS_HASH` | Yes (prod) | — | Bcrypt hash. Generate via `python -m backend.scripts.hash_pw <pw>` |
| `SUPERADMIN_PASS` | Dev only | — | Plaintext password (auto-hashed at startup, logs warning) |
| `ALLOW_REGISTER` | No | `false` | Public self-registration toggle |
| `LOGIN_LOCKOUT_AFTER` | No | `5` | Failed logins before lockout |
| `LOGIN_LOCKOUT_MIN` | No | `15` | Lockout window minutes |
| **File security** | | | |
| `FILE_SIGN_SECRET` | Yes (prod) | falls back to `JWT_SECRET` | HMAC key for signed `/file` URLs (5-min TTL) |
| **LLM safety** | | | |
| `LLM_CALL_TIMEOUT_S` | No | `60` | Per-call timeout |
| `LLM_DAILY_CAP_USD` | No | `50` | Per-tenant daily $ cap |
| **AI matching behavior** | | | |
| `MATCH_ON_CV_UPLOAD` | No | `false` | If `true`, every new CV scans all open positions (slow + costly). Default `false`: matching only runs on position create / JD update / manual rescan. |
| `JD_BG_INTERVAL_S` | No | `60` | JD background poll interval (seconds). Lowered from `300` since real-time LISTEN/NOTIFY listener (`backend/agents/jd_enrich_listener.py`) handles enrichment within 3-5s of insert/update; poll is now safety net only. |
| **Ops** | | | |
| `APP_VERSION` | No | `1.0.0` | Surfaced on `/api/health` |

## Security & Production Hardening

Beta-readiness fixes (M2):

| Area | Mechanism |
|---|---|
| **Auth** | JWT HS256 (`/api/auth/login`), bcrypt cost-12, 8h expiry, lockout after 5 fails for 15min |
| **Superadmin** | Env-driven (`SUPERADMIN_ID` + `SUPERADMIN_PASS_HASH`), bootstrapped on startup |
| **Self-register** | Disabled by default (`ALLOW_REGISTER=false`); superadmin Bearer required for elevated roles |
| **File auth** | HMAC-signed `/file?sig=…&exp=…` URLs (5-min TTL) via `/file/sign`. Legacy `?token=` accepted with deprecation warning |
| **CORS** | Env `ALLOWED_ORIGINS` list, no wildcard. Logged at startup |
| **Rate limit** | slowapi: `RATE_LIMIT=600/minute` global (env-tunable), 5/min upload + login + register, 30/min LLM endpoints |
| **Concurrency** | 4 uvicorn workers, DB pool 5..20, OCR `Semaphore(2)`, LLM `Semaphore(8)` per worker — comfortable ~10 parallel users. Tune via `WORKERS` / `OCR_CONCURRENCY` / `LLM_MAX_CONCURRENT` |
| **Burmese OCR** | Full Myanmar block (Burmese / Shan / Mon / Karen / Kayah / Pa'O), Unicode + Zawgyi (auto-converted via `myanmartools` + ICU `Zawgyi-my`) |
| **Image enhancement** | `enhance_image_for_ocr` — auto-upscale low-res scans (LANCZOS, target ≥2000px) + sharpen + contrast + brightness. Skipped when already crisp. Vision-handwritten path uses original (preserves stroke). Tunable via `OCR_UPSCALE_MIN_PX` / `OCR_UPSCALE_MAX_PX` |
| **Billing dashboard** | `/billing` (admin/superadmin only). Per-job · per-model · per-step LLM cost ledger from `llm_call_log` table. Range filters (today/7d/30d/MTD), hourly burn chart, drill-down per CV job, CSV export, 30s auto-refresh, daily $ cap progress bar |
| **Feature flags** | `system_flags` table; superadmin toggles nav items (POSITIONS / JDS / CV REPO / ANALYTICS / INTERVIEWS / POOLS / HR BRAIN) from `/admin` → SYSTEM tab. **Defaults: Interviews + Pools OFF** |
| **Upload guard** | 20MB cap + MIME whitelist (pdf/docx/doc/txt/png/jpg) |
| **XSS** | All `{@html}` sinks escape-first (LLM output + note rendering) |
| **LLM safety** | Per-call 60s timeout, daily $ cap (`LLM_DAILY_CAP_USD`), structured JSON logs `{ts,tenant,model,latency,tokens,cost,status}` |
| **Pipeline isolation** | Step 13 AI_SUMMARY failure does not break upload (`ai_summary_status` column) |
| **Report.docx** | `run_in_executor` + 30s timeout + 50KB field truncate + StreamingResponse |
| **Health** | `/api/health` returns `db`, `disk`, `llm` IDs, `version`, `uptime` |
| **Trace cap** | `pipeline_trace` pruned to 50 rows per candidate |
| **Chat v2 (Agno agent, flag-gated)** | `AGENT_V2=true` opts in; 11 tools (CV/position/brain/funnel/email), per-role allowlist (recruiter ✗ `update_brain`, analyst ✗ `draft_email`), PII redact (national_id/dob/phone/email) on tool traces, pgvector memory recall (top-K=5), per-session $ cap (`AGENT_SESSION_CAP_USD`), CI eval gate (30 golden cases, mean ≥4.0), full cost ledger via `llm_call_log step='agent'`. Rollback: `AGENT_V2=false` + recreate api → legacy keyword chat |
| **Redis cache** | `REDIS_URL` env; `embed_cache` 24h TTL (query embeddings for agent memory recall), `tool_cache` 60s TTL (agent tool-result dedup). Graceful in-memory fallback if Redis down |

⚠️ Open items before GA: HttpOnly cookie auth (currently localStorage JWT — XSS-stealable), MFA, password reset, audit log retention policy.

## Testing

```bash
python3 -m pytest tests/ -v
# 27 tests: auth, scoring, CV parser
```

## Backup

```bash
./scripts/backup.sh
# Saves to data/backups/hire_YYYYMMDD_HHMMSS.sql
# Keeps last 7 backups
```

## Stats

| Metric | Count |
|---|---|
| Python LOC | 11,142 |
| Svelte LOC | 13,400+ |
| CSS LOC | 852 |
| Total LOC | ~25,500 |
| API Endpoints | 165+ |
| DB Tables | 44 |
| Frontend Pages | 11 |
| Components | 7 |
| Tests | 27 |

## Troubleshooting

### `effect_update_depth_exceeded` (page stuck loading)

Svelte 5 effect loop. Page renders loading indicator forever, console shows
recursive error from minified runtime.

**Cause**: a `$effect` reads reactive state in its sync portion AND writes
to the same state (directly or via a sync helper).

**Fast fix**: wrap the effect body or callee in `untrack`:

```js
import { untrack } from 'svelte';
$effect(() => { if (id) untrack(() => loadStuff()); });
```

**Diagnostic**: enable sourcemaps in `frontend/vite.config.ts`
(`build: { sourcemap: true, minify: false }`), then add a per-effect
counter that warns past 50 firings:

```js
let _dbg = (typeof window !== 'undefined') && (window.__hireFx = window.__hireFx || {});
function _t(l) { if (!_dbg) return; _dbg[l] = (_dbg[l]||0)+1;
  if (_dbg[l] > 50) console.warn('[fx-loop]', l, _dbg[l]); }
$effect(() => { _t('fx_main'); /* ... */ });
```

Rebuild + reload. First label warning = looper. Inspect for read-then-write
pattern in the effect body or its sync callees. See `CLAUDE.md` for full guide.

### Profile page stuck on second navigation

SvelteKit reuses `[id]` route component when only the param changes — state
persists across `/candidates/9` → `/candidates/8`. Reset per-record state at
the top of the loader before the fetch:
`candidate = null; *Loaded = false; activeTab = 'profile';`

## License

Private — CityAI Project.

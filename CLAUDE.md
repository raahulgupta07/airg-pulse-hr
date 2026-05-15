# PULSE — Org Heartbeat (formerly HIRE)

**P**eople · **U**pdates · **L**ifecycle · **S**ourcing · **E**ngagement

Unified org platform: AI hiring + internal comms + job posting + broadcast/ads + candidate matching + HR Brain chatbot.

**Repo**: `raahulgupta07/airg-pulse-hr` (GitHub) · **License**: Proprietary — All Rights Reserved (see `LICENSE`). Source visibility does NOT grant any license. Commercial/partnership: raahulgupta07apple3@gmail.com.

> **Agent quick-start:** see [`AGENTS.md`](./AGENTS.md) (orientation, hard rules, file map) + [`ARCHITECTURE.md`](./ARCHITECTURE.md) (data flows, topology). This file = full reference.

## 2026-05-15 — Zero-config deploy (engineer can't break the boot)

**Goal**: engineer pulls repo, edits 4 lines in `.env`, runs `docker compose up -d --build`, logs in. Nothing else.

### Install (manual, the way engineers actually do it)
```bash
git clone https://github.com/raahulgupta07/airg-pulse-hr.git
cd airg-pulse-hr
cp .env.example .env
nano .env       # set OPENROUTER_API_KEY, SUPERADMIN_ID, SUPERADMIN_PASS, PORT
docker compose up -d --build
# wait ~60s
curl http://localhost:8090/api/health
# open http://<host>:<PORT>, log in with SUPERADMIN_ID / SUPERADMIN_PASS
```

### Install (interactive alternative)
```bash
./setup.sh      # prompts for 4 values, writes .env, builds, boots
```

### Upgrade flow
```bash
./scripts/pre_upgrade.sh                     # snapshot DB + files
git pull origin main
docker compose up -d --build
curl -s http://localhost:8090/api/health | jq '{status, migrations}'
```
Migrations auto-run on boot under `pg_advisory_lock(13371337)`. Health endpoint returns 503 until migrations clear, so ALB / reverse proxy holds traffic.

Rollback: `git reset --hard <sha> && docker compose up -d --build`. Restore dump if a destructive migration ran (`scripts/restore.sh`).

### Hardening that makes the above bulletproof

**1. `backend/core/jwt_auth.py` — auto-managed JWT secret**
- `_secret()` reads `JWT_SECRET` env. Rejects bogus values (empty, `change-me`, `secret`, `none`, <32 chars, <6 unique chars) and falls back to auto-gen.
- `_autogen_secret()` writes random 64-hex to first writable path in `[/data/.jwt_secret, /var/lib/pulse/.jwt_secret, /tmp/.pulse_jwt_secret]`. In-memory last resort.
- Cached per-process so each call returns the same value. `reset_cache()` exposed for tests.

**2. `backend/routes/auth.py::bootstrap_superadmin` — defaults + auto-unlock**
- `SUPERADMIN_ID` default = `pulse_admin`. `SUPERADMIN_PASS` default = `admin` (logs rotation warning).
- UPSERT runs every boot. `ON CONFLICT DO UPDATE` sets `pass_hash = EXCLUDED.pass_hash, role='superadmin', failed_login_count=0, locked_until=NULL`. So any lockout from prior 5-fail attempts clears on `docker compose restart api`.

**3. `backend/main.py` — CSRF + CORS tolerance**
- CSRF middleware skips `/api/auth/*` (login has no session yet — CSRF inapplicable) and `/api/careers/*` (public).
- Missing `Origin` header → allow (curl, server-to-server).
- Same-host auto-allow: `urlparse(origin).netloc` matches `Host` or `X-Forwarded-Host` → pass without env tweak.
- CORS: adds `allow_origin_regex=^https?://[^/]+$` (env `ALLOWED_ORIGIN_REGEX`). With `allow_credentials=True`, Starlette echoes back the matched origin (no `*` exposure). Bearer auth — not cookies — so credentials flag is mostly cosmetic.

**4. `compose.yaml` — safe defaults, optional .env**
- `OPENROUTER_API_KEY` no longer required at boot (`${OPENROUTER_API_KEY:-}` instead of `:?` mandatory). AI features check `bool(OPENROUTER_API_KEY and not placeholder)` and log "LLM call skipped" without crashing.
- `env_file: [{path: .env, required: false}]` — boot succeeds even with no `.env`.
- Service `environment:` block sets `SUPERADMIN_ID=pulse_admin`, `SUPERADMIN_PASS=admin`, `DEV_MODE=false`, `WORKERS=1`, `OCR_CONCURRENCY=1`, `RATE_LIMIT=600/minute`, `ALLOWED_ORIGIN_REGEX=^https?://[^/]+$$` as fallbacks (the `:-` operator preserves any `.env` override).
- Backup sidecar also gets `env_file: required: false`.

**5. `scripts/entrypoint.sh` — filesystem prep**
- `mkdir -p /data /data/cvs /data/screenshots /data/uploads /data/exports /data/brain_uploads` + `chmod -R u+rwX` on every boot.
- DB-ready loop capped at 120s (was infinite). Proceeds anyway if exceeded — app retries.
- Default `WORKERS=1` (was 2). Matches single-worker queue assumption.

**6. `.env.example` rewritten**
- 4 values in REQUIRED block at top: `OPENROUTER_API_KEY`, `SUPERADMIN_ID`, `SUPERADMIN_PASS`, `PORT`.
- All other settings commented with default hints. Engineer never sees `DB_PASS`, `JWT_SECRET`, model overrides, CORS regex, etc unless they go looking.

**7. `setup.sh` (new)**
- Interactive prompts (4 inputs), auto-generates strong `DB_PASS` + `JWT_SECRET` via `openssl rand`, writes `.env` 0600, builds, boots, polls health, prints login URL.
- Re-run-safe: detects existing `.env`, prompts overwrite, backs up to `.env.bak.YYYYMMDD_HHMMSS`.

### Smoke-tested locally
```
cp .env.example .env   (no edits)
docker compose up -d --build
→ 4 containers healthy
→ POST /api/auth/login {pulse_admin / admin} = 200 OK + JWT
→ POST /api/auth/login w/ arbitrary Origin = 200 OK (CSRF/CORS pass)
→ 0 errors in logs (3 expected warnings: auto-gen JWT, default password, verifier model alias)
```

### Failure-mode coverage (what previously broke the engineer, now self-heals)
| Engineer mistake | Old result | New result |
|---|---|---|
| Forgets `OPENROUTER_API_KEY` | Compose refuses to start (`:?` mandatory) | App boots, AI off, CV pipeline still works |
| Forgets `JWT_SECRET` | App crashes at boot (`RuntimeError`) | Auto-gen, persisted to `/data/.jwt_secret` |
| Uses `change-me` JWT secret | Boots with weak secret | Detected, ignored, auto-gen used |
| Forgets `SUPERADMIN_PASS_HASH` | Bootstrap silently skips → 401 on login | Defaults to plaintext `admin`, bcrypted at boot |
| 5 failed logins → lockout | Permanent until manual SQL UPDATE | Cleared on next `docker compose restart api` |
| Deploys behind public domain | 403 CSRF "Origin not allowed" | Same-host auto-allow, no env tweak |
| Skips `.env` entirely | `OPENROUTER_API_KEY:?` aborts compose | Boots clean with all defaults |
| Forgets to chmod `/data` | `[startup] writable=False` | Entrypoint auto-mkdir + chmod |
| Wrong port already in use | `bind: address already in use` | Doc'd in Troubleshooting — `PORT=8091` in `.env` |

### Files added/modified
- New: `setup.sh` (interactive installer, ~150 LOC)
- Modified: `backend/core/jwt_auth.py` (+89 LOC — auto-gen + validation), `backend/main.py` (+30 LOC — CSRF/CORS), `backend/routes/auth.py` (defaults), `compose.yaml` (optional env_file + safe defaults), `scripts/entrypoint.sh` (mkdir + chmod), `.env.example` (rewrite — 4-field top, rest commented)
- Updated: `README.md` (Path A rewritten — manual + interactive, upgrade flow, operations, troubleshooting table)

### Git
- Commit `e63278b` on `origin/main`. 7 files, +417/-112.

## 2026-05-14 (deploy) — GitHub push + proprietary LICENSE + bulk delete

### Git init + first push
- `git init -b main` in repo root. `git remote add origin git@github.com:raahulgupta07/airg-pulse-hr.git`. Pushed `main`.
- 400 files, 98,644 lines initial commit. Co-authored Claude Opus 4.7.
- Repo currently **public**. Switch to private via `gh repo edit raahulgupta07/airg-pulse-hr --visibility private` if needed.

### `.gitignore` hardening (pre-push)
Added beyond original list:
- `.env.*` (except `.env.example`) — was only `.env.local`
- `data/` (full dir, was only `data/cvs|screenshots|exports|uploads`) — covers any new subdirs
- `backups/` — pg_dump snapshots contain PII
- `pgdata/` — Postgres data dir
- `*.pem`, `*.key`, `*.crt`, `secrets/` — TLS material
- `*.log`, `logs/` — app logs may contain user input/PII
- `.pytest_cache/`, `.coverage`, `htmlcov/`
- `*.pyo`, `*.pyd`, `.mypy_cache/`, `.ruff_cache/`
- `TODO.local`, `NOTES.local`, `*.local.md` — dev scratchpads
- `bench/*.xlsx` — vision bench data may include test CVs

### Pre-push secret scan
- Scanned all 400 staged files for: `sk-or-v1-*` (OpenRouter), `JWT_SECRET=[a-f0-9]{40,}` (live JWT), `SUPERADMIN_PASS_HASH=$2[abxy]$` (bcrypt), live admin password `e5JfjjKIqYgprMQ1`, live JWT secret `4c48c822...bae11`.
- Result: **clean**. Only placeholder `$2b$12$...` in CLAUDE.md (false positive).
- `.env`, `backups/pre-deploy-2026-05-14.sql`, `pgdata/` all confirmed NOT staged.

### `LICENSE` — proprietary custom
- Copyright 2026 Rahul Gupta, All Rights Reserved.
- Explicit prohibitions: use, copy, modify, distribute, sublicense, lease, sell, reverse-engineer, decompile, ML training, removing notices.
- Permitted: view-for-evaluation, factual references in commentary.
- Third-party OSS deps keep their own licenses (FastAPI, SvelteKit, etc).
- Standard NO WARRANTY + liability cap clauses.
- GitHub will show "Other" license badge (no SPDX match).

### Bulk delete (CV + JD repos)
**Backend** (`backend/routes/bulk.py`):
- `POST /api/bulk/delete-candidates` — admin+, max 200 ids/call, hard DELETE FROM candidates, FK cascade triggers, best-effort `pdf_path` file unlink. Returns `{deleted, total}`.
- `POST /api/bulk/delete-jds` — admin+, max 200 ids/call, hard DELETE FROM jd_repository, FK cascade.
- Note: `require_role()` takes single role arg; both endpoints gate on `"admin"` (which `has_min_role` accepts superadmin too via role hierarchy).

**Frontend CV repo** (`routes/candidates/+page.svelte`):
- Bug fix: table-header `<th>` checkbox handler ignored `compareMode` — header click did nothing when compare mode active. Now branches: in compare mode toggles `compareIds` (capped at 5); else toggles `selectedIds` for all visible rows.
- Bulk toolbar in select-all bar gained: `Delete N` (coral danger button) + `Clear` button. Confirm dialog before delete. Optimistic local filter then await + reload.
- New `bulkDeleteCandidates()` fn calls new bulk endpoint.

**Frontend JD repo** (`routes/jds/+page.svelte`):
- `jdBulkDelete()` rewired: was N parallel `DELETE /jds/{id}?hard=true` (slow + per-row creator check could 403 mid-batch). Now single `/bulk/delete-jds` call with optimistic remove. Returns `r.deleted` count.

### Files added/modified
- New: `LICENSE`, hardened `.gitignore`
- Backend: `routes/bulk.py` (+2 endpoints, ~50 LOC)
- Frontend: `routes/candidates/+page.svelte` (toolbar + handler fixes), `routes/jds/+page.svelte` (delete rewire)

### Image
- `hub-hr-agent-api:latest` rebaked with bulk delete endpoints. Container restarted clean.

## 2026-05-14 — Stage-aligned candidates + 8 new agents + expiry/audit + agent config

### Candidates table — pipeline-aligned tabs + per-row stage setter
- Tab strip rebuilt to mirror Pipeline kanban 1:1: `ALL · AI · UPLOADED · SCREENED · SHORTLISTED · OFFERED · HIRED · REJECTED`. Each tab maps directly to its kanban column (same labels, same warm color palette, same order). Counts derived from filtered candidates per stage.
- `STAGE` column dropped; stage selector folded into `STAGE / ACTIONS` column (220px wide). Per-row `<select>` writes stage via `/bulk/move-stage` (single-id call). Score column shrunk 2fr → 1.3fr to free space.
- AI suggestions (`attachment_state='suggested'`) render `[+]` promote / `[×]` dismiss buttons instead of stage select (no stage until promoted).
- `<select>` uses per-option `selected={...}` + `{#key c.stage + cid}` wrapper to defeat Svelte 5 DOM-cache bug where browser retained user's prior dropdown choice across re-renders.
- `{#each filtered as c (c.candidate_id || c.id)}` keyed — rows tracked by ID, no DOM reuse leaking state across reloads.
- `aiSuggestions` loaded separately from `/positions/{slug}/ai` (since backend `get_position_candidates` excludes `attachment_state='suggested'`). Passed as second prop to `CandidatesTable`.

### Bulk endpoints — attachment_state sync
- `/bulk/move-stage` now writes `attachment_state` ('rejected' if stage=rejected, 'attached' otherwise) + `dismissed` flag. Re-promote from rejected via dropdown works correctly. Matches `/ai/{cid}/reject` semantics.
- `/bulk/reject` sets `attachment_state='rejected'` + `dismissed=TRUE` + `stage='rejected'`. Audit-consistent with single-row AI reject endpoint.
- Fixes data-corruption class where bulk operations left attachment_state stale, causing rejected candidates to still appear in non-AI tab filters.

### 8 new background agents (16 total now in `agents/registry.py`)

**JD agents (mig 057)**
- **`jd-bias`** (`backend/agents/jd_bias_detector.py`) — 30 min loop. LITE_MODEL JSON classifier flags gendered/ageist/ableist phrases. Stores `jd_repository.bias_report JSONB`. Emits `jd_bias` PULSE FEED notif when flagged.
- **`jd-refresh`** (`backend/agents/jd_refresher.py`) — 6h loop. Joins `jd_repository` ↔ `positions.weights_source_jd_id` filtered by `lifecycle_stage NOT IN ('filled','archived')`. Emits `jd_stale` (7-day dedupe) for JDs `updated_at < NOW() - JD_REFRESH_DAYS` (default 60).
- **`jd-translator`** (`backend/agents/jd_translator.py`) — 30 min loop. Picks JDs with non-empty `translate_to TEXT[]` (e.g. `['my','th','id']`). Per (jd, lang) calls LITE_MODEL → upserts `jd_translations(jd_id, lang, body)`. Idempotent: skips when translation timestamp ≥ jd.updated_at.
- **`jd-completeness`** (`backend/agents/jd_completeness.py`) — 24h nightly. Heuristic 0–100: title +20, min_exp +15, required_skills≥3 +20, seniority +15, dept +10, jd_text>500 +10, location +10. Writes `completeness_score`. Notif `jd_incomplete` when <50.

**Brain/Copilot agents (mig 058)**
- **`brain-trainer`** (`backend/agents/brain_trainer.py`) — 6h loop. Reads `chat_messages`, regex pre-filter + LITE_MODEL classifies low-confidence/fallback assistant responses. Inserts `brain_unanswered(question, session_id, asked_at, addressed)`. Admin notif.
- **`doc-ingestor`** (`backend/agents/doc_ingestor.py`) — 5 min loop. Watches `org_brain_uploads(file_path, status)`. Parses PDF (cv_parser/pypdf) / DOCX (python-docx) / TXT, chunks at 500 chars w/ 50 overlap, embeds via `embed_text`, inserts into `org_brain(chunk_text, embedding vector(1536))` (HNSW indexed). Marks status=done/error.
- **`qa-suggester`** (`backend/agents/qa_suggester.py`) — 1 min loop. Reads `qa_suggestion_queue(candidate_id, position_id, fulfilled)`. Builds candidate+position brief, asks LITE_MODEL for 3 short interview questions (JSON array). Stores in `suggestions JSONB` column. Frontend writes to queue when recruiter opens drawer.
- **`faq-builder`** (`backend/agents/faq_builder.py`) — 24h nightly. Pulls 30d `chat_messages` user msgs, embeds, greedy clusters at cosine ≥ 0.85. Clusters ≥3 → LITE_MODEL canonicalize → INSERT into `faq_entries(question, answer, cluster_size, last_built_at)`. Full refresh truncate+insert.

**Endpoints added** (`backend/routes/brain.py` — 3 routers):
- `POST /api/admin/brain/upload` (admin+, multipart, ≤25MB, .pdf/.docx/.doc/.txt)
- `GET /api/admin/brain/unanswered` (admin+)
- `POST /api/admin/brain/unanswered/{id}/address` (admin+)
- `GET /api/admin/brain/uploads` (admin+) — diagnostic
- `POST /api/qa/queue` (recruiter+) — body `{candidate_id, position_id}`
- `GET /api/qa/{candidate_id}/{position_id}` (recruiter+)
- `GET /api/faq/` (any auth)

### Agent config UI (mig 059)
- New `agent_configs(agent_id PK, enabled BOOLEAN, interval_seconds INT, thresholds JSONB, updated_at, updated_by_id)` table. Idempotent seed for all 16 agent_ids.
- `backend/agents/registry.py` extended: `RUN_ONCE` map + `register_run_once()` + 10s-cached `is_enabled(agent_id)` helper. Agents poll DB at start of each cycle for early-exit when disabled.
- New endpoints in `backend/routes/agents.py`:
  - `GET /api/agents/config` — joins registry + db + runtime snapshot
  - `PATCH /api/agents/config/{agent_id}` (admin+) — validates 60-86400s interval
  - `POST /api/agents/{agent_id}/test-run` (admin+) — fires single cycle out-of-schedule via `RUN_ONCE` callable. 501 if not registered. 120s timeout.
- `frontend/src/lib/admin/AgentsConfigPanel.svelte` — 3-col responsive grid. Per-card: status dot, enable switch (instant PATCH + revert on fail), interval slider 60-86400 + numeric mirror, thresholds JSON textarea, Last/Next/Errors strip, [Test run now] (spinner + 501 toast), [Save] (turns coral when dirty). Auto-refresh 8s, edit buffer keyed by agent_id.
- Mounted as `Agent Config` tab in `/admin`.

### Expiry + audit (mig 055, 056)
- `candidates` + `jd_repository` extended: `expires_at TIMESTAMPTZ` (default `created_at + 90d`), `created_by_id INT FK users`, `updated_by_id INT FK users`, `updated_at TIMESTAMPTZ`. Backfill from legacy `owner_id`/`created_by`/`updated_by`. Index on `expires_at`.
- `app_settings('expiry_defaults', '{"cv_days":90,"jd_days":90}'::jsonb)` seeded. Configurable.
- New `backend/core/expiry.py` — `get_default_expiry_days(kind)`, `get_retention_settings()`, `set_retention_settings(...)`.
- INSERT paths stamped: `database.py::insert_candidate`, `jd_repo.py::create_jd/generate_jd/duplicate_jd`, `agents/ingest.py::_route_jd`. UPDATE paths stamped: `candidates.py::update_candidate`, `jd_repo.py::update_jd/update_jd_body`.
- SELECT in CV/JD list endpoints returns `created_by_name`, `updated_by_name`, `expires_at`, `is_expired` (bool), `days_until_expiry` (int).
- New endpoints: `GET /api/admin/retention`, `POST /api/admin/retention` (validates 1–3650 days, audit-logged).
- `frontend/src/lib/admin/RetentionPanel.svelte` — two number inputs + Save. Mounted as `Retention` tab in `/admin`.
- CV repo + JD repo lists: new columns `Added by · Updated by · Expires`. Chip styling: red `Expired`, amber `<14d`, neutral otherwise.
- **Constraint**: chip is purely visual — does NOT block edits, does NOT exclude from AI scan. Soft signal only (per design choice).

### Pool tab fully removed from CandidatesTable (~100 LOC dead code remains harmless)
- TABS array dropped pool entry. Pool browse access only via top-right `[ATTACH FROM TALENT POOL]` button. Inline pool render branches in CandidatesTable retained but unreachable (loadPool/poolItems/attachedIds shared with parent's pool-browse modal — removal risks coupling break).

### Migration roll
- 055 expiry_audit · 056 retention_settings · 057 jd_agents · 058 brain_agents · 059 agent_configs

### Pre-deploy hardening pass (post-launch of 8 new agents)

**Backend agent gating + dynamic interval**
- `backend/agents/registry.py` extended with `get_interval(agent_id, default_s)` (10s TTL cache, reads `agent_configs.interval_seconds`) and `invalidate_interval_cache(agent_id)`. Admin slider now actually changes cadence.
- All 8 new agent loops (`jd_bias_detector`, `jd_refresher`, `jd_translator`, `jd_completeness`, `brain_trainer`, `doc_ingestor`, `qa_suggester`, `faq_builder`) injected with early-exit gate at top of `while True:`:
  ```python
  if not is_enabled(AGENT_ID):
      heartbeat(AGENT_ID, status="disabled", action="off")
      await asyncio.sleep(60)
      continue
  ```
- Sleep at loop tail rewritten: `await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))`. Disabling an agent in admin UI now silences it within 70s; interval changes propagate within 10s.
- `PATCH /api/agents/config/{agent_id}` invalidates BOTH `enabled` + `interval` caches on write.

**Per-agent LLM cost cap**
- `registry.py` adds `get_llm_daily_cap(agent_id, default=5.0)` (reads `agent_configs.thresholds.llm_daily_cap_usd`, falls back to env `AGENT_LLM_DAILY_CAP_USD`) + `check_agent_cost_cap(agent_id)` returning `(within_cap, spent_today, cap)`. Falls open on DB error.
- Sums `llm_call_log` rows tagged `step=f"agent:{agent_id}"` since `CURRENT_DATE`. Agents can call before each LLM hit and skip cycle if over cap.

**Brain upload hardening**
- `backend/routes/brain.py::brain_upload`: filename now `secrets.token_urlsafe(16)` (was `uuid.uuid4().hex`). Resolved abspath verified to stay within `BRAIN_UPLOAD_DIR` (defense-in-depth path-traversal guard) — raises 400 on escape.

**Rate limit on test-run**
- `POST /api/agents/{agent_id}/test-run` now `@limiter.limit("10/minute")` — prevents admin spam triggering parallel out-of-schedule cycles.

**Pool dead code cleanup**
- ~100 LOC removed from `frontend/src/lib/candidates-table/CandidatesTable.svelte`:
  - `TAB_HELP.pool` entry deleted
  - `{#if activeTab === 'pool' && !poolBrowsed}` empty-state block deleted
  - `{:else if activeTab === 'pool'}` pool picker block (~80 LOC of pool table render) deleted
  - Outer `{:else}` wrapper around main TABLE collapsed
- Helper fns retained (`loadPool`, `poolItems`, `attachedIds`, `browseTalentPool`, `poolFiltered`, `poolAttachIds`, `poolToggle`, `poolToggleAll`, `poolAttachSelected`) — still consumed by parent's "ATTACH FROM TALENT POOL" modal trigger.

**Image rebuild + DB backup**
- `pg_dump` snapshot taken: `backups/pre-deploy-2026-05-14.sql` (7.1MB, 9844 lines) — pre-deploy rollback point.
- `docker compose build api` baked all 8 agents + brain routes + agent config UI + retention panel + expiry helpers into `hub-hr-agent-api:latest`. Container recreated cleanly (0 errors, 1 warning on verifier model name).
- Migrations 055-059 verified recorded in `_migrations` on fresh boot.

**Smoke verified**
- Login → JWT issued, 16 agents listed via `/api/agents/`, retention endpoint returns `{cv_days:90, jd_days:90}`, FAQ endpoint returns `{items:[], count:0}`, PATCH config writes + persists.
- Toggle smoke: `PATCH /api/agents/config/jd-bias {enabled:false}` → DB row updated → next cycle gate fires (within ~70s with current 1800s loop).

**Skipped (deferred to post-staging)**
- Smoke test files (background test agent stalled twice; covered via curl instead)
- HttpOnly cookie auth, MFA, password reset (pre-existing GA-list items, not new today)

### Files added/modified summary
- 8 new agent files in `backend/agents/`
- New `backend/routes/brain.py` (~300 LOC, 3 routers)
- New `backend/core/expiry.py`
- Extended `backend/agents/registry.py` (8 → 16 agents + RUN_ONCE map + is_enabled helper)
- Extended `backend/routes/agents.py` (config + test-run endpoints)
- Extended `backend/routes/admin.py` (retention endpoints)
- Extended `backend/routes/bulk.py` (attachment_state sync)
- 2 new admin panels: `AgentsConfigPanel.svelte`, `RetentionPanel.svelte`
- `CandidatesTable.svelte` rebuilt: keyed each, stage select per row, pipeline-aligned tabs
- `+page.svelte` (positions/[slug]): aiSuggestions parallel-load + prop pass-through
- 5 new SQL migrations

## 2026-05-13 (late) — Claude warm theme + white-label + 30 UX features

### Theme migration (brutalist → Claude warm)
- `frontend/src/app.css` rewritten (1134 LOC). Tokens: `--color-bg #faf9f5`, `--color-accent #c96342` (coral/clay), `--color-border #e8e6dd`, 1px hairlines, 12px radius, soft shadows. Font: Inter body + Tiempos Headline serif. Brutalist backup preserved at `app.css.brutalist-backup`.
- Layout, login, positions home, JD repo, CV repo, analytics, admin, billing all reskinned. Sentence-case throughout (was uppercase). 22 pages/components updated via parallel agents.
- Login = Claude.ai-style split: left brand + hero ("Hire smart, communicate better") + auth card (SSO + LDAP + email, no Google), right = animated cursor tour over 6 feature tiles (Ingest CVs / Match candidates / Draft article / Generate image / Broadcast email / Use template) with 3 floating bubbles staggered.
- Density pass: body 14.5px → 13.5px, table 13px → 12px, line-height 1.55 → 1.5. Hero typography preserved.

### White-label admin panel
- `lib/branding.ts` — reactive `brandingStore`, `getBranding()`, `loadBrandingFromAPI()`, `applyBranding(b)` derives `--color-accent` + `-ink` + `-soft` + `-bg` shades via HSL math.
- `routes/admin/branding/+page.svelte` (panel, inlined in admin tabs) — app name, logo upload (PNG/SVG, 256KB cap, base64 data URL), accent color picker (live preview), footer text.
- Backend `app_settings` table (mig 046) + `POST/GET /api/admin/branding` in `routes/admin.py`. GET is public (login page needs custom logo before auth). Validates hex regex `^#[0-9a-fA-F]{6}$`, logo MIME, accent.
- Default: "City Agent Pulse" / coral / "Org Heartbeat". Layout + login hydrate brand on mount + apply CSS vars.
- All "Pulse" wordmarks renamed to "City Agent Pulse" across 13 visible strings in 10 files. Component names (PulseFeed, PulseToast) + localStorage keys (pulse_*) + window events (pulse-toast etc) preserved.

### 30 UX features shipped via 10+ parallel agents

| Feature | Where | Notes |
|---|---|---|
| ⌘K command palette | `lib/CommandPalette.svelte` | spotlight modal, fuzzy match across nav/positions/CVs/actions, ↑↓ Enter Tab Esc, mounted in layout |
| ? shortcut overlay | `lib/KeyboardHelp.svelte` | press `?` to see all shortcuts |
| j/k row navigation | tables (CV repo, JD repo, candidates-table) | j down k up Enter open x dismiss |
| Skeleton + EmptyState + ErrorBanner | `lib/Skeleton.svelte`, `EmptyState.svelte`, ~~ErrorBanner~~ removed | shimmer skeletons applied to home/CV/JD; empty-states with icon + CTA. ErrorBanner deleted — was triggering false-positive "Can't reach server" too often |
| Avatar dropdown + Profile + Notif prefs + Change password | `routes/profile/*`, layout patched | Profile / Notification preferences / API keys / Help / Logout dropdown. Backend `POST /api/auth/change-password` + `GET/POST /api/users/me/notifications` (mig 049 adds `users.notification_prefs JSONB`). |
| Mobile responsive | layout + CV repo + drawer | <900px hamburger drawer, <768px CV repo card list, full-screen modals |
| Onboarding tour | `lib/OnboardingTour.svelte` | 4-step spotlight on first auth'd visit, `localStorage.pulse_onboarded` |
| "Sample data" button | home empty state | tries POST /api/demo/seed, alert fallback |
| What's new modal | `lib/WhatsNew.svelte` | once-per-version, reads /api/health.version |
| Hire celebration confetti | `lib/Confetti.svelte` | fires on `pulse-celebrate` window event when candidate dropped into Hired column |
| Page transitions | layout `{#key path}` with `fade` 120ms | subtle |
| Hover preview cards | `lib/HoverPreview.svelte` | 600ms hover candidate name → mini profile card lazy-fetch + cache |
| Smart defaults | localStorage persistence | `pulse_cv_filters`, `pulse_jd_filters`, `pulse_pos_tab_{slug}` |
| Print stylesheet | `app.css` `@media print` | hides chrome, full-width content, Tiempos serif |
| A11y | `app.css` `:focus-visible` 2px coral outline, skip-link in layout | |
| Drag-drop overlay | candidates page | drop PDF/DOCX anywhere triggers upload |
| Undo bar | `lib/UndoBar.svelte` | bottom toast on destructive ops (5s window), restores via `pulse-undo` event |
| Recent + saved searches | candidates/jds | localStorage `pulse_recent_*` / `pulse_saved_*`, ↑↓ Enter |
| Bulk actions extended | JDs + positions | floating bottom action bar w/ confirm modal |
| Visual workflow builder | admin Workflows tab | trigger → condition → action 3-stage modal. Backend `POST/GET/PUT/DELETE /api/automations` + mig 048 (additive on legacy `automation_rules`). Frontend localStorage fallback. |
| @mentions in candidate notes | `routes/candidates/[id]/+page.svelte` | `@user` regex → coral chip pill, fetches `/api/auth/users` |
| Comment threads | candidate notes | reply button → parent_id POST (falls back to flat indent) |
| Presence indicators | `lib/Presence.svelte` | avatar bubbles top of position workspace + candidate detail (mock — real-time backend stub) |
| Activity feed | `lib/ActivityFeed.svelte` | reusable, fetches `/api/{type}s/{id}/activity`, mounted in candidate + position pages |
| Email templates editor | admin Email templates tab | merge tags `{{candidate.name}}`, preview, 4 seed templates. Backend `templates.py` + mig 047. |
| Offer templates editor | admin Offer templates tab | markdown editor + 2 seed templates. Same backend file. |
| Schedule interview panel | `lib/SchedulePanel.svelte` | datetime-local + duration + interviewers + .ics fallback when backend missing |
| Analytics depth | Source ROI / Predictive / Comparative tabs | warm ECharts palette (coral/amber/sage), fallback mock when backend missing |
| AI Nudges merged into PULSE FEED | `lib/PulseFeed.svelte` | new `✨ Nudges` tab inside bell dropdown (no separate floating panel). 3 nudge types (top-match, stuck-screening, stale-JD), dismissals in `pulse_dismissed_nudges` |
| Careers status lookup | `routes/careers/+page.svelte` | email-input → `/api/careers/status?email=` (stub fallback) |
| GDPR export + delete | admin Audit tab + new backend `routes/gdpr.py` | `GET /api/users/{id}/gdpr-export` composes data from users + candidates + notifications + positions + audit_log + candidate_notes. `DELETE /api/users/{id}?gdpr=true` scrubs PII columns (email, operator_id, display_name, avatar_url, department, password_hash). Audit logged. |
| Slack/Teams/GCal/Outlook/DocuSign/LinkedIn integrations marketplace | admin Integrations tab + backend `app_settings` | webhook URL storage, test POST on connect, CORS-tolerant status |

### Admin shell consolidation
- 5 sub-route pages (`/admin/branding`, `/admin/email-templates`, `/admin/offer-templates`, `/admin/integrations`, `/admin/workflows`) extracted to `lib/admin/{Branding,EmailTemplates,OfferTemplates,Integrations,Workflows}Panel.svelte`.
- Rendered inline in `/admin/+page.svelte` via `{#if tab === 'X'} <Panel /> {/if}` — single-page experience.
- URL param `?tab=branding` deep-links work, `replaceState` (no history pollution). Old routes redirect to `/admin?tab=X`.

### Backend fixes / endpoints added
- **Mig 045** `cv_content_hash TEXT` on `candidates` + partial index on active rows. Pre-pipeline SHA-256 dedup in `_route_cv` (`agents/ingest.py`) + `bulk-upload` route. Skip pipeline + return existing cv_id on hit. Orange toast in UI.
- **Mig 046** `app_settings(key TEXT PK, value JSONB, updated_at, updated_by FK users)` — branding + integrations storage.
- **Mig 047** `email_templates` + `offer_templates` w/ 4+2 seed rows.
- **Mig 048** `automation_rules` extended w/ `trigger/condition/action/enabled` (additive on legacy schema).
- **Mig 049** `users.notification_prefs JSONB DEFAULT '{}'`.
- New routes: `routes/templates.py` (email + offer), `routes/automations.py` (workflows CRUD), `routes/gdpr.py` (export + scrub), `routes/admin.py` extended w/ branding + integrations, `routes/auth.py` extended w/ `users_router` (notifications) + `change-password`. Analytics `/funnel` alias delegating to `pipeline_funnel`.
- Smart `/api/*` 404/307 fallback in `serve_frontend` (`main.py:597+`) — if no-slash path doesn't exist but slash variant does, 307 redirect. Unknown paths return clean 404. Replaces blanket 307 that broke `fetch()` callers + SSE.
- `redirect_slashes=False` on FastAPI app — prevents SSE EventSource breakage (no follow on 307).
- `RATE_LIMIT=off` in `.env` → resolves to 1000000/min (effectively unlimited). Per-route caps still active (login 5/min, upload 5/min, LLM 30/min). Health endpoint never rate-limited.
- `/api/health` exempt from rate limit + added `@limiter.exempt` decorator.

### Performance fixes
- **AI_SUMMARY (Step 13)** model swapped from `CHAT_MODEL` (gemini-3-flash, $0.30/$2.50) → `LITE_MODEL` (gemini-3.1-flash-lite, $0.10/$0.40) via `SUMMARY_MODEL` env var. **~6x cheaper** per CV. Quality plenty for 200-word exec brief.
- **Svelte 5 `$effect` infinite-loop audit** — fixed 30+ bugs across 22 files where `$effect(() => { loadX() })` triggered re-runs because `loadX` mutated reactive state read by the effect. Pattern fixed via `onMount` (mount-only) or `untrack(() => loadX())` (dep-tracked but no retrigger). Pages were showing endless skeleton/loading state before this fix.

### Docker / deploy
- Bind-mount added: `./frontend/build:/app/static-frontend:ro` in `compose.yaml`. Frontend changes via `npm run build` survive container recreate. Backend changes still need `docker cp` or image rebuild.
- Docker Desktop bind-mount sync bug encountered: `frontend/build/` cleared + rebuilt can leave container seeing empty dir. Fix: `docker restart pulse-api` re-syncs.

### Login fixes
- Animated right-side canvas: 6 tiles + black SVG cursor hopping every 12s + 3 floating chat bubbles staggered (user prompt / sent confirmation / attachment chip).
- SSO (SAML/OIDC) + LDAP/AD buttons added (currently stub `alert()`).
- Google login removed per request.
- Terms/Privacy line removed.

## 2026-05-13 — Interview Kit (per-position, generic + per-candidate tailored)

New tab on position page: `Interview Kit`. Generates audience-specific interview questions per role, optionally tailored to a specific AI-matched candidate using their match gaps + strengths.

### Backend
- **Migration `db/migrations/044_interview_kits.sql`** — `interview_questions` table:
  - `audience` ∈ HR_BP / HIRING_MGR / PANEL / TECH
  - `category` ∈ BEHAVIORAL / TECHNICAL / CULTURE / ROLE_SPECIFIC / GAP_PROBE / STRENGTH_VERIFY
  - `stage` ∈ SCREEN / TECH / ONSITE / FINAL
  - `look_for TEXT[]`, `red_flags TEXT[]`, `source` ∈ ai_generic / ai_tailored / manual, `used` flag
  - Indexes: `(position_id, candidate_id, audience, stage)` + partial `position_id WHERE candidate_id IS NULL`
- **Agent `backend/agents/interview_kit_gen.py`** — two functions, both LITE_MODEL (~$0.0005/batch):
  - `generate_generic(title, jd_text, audience, stage, count)` — bank of role-level questions
  - `generate_tailored(title, jd_text, candidate, match, audience, stage, count)` — uses match gaps + strengths + composite score + match_explanation; categories weighted toward GAP_PROBE / STRENGTH_VERIFY
  - Per-audience prompt focus (HR_BP=motivation/culture, HIRING_MGR=ownership, PANEL=cross-functional, TECH=deep technical) + per-stage depth tuning
- **Routes `backend/routes/interview_kit.py`** — registered under `/api`:
  - `GET /positions/{slug}/interview-kit?candidate_id=&audience=&stage=` — list + group by category (generic merges in when candidate filter set)
  - `POST /positions/{slug}/interview-kit/generate` (recruiter+, 10/min) — body `{candidate_id?, audience, stage, count}` → LLM gen + INSERT batch
  - `PATCH /interview-kit/{qid}` (recruiter+) — edit question/look_for/red_flags/category/audience/stage
  - `DELETE /interview-kit/{qid}` (recruiter+)
  - `POST /interview-kit/{qid}/used` (recruiter+) — mark used
  - `GET /positions/{slug}/interview-kit/export.md` — markdown handoff (sections per category, look_for + red_flags inline)

### Frontend
- **`frontend/src/lib/interview-kit/InterviewKit.svelte`** (~430 LOC) — toolbar (candidate dropdown=Generic + top-12 AI matches w/ score, audience pills, stage select, count), grouped sections by category, `QuestionCard`s w/ inline edit, [COPY] [EDIT] [✓ USED] [x REMOVE], context strip showing `Position · Audience · Stage · Tailor-target`. Brutalist style (#feffd6/#383832, 2/4px borders).
- **Position page (`+page.svelte`)** — added `Interview Kit` tab (icon=quiz) between Dashboard and Settings; renders `<InterviewKit {slug} {position} />`.

### Tests
- **`tests/test_interview_kit.py`** — 10 tests: list empty, list with seed, audience filter, stage filter, edit, mark used, delete (+404 on re-delete), export.md, bad-audience reject, position 404, generate-generic (LLM-gated skip).

### Smoke test (live)
- Created `AI Software Engineer` position (slug `ai-software-engineer`, id 37) with full JD + skills/weights
- Uploaded CV `Aisha Zaw` (6yr senior AI engineer, id 12) → pipeline OK
- AI rescan: 7 scored, 4 matched. Aisha #1 at **71%**.
- Generated 4 generic HR_BP/SCREEN + 4 tailored TECH/TECH for Aisha. Tailored hit GAP_PROBE on LLM pre-training, STRENGTH_VERIFY on pgvector multi-tenant.

## 2026-05-12 — Pipeline parallelism + CLI terminal + JD background agent

### Pipeline performance — true 8-way parallel
- **Root cause of serial behavior**: `llm_call` + `_embed_text_sync` + `extract_structured_data` were sync, blocked event loop. asyncio.gather couldn't parallelize.
- **Fix**: wrapped all sync calls in `backend/core/cv_pipeline.py` with `asyncio.to_thread`:
  - `extract_structured_data`, `enrich_candidate`, `generate_qa_pairs`, `compute_quality_score`, `llm_call` (AI_SUMMARY step)
  - HYPE_EMBED and CONTEXT_EMBED embeddings now via `asyncio.gather(*[embed_text(q) for q in qa_pairs])` — actually parallel
- **`embed_text`**: now `await _aio.to_thread(_embed_text_sync, text)` in `backend/core/config.py` (was async-fn-with-sync-body)
- **Speed wins**:
  - Default embedding switched from `text-embedding-3-large` → `text-embedding-3-small` (1536 dims, faster, cheaper)
  - `STRUCTURE_MODEL = os.getenv("STRUCTURE_MODEL", LITE_MODEL)` in `cv_extractor.py` (was CHAT_MODEL = Gemini-3-Flash; LITE_MODEL faster for JSON extraction)
- **MAX_PARALLEL_PIPELINES queue worker** in `backend/routes/candidates.py`:
  - Module-level `_pipeline_queue`, `_queue_running`, `_queue_worker()`, `_ensure_queue_workers()`
  - `bulk_process` enqueues — returns instantly `{started, count, skipped, queue_depth}` (no blocking)
  - `force: bool = False` param: RUN ALL = `force=true` (re-runs done CVs); RUN PENDING = `force=false`
  - `_active_tasks` dict tracks asyncio.Tasks for cancellation; `_track()` registers + adds done callback
- **WORKERS=1 in .env** — 4 uvicorn workers had separate in-memory `_active_tasks` dicts, cancel couldn't find tasks. Single worker = state cohesion.

### Bulk CV upload + UI controls
- **Merged Upload buttons** — single `Upload CV(s)` button triggers `#cv-upload` multi-select OS file picker (1 or many)
- **Bulk upload endpoint**: 50-file cap, sync email dedup
- **CV REPO row controls**:
  - Per-row: `▶ RUN`, `■ STOP`, `→ PROFILE`, `↻ RETRY`, `✗ DISMISS`
  - Bulk: `RUN ALL` (force=true), `RUN PENDING ONLY` (force=false), `STOP ALL` (clears queue + cancels active tasks)
  - Optimistic `activeTraces[cid]='starting'` on click → button disables instantly
  - 409 on `/run` → auto-retry `/reprocess`
- **Queue visibility**:
  - `GET /candidates/queue-status` returns `{running, queued, queue_depth, queue_positions}` = `_queue_running ∪ alive(_active_tasks)`
  - Frontend polls 1.5s, shows RUNNING NOW banner with cv chips → click scrollToRow + row-flash animation
  - Queue-running rows pinned to top of table
  - Per-row badge: `RUNNING` or `QUEUED #N`
- **`is_processed` + `processing_error` added** to `/candidates` SELECT — fixed bug where done CVs still showed RUN button (JS `c.is_processed === true` was false for undefined)
- **Auto-prune dismissed IDs** within 1h `created_at` cutoff — fixed empty CV REPO after DB nuke (`RESTART IDENTITY` recycled IDs that matched localStorage-dismissed entries)

### Pipeline CLI terminal (`frontend/src/lib/PipelineTerminal.svelte`)
- Bottom-dock CLI, Claude-style. Lines with type: `info`/`success`/`error`/`warn`/`complete`
- **Default collapsed**, auto-expands when `stats.running > 0` (unless userToggled flag)
- **`pollStats`** (1.2s) hits `/candidates/pending` for top-bar counters + announces `🎉 PIPELINE COMPLETE` (green gradient bg + green border) on transition to done
- **`pollEvents`** hits `/pipeline-events?since_id=N` with cursor = `max(0, lastEventId - 14)` for status-transition visibility
- **Dedup via `seenIds` Set** keyed by `${id}:${status}` (not just id — status transitions matter)
- **Backend `/pipeline-events`**: monotonic `id` cursor + `last_step` / `last_status` in latest_run JSON
  - Bug fix: `max_id = rows[-1]["id"] if rows else int(db_max)` (was `max(since_id, db_max)` which returned 999999999 when probe used that value → no events)
- **Progress bar per row**: poll-driven from pipeline_trace `status='running'/'done'` counts (most steps <100ms so bar jumps in batches at 1.2s poll)

### Compare CVs — AI summary + Excel export (`backend/routes/matching.py`)
- `/compare` — `position_slug` now optional; `_generate_open_comparison()` LLM fn for position-less compares
- **AI Executive Summary** panel above compare table (green gradient bg) — regen via `/matching/compare` refresh
- **`GET /matching/compare/export.xlsx?ids=`** — openpyxl Workbook, 2 sheets: `Comparison` + `AI Summary`
- Frontend uses `api()` helper (`authHeaders` auto-injected) — fixed 401 from missing `getToken` import

### DOCX inline viewer (`frontend/src/lib/DocViewer.svelte`)
- **mammoth.js dynamic import** — DOCX → HTML client-side via `mammoth.convertToHtml({arrayBuffer: buf})`
- Both PDF + DOCX scrollable inside viewer pane:
  - Outer: `height: calc(100vh - 140px); overflow: hidden`
  - Inner: `flex: 1 1 auto; min-height: 0; overflow-y: auto`
  - PDF iframe: `height: 100%; flex: 1 1 auto`
- Global styles for `.docx-render h1/h2/h3/p/ul/table`

### JD Background Agent (`backend/agents/jd_background.py` — NEW)
- Runs every `JD_BG_INTERVAL_S` (default 300s = 5 min)
- **Fills MISSING fields only — does NOT rewrite jd_text**
- For each JD missing fields: extracts `required_skills`, `department`, `seniority_level`, `certifications`, `min_experience_years` — UPDATE only when field empty (`COALESCE(field,'')=''` / `cardinality=0` guards)
- KF4D competencies via `_internal_extract_jd_competencies` from `jd_repo.py`
- **STATE dict** + **EVENTS ring buffer (200 cap)** + `_emit(kind, msg, level)` for activity log
- Lifecycle: `idle → scanning → sleeping` with `next_run_at` timestamp
- Startup delay: 20s sleep before first cycle
- Per-JD sleep: 0.3s between to avoid LLM bursts
- Started on app boot via `asyncio.create_task(jd_background_loop())` in `backend/main.py`
- **`GET /api/jd-background/status?since_id=N&event_limit=50`** — returns `{state, events, max_id, interval_s, batch_size}`

### JD Agent Robot badge (`frontend/src/lib/JdAgentBadge.svelte` — NEW)
- **Placed in top nav header — replaces `ORG HEARTBEAT` text** (per user request)
- Collapsed pill: `🤖 [dot] JD AGENT · STATUS [count]` with green border + bob animation when active
- Expanded panel (`position: fixed; top: 56px; right: 200px`): status / current_action / last_run / next_scan countdown / total processed / last cycle summary / recent activity feed (last 12 events)
- **Mirrors all events to CLI terminal** via `window.dispatchEvent(new CustomEvent('hire-cli', {detail}))`
- Polls `/api/jd-background/status` every 4s with `since_id` cursor; tick interval 1s for countdown

### Auth + login fixes
- **Login black screen** — login page `:global(html), :global(body)` styles persisted after navigation. Fixed: gated with `:global(body.login-active)` class, removed on unmount
- **Login 401** — frontend was sending BOTH `operator_id+access_key` AND `email+password` shapes; backend tried email path first → 401. Fixed: send only one shape based on whether operatorId contains `@`
- **`bootstrap_superadmin`** — added `gen_public_id("users")` call (was failing on NULL public_id)
- **Credentials reset**: `pulse_admin` / `admin` — generated new bcrypt, updated DB row + `.env SUPERADMIN_PASS_HASH`

### Delete modal fixes
- **CSS `text-transform: uppercase`** made input look uppercase but value wasn't — removed
- **Accept either position name OR `DELETE` literal** (case-insensitive)
- **Position card removal** — added keyed `{#each positions as pos (pos.slug)}` + optimistic local filter before reload (was requiring page refresh)

### Health endpoint
- Moved from `/health` → `/api/health` (consistency with rest of API)

### Deployment lesson
- **Never `docker compose up --force-recreate`** — wiped backend image without rebuild → "site can't be reached". Use `docker cp` for file syncs + `docker restart pulse-api` only.

### Test fixtures generated
- 50 test JDs (`.docx`) + 110 test CVs (`.docx`) for pipeline load testing — based on HSE Manager seed

### Position AI Tab — auto-match on position create

- **Trigger model**: matches CVs to position ONLY when position is created (or JD updated, or manual rescan). NOT on every CV upload (gated behind `MATCH_ON_CV_UPLOAD=false`, default off).
- **New table** `position_ai_scans` (mig 041): tracks each scan's lifecycle (queued→running→done/error) with `started_at`, `finished_at`, `n_scored`, `n_matched`, `error`. Partial unique index `uniq_pas_active` (mig 042) prevents parallel scans on same position.
- **`position_candidates.match_source`** (mig 041): tracks origin of each match — `manual` / `auto_scan_on_create` / `auto_scan_on_jd_update` / `auto_scan_rescan` / `ai_promoted`.
- **Per-step n_scored UPDATE**: `auto_scan_for_position` writes counter every 5 candidates so SSE stream shows live progress, not just done jump.
- **Dedupe**: `_create_ai_scan_row` catches `UniqueViolation` on `uniq_pas_active`, returns existing active scan id. `POST /ai/rescan` pre-checks for active scan, returns `{scan_id, status:in_progress, dedup:true}` instead of creating duplicate.
- **CV pipeline Step 12 gate**: `MATCH_ON_CV_UPLOAD=false` skips `_auto_match_candidate`. Logs `pipeline.step.auto_match.skipped reason=match_on_cv_upload_disabled`. Flip to `true` to restore per-CV scanning.

**New endpoints** (`backend/routes/positions.py`):
- `GET /api/positions/{slug}/ai` — returns `{position, scan, matches[]}` (top 20, sorted by composite score desc, with full 7-dim breakdown).
- `POST /api/positions/{slug}/ai/rescan` (hiring_manager+) — re-launches scan, returns `{scan_id, status}`.
- `GET /api/positions/{slug}/ai/events` — SSE stream of scan progress (1s tick, closes on done/error or 5min idle). Accepts auth via `?token=` query param (EventSource has no header support).
- `POST /api/positions/{slug}/ai/{cid}/promote` (recruiter+) — sets stage='screened', match_source='ai_promoted'.
- `POST /api/positions/{slug}/ai/{cid}/reject` (recruiter+) — sets dismissed=true, stage='rejected'.

**Frontend** (`frontend/src/lib/PositionAITab.svelte`, `+page.svelte`):
- New 8th tab `AI` (icon `auto_awesome`) in position workspace, between Candidates and Pipeline.
- Component uses EventSource SSE primary, 2s-poll fallback on error.
- Brutalist match list: ranked rows, score chip with color (green ≥70, orange ≥40, red <40), 7-dim breakdown bars, strengths/gaps chips, ADD TO PIPELINE / REJECT actions with optimistic UI.

**Auth shim** (`backend/core/auth.py:189-196`): added `?token=` query-param fallback to `get_current_user` for SSE endpoints (EventSource header limitation).

**Bug fixed**: `c.years_experience` → `c.total_experience_years` in `/api/positions/{slug}/ai` SQL (matches array was silently empty).

**DB additions**: `position_ai_scans` table (mig 041) + `position_candidates.match_source` column (mig 041) + partial unique index `uniq_pas_active` (mig 042).

### Position AI Tab — round 2 (unified UX + drawer + feed)

**CANDIDATES tab unified — standalone AI tab removed**
- Position page tabs reduced 7 → 6 (no `AI` tab). CANDIDATES tab now stacks two sections:
  - **AI MATCH** (full `<PositionAITab>` at top, self-labeled). Empty state: `SCANNED N CVS — NO NEW MATCHES` + sub-line "All above-threshold candidates already shortlisted, or none scored above X%".
  - **SHORTLISTED CVS** below — header `SHORTLISTED CVS · N TOTAL · M AI · K MANUAL`. Pill `✨ AI` (green) or `MANUAL` derived from `match_source IN (ai_promoted, auto_scan_*)` OR `auto_added=true` OR legacy `added_by` values.
- AI MATCH SQL filter: `AND COALESCE(pc.stage, 'uploaded') = 'uploaded'` — promoted candidates auto-disappear from AI MATCH list.

**SCAN REPO button rewired**
- Old `/matching/scan/{slug}` endpoint dropped from button. Now calls `POST /api/positions/{slug}/ai/rescan` (single scan path = `auto_scan_for_position`, writes scan row + auto-attach).
- Pre-flight blocks if no JD on position: alert "Add JD to position first to run AI scan".
- Old "AI SCAN: N candidates above X% threshold" inline panel deleted.

**MatchRow redesigned**
- Compact grid `28px 32px 56px 1fr 140px` (checkbox · rank · score chip · info · actions).
- 6-bar inline breakdown: SKILLS / EXP / EDU / CERT / IND / CULTURE.
- Score chip color from `position.min_match_score` (green ≥ min, orange ≥ min×0.6, red below).
- Pill `✨ AI` / `MANUAL`. Tooltip on score chip shows `match_explanation` + strengths/gaps.
- **Bug fixes**: `match.score` → `match.match_score_composite` (was 0% always); built `breakdown` locally from flat `match_score_*` fields (no `match.breakdown` object exists); SQL `c.years_experience` → `c.total_experience_years` in `/positions/{slug}/ai`.

**CandidateDrawer (NEW — `frontend/src/lib/CandidateDrawer.svelte` ~480 LOC)**
- Slide-in 600px right-side drawer. Triggered from AI MATCH, SHORTLISTED, and PIPELINE kanban rows.
- Header: name · role · yrs · company · AI/MANUAL pill · MATCH score pill · `[OPEN CV PDF]` (signed URL → new tab) · `[VIEW FULL PAGE]`.
- 6 tabs: PROFILE / SKILLS / EXPERIENCE / SCORE / DOCS / PIPELINE.
- DOCS lazy-loads + probes signed URL; 404 → "CV FILE NOT AVAILABLE" + re-upload link.
- PIPELINE tab uses `/api/candidates/{id}/ai-recommendations`.
- SCORE tab (positionContext only): 7-dim breakdown bars + composite chip + `match_explanation`.
- SUMMARY field renders markdown via `mdLite` (escape-first; **bold** / ## H3 / ### H4 / - bullets / paragraphs).
- ESC + outside click + body scroll lock. Brutalist style. Replaces legacy kanban small drawer (legacy code retained but unreached).

**PULSE FEED — unified notifications widget (NEW — `frontend/src/lib/PulseFeed.svelte` ~402 LOC)**
- Replaces both bell notifications and `JdAgentBadge` in top nav.
- Single button `[🔔 PULSE FEED · N]` w/ red dot if unread. Dropdown tabs ALL / NOTIF / JD / AI with per-type counts.
- Real-time SSE via `GET /api/feed/events?token=...`, auto-reconnect 5s on error, cap 100 events. Mark-read + mark-all-read.
- **Backend NEW** `backend/routes/feed.py` (~390 LOC):
  - `GET /api/feed?limit=N` → `{events, unread_count, by_type}`
  - `GET /api/feed/events` SSE (2s poll, `: ping` every 25s, 30min cap)
  - `POST /api/feed/mark-read {ids}` + `POST /api/feed/mark-all-read`
  - Aggregates 4 sources: `notifications` table, `position_ai_scans` (24h), `position_candidates` (24h, AI source), `jd_background.STATE`.

**Candidate detail page additions**
- New `GET /api/candidates/{id}/ai-recommendations` (`backend/routes/candidate_extras.py:149-176`) — returns positions where candidate is AI-matched.
- PROFILE tab now shows AI-matches summary block; new 9th tab `AI MATCHES [N]` w/ count badge.
- Component `frontend/src/lib/CandidateAIMatches.svelte` (compact + full modes).

**Bug fix — JD attach from repo never triggered scan**
- `backend/routes/jd_repo.py:794-823` — `use_jd_for_position` now copies `jd_text`, calls `_extract_and_embed_jd`, then launches `auto_scan_for_position` with `match_source='auto_scan_on_jd_update'`.
- `/positions/{slug}/ai` response now includes `position.has_jd` + `weights_source_jd_id`.

**Bulk-promote endpoint**
- `POST /api/positions/{slug}/ai/bulk-promote {candidate_ids:[...]}` (cap 50). Single transaction. Audit-logged with `source: ai_bulk_promote`.

**Scan/match infra additions**
- Periodic stale-sweeper: 5-min loop in `backend/main.py:200-213` marks queued/running scans older than 10min as `error/stale_on_restart`.
- Rate limits: `/ai/rescan` 5/min, `/ai/bulk-promote` 10/min, `/ai/{cid}/promote` 30/min, `/ai/{cid}/reject` 30/min.
- Audit log on promote/reject via `candidate_activity` table.
- Signed URL for SSE: new `GET /ai/events/sign` returns `{url, exp, ttl_s:300}`. SSE accepts `?sig=&exp=&uid=`. Legacy `?token=` accepted with deprecation warn.
- Swagger annotations on all 7 AI endpoints.
- Observability: JSON log lines `scan.started`, `match.added`, `scan.completed` (w/ `duration_ms`), `scan.error`.

**Tests** — 6 new files: `tests/test_ai_promote_reject.py`, `test_position_create_no_jd.py`, `test_match_source_field.py`, `test_bulk_promote.py`, `test_sse_keepalive.py`, `test_stale_sweeper.py`. Pass individually; bulk run hits 5/min login rate limit.

**Infra**
- New `redis` service in `compose.yaml` (was missing). `pulse-redis` healthy. `[cache] Redis connected` log on boot.
- `REDIS_URL=redis://redis:6379/0` added to `.env`.
- Volume `hire-data` named → `./data:/data` bind-mount (host-visible, backup-ready).
- Image rebuilt clean. `agentos>=0.5` removed from requirements (not on PyPI).
- Migration 042 applied: partial unique index `uniq_pas_active` on `position_ai_scans(position_id) WHERE status IN ('queued','running')` for dedupe deadlock prevention.

**Pre-launch hardening**
- `DEV_MODE=false`. `JWT_SECRET` + `FILE_SIGN_SECRET` rotated. `pulse_admin` password rotated (16-char random). `MATCH_ON_CV_UPLOAD=false` set explicit. DocViewer 404 fallback wired in CandidateDrawer.

### JD real-time enrichment (no AI Enhance needed)

**Goal**: fill empty JD structured fields (department, seniority, min_exp, required_skills, nice_to_have_skills) within seconds of insert/update — without rewriting `jd_text` or requiring user click.

**Backend — manual endpoint** (`backend/routes/jd_repo.py`):
- `POST /api/jds/{jd_id}/enrich?force=false` — owner/admin gated. Calls `_extract_requirements(jd_text)` (single Gemini Flash Lite call, ~$0.0003).
- Default fills only empty cols (`COALESCE`/`cardinality=0` guards); `force=true` overwrites all 5 fields.
- Does NOT touch `jd_text` (unlike `/enhance`).
- Returns `{updated: [cols], fields: {...}, extracted: {...}}`.

**Real-time listener — LISTEN/NOTIFY** (`db/migrations/043_jd_enrich_trigger.sql`):
- PL/pgSQL fn `notify_jd_needs_enrich()` emits `pg_notify('jd_enrich_needed', NEW.id::text)` when any of the 5 fields is null/empty AND `length(jd_text) > 50`.
- Trigger `trg_jd_needs_enrich` fires AFTER INSERT OR UPDATE OF the 5 cols + `jd_text` ON `jd_repository`.
- One-shot DO block backfills NOTIFY for up to 500 existing incomplete rows on migrate.

**Worker** (`backend/agents/jd_enrich_listener.py` — NEW):
- Dedicated psycopg async conn, **autocommit** — LISTEN needs persistent connection, can't share pool.
- `LISTEN jd_enrich_needed` → in-mem dedupe set + `asyncio.Queue` + `Semaphore(2)` consumer pool.
- On notify: pulls jd_id, calls `_extract_requirements`, UPDATEs only empty cols (same logic as `/enrich` endpoint).
- 5s reconnect backoff on conn loss.
- INSERTs `notifications` row (`type='jd_enriched'`) → live in **PULSE FEED**.
- Mirrors events to `jd_background.EVENTS` ring buffer.
- Started in `backend/main.py` startup alongside `_stale_sweeper_loop` + `jd_background_loop`.
- **Latency**: 3-5s end-to-end (INSERT → enriched fields visible).

**Fallback poll preserved**:
- 5-min `jd_background_loop` kept as safety net.
- `JD_BG_INTERVAL_S=300 → 60` (catches any missed NOTIFY within 1 min).

**Status endpoint extended**:
- `GET /api/jd-background/status` now returns `listener: {listener_connected, queue_depth, processed_count, last_enrich_at, last_jd_id, last_fields}` alongside existing poll state.

**Frontend** (`frontend/src/routes/jds/[id]/+page.svelte`):
- New green `[ ✦ ENRICH FIELDS ]` button next to existing `[ ✦ AI ENHANCE ]` on JD detail page.
- Click → `enrichFields()` async fn → `POST /api/jds/{id}/enrich` → reload row.

**ENRICH vs AI ENHANCE**:
- ENRICH: department, seniority, min_exp, required_skills, nice_to_have_skills. **No jd_text change.**
- AI ENHANCE: rewrites entire jd_text + scores DEI/legal/completeness + extracts skills.

**Cost**: ~$0.0003/JD (Gemini 3.1 Flash Lite, ~1200 tokens out). 50 JDs ≈ $0.015.

---

## 2026-05-11 — MVP readiness pass

### Removed
- **Interviews feature** — route `backend/routes/interviews.py`, frontend `/interviews/` dir, kanban stages `interview_scheduled`/`interviewed`, candidate `Interviews` tab, AI Scorecard Pre-fill, Position-page AI Questions modal + Interviews KPI tile + Interview stages settings, `feature_interviews` flag. DB tables `interviews` + `interview_scorecards` → **dropped + replaced with empty SQL views** so legacy analytics/scorecard SQL in `analytics.py`/`analytics_v2.py`/`export.py`/`emails.py`/`candidates.py`/`evaluation.py` still parses (returns zero rows).
- **Pools feature** — route `backend/routes/pools.py`, frontend `/pools/` dir, nav entry, `feature_pools` flag, `add_to_pool` automation action, DB tables `candidate_pools` + `pool_members`. **Kept** `scope=pool` param in `/candidates` route (separate concept = org-wide CV view).

### Added / reworked
- **JD Generate flow** — `POST /jds/generate?preview=true` returns text + extracted skills **without DB write**. Frontend shows preview pane (rendered markdown + DEI/completeness scores), user clicks **✓ Save to JD Pool** → `POST /jds/` persists.
- **JD Paste modal** — separate from Generate. 2 actions:
  - `Save As-Is` → POST /jds/ saves raw text, backend auto-extracts skills/years/cert/dept/seniority via `_extract_requirements`
  - `✨ AI Enhance & Save` → POST /jds/ → POST /jds/{id}/enhance?preview=true → user reviews enhanced text in preview pane → ✓ Save → PATCH /jds/{id}/body commits enhanced text
- **Markdown renderer** for JD preview (`renderJdMarkdown()` in `jds/+page.svelte`): H1/H2/H3 with green section dividers, pipe tables with cell borders, `**bold**`, `- bullets`. XSS-safe (escapes entities first). Toggle Rendered ↔ Edit Markdown.
- **KF4D auto-extract on JD save** — wired `_internal_extract_jd_competencies()` into all 3 JD-write paths: `POST /jds/`, `POST /jds/generate`, `POST /jds/{id}/enhance`. Failure isolated (try/except).
- **Public ID prefixes** (mig 039) — `cv_`/`jd_`/`pos_`/`usr_`/`sec_` ULID Crockford base32 26-char. `backend/core/ids.py` exports `gen_public_id(table)`, `resolve_id(db, table, ref)`, `resolve_id_sync()`. Dual int/public_id resolution (mig 039 ran on 49 rows; 46 handlers patched).
- **JD semantic search** (mig 040) — `jd_embedding vector(1536)` + HNSW cosine index + `jd_embed_hash TEXT` (SHA-256 dedup). New endpoints: `POST /jds/embeddings/backfill` (admin), `GET /jds/search/semantic?q=...&limit=N`. Auto-embed via `asyncio.create_task(_safe(_embed_jd(...)))` in `backend/agents/ingest.py` after JD INSERT.
- **Embedding cascade** — OpenAI-only: `text-embedding-3-large` (primary, dim 3072→1536 via `encoding_format="float"`), 3-large (retry), 3-small (fallback). Gemini-2-preview **removed** (rate-limit flaky on free tier).
- **Hard-delete with double-confirm modal** — CV, JD, Position. Red modal + type-`DELETE` text input. Role-gated:
  - CV: `owner_id == user_id` OR `role='superadmin'` → 403 else
  - JD: `created_by == user_id` OR `role='superadmin'` → 403 else
  - Position: `hiring_manager_id == user_id` OR `role IN ('admin','superadmin')` → 403 else
  Endpoints: `DELETE /candidates/{id}?hard=true`, `DELETE /jds/{id}?hard=true`, `DELETE /positions/{slug}?hard=true`. Default (no `?hard=true`) = soft archive.
- **CV repo layout** — title + subtitle + buttons moved INSIDE body (right of rail) to match JD pattern. Removed standalone `.cv-header` block + border-bottom CSS.
- **Compare mode persistence** — `compareIds` + `compareMode` persist to localStorage (`pulse_compare_ids`, `pulse_compare_mode`) so selections survive nav.
- **Source badges on position page** — `✨ AI` / `👤 MANUAL` chips on candidate cards + filter chips (all / ai / manual). New cols on `position_candidates`: `auto_added BOOLEAN`, `added_by TEXT`. `add_candidate_to_position()` sets `auto_added = added_by IN ('ai_scan','auto_match','ai_auto')`.
- **AI scan filter** — `scan_repo_for_position` excludes `id IN (SELECT candidate_id FROM position_candidates WHERE position_id=$1)`. Returns `all_attached: True` when nothing to scan.
- **Kanban auto-sizing** — removed `min-height`, added `align-items: flex-start` + sticky stage headers + `max-height: calc(100vh-260px)`.
- **Match-score blend** — `0.8 * current + 0.2 * semantic` (was 1.0 current). Jaccard tokenization + substring matching + domain synonyms (HSE/EHS/EOSH/OSH) in `_skill_match()`.
- **JD hydration fallback** — `_hydrate_position_from_jd()` copies JD `required_skills` into position when position table empty (avoids degenerate 69.5 ties).
- **Role extractor** — tightened LLM prompt forbidding hiring-decision tokens (hire/yes/no/n/a). Sanitizer in `enrich_candidate()` falls back to `experience[0].role` when blocklist hit. Fixes `current_role="hire"` bug.
- **Stage rollback** — kanban now: `uploaded · screened · shortlisted · offered · hired · rejected`.
- **JD share global** — `is_admin` now includes `superadmin` role in `jd_repo.py:1454`.
- **Trailing-slash fix** — frontend uses `/jds/` and `/positions/` (FastAPI strict-routing; bare `/jds`/`/positions` returns 405).
- **Auto scope=mine after JD save** — new JDs default `visibility=private` (MINE scope). Auto-switch so user sees them immediately.
- **Favicon** — `frontend/static/favicon.svg` green briefcase + apple-touch-icon + theme-color meta.

## Architecture

- **Backend**: FastAPI (Python 3.11) + 165+ API endpoints
- **Frontend**: SvelteKit 5 + Svelte 5 Runes + Tailwind CSS 4.2
- **Database**: PostgreSQL 18 + PgVector (44 tables)
- **LLM**: OpenRouter API (Gemini 3 Flash / GPT-5.4-mini / Gemini Lite)
- **OCR**: Hybrid — PaddleOCR (free, local) + Vision LLM (handwritten only) + Tesseract fallback
- **Deploy**: Docker Compose (2 containers: db + api)
- **Tests**: pytest (27 tests)

## Project Structure

```
HUB-HR-Agent/
├── backend/                          # FastAPI (35 Python files, 11,142 LOC)
│   ├── main.py                       # App entry, middleware, WebSocket, health checks
│   ├── requirements.txt              # Dependencies (FastAPI, PaddleOCR, OpenAI, etc.)
│   ├── core/
│   │   ├── config.py                 # LLM models, 4-model embedding cascade, AI status check
│   │   ├── database.py              # PostgreSQL pool, full CRUD, boolean search
│   │   ├── auth.py                  # JWT-first validate_token + legacy hex fallback, bcrypt, RBAC
│   │   ├── jwt_auth.py              # PyJWT HS256 create/verify (NEW M2)
│   │   ├── cost_cap.py              # Per-tenant daily $ cap on LLM (NEW M2)
│   │   ├── rate_limit.py            # Shared slowapi limiter (NEW M2)
│   │   ├── cv_pipeline.py          # 13-step CV processing pipeline (Step 13 AI_SUMMARY isolated)
│   │   ├── cv_parser.py            # Hybrid OCR (PaddleOCR + Vision LLM + Tesseract)
│   │   ├── cv_extractor.py         # LLM structured extraction, Q&A generation
│   │   ├── cache.py                # In-memory TTL cache + Redis adapter (graceful fallback)
│   │   ├── embed_cache.py          # NEW v2 — Redis-backed embedding cache (24h TTL)
│   │   ├── tool_cache.py           # NEW v2 — agent tool-result cache decorator (60s TTL)
│   │   ├── job_queue.py            # PostgreSQL-backed job queue (no Celery)
│   │   └── migrations.py           # Versioned SQL migration runner
│   ├── agents/                      # NEW v2 — Agno HR agent layer (flag-gated)
│   │   ├── hr_agent.py              # arun() async generator, LLM tool-loop (Agno-shim fallback)
│   │   ├── session.py               # agent_runs row mgmt, $ cap enforcement
│   │   ├── memory.py                # AgnoMemory — pgvector recall + write (agent_memory)
│   │   ├── eval/                    # golden.jsonl (30 cases) + run_eval.py (CI gate avg≥4.0)
│   │   └── providers/               # tool implementations
│   │       ├── candidate_provider.py    # query_cvs, get_candidate_brief, score_cv_vs_position, list_candidate_pipeline
│   │       ├── position_provider.py     # query_positions, get_position_brief, get_pipeline
│   │       ├── brain_provider.py        # query_brain, update_brain (write)
│   │       ├── analytics_provider.py    # query_funnel
│   │       └── email_provider.py        # draft_email
│   ├── scripts/
│   │   └── hash_pw.py               # `python -m backend.scripts.hash_pw <pw>` → bcrypt hash (NEW M2)
│   └── routes/                       # 22 route modules
│       ├── auth.py                   # JWT login/register/me/logout/config + lockout (M2 rewrite)
│       ├── candidates.py            # Upload, search, smart NLP search, LinkedIn/GitHub import
│       ├── candidate_extras.py      # Notes, activity, interviews, scorecards, tags, AI summary
│       ├── positions.py             # CRUD, JD generate/enhance, templates, auto-scan, archive
│       ├── matching.py              # Scan repo, score, compare, rescore, culture scoring, flags
│       ├── evaluation.py            # Rubrics, flags, consensus, votes, stack rank, calibration
│       ├── chat.py                  # HR Brain SSE streaming, sessions, feedback
│       ├── jd_repo.py              # JD repository — create, generate, enhance, duplicate
│       ├── (interviews.py — REMOVED 2026-05-11)
│       ├── screening.py            # Per-position screening questions + knockout
│       ├── offers.py               # Offer CRUD, approval chains, salary suggestion
│       ├── emails.py               # Send, bulk send, compose rejection/offer, sequences
│       ├── analytics.py            # Overview, funnel, time-to-hire, sources, AI insights, SLA
│       ├── notifications.py        # CRUD, unread count
│       ├── bulk.py                 # Bulk move stage, reject, add to position
│       ├── careers.py              # Public career page, apply endpoint (no auth)
│       ├── (pools.py — REMOVED 2026-05-11)
│       ├── duplicates.py           # Duplicate detection, merge
│       ├── saved_searches.py       # Save filters, talent alerts
│       ├── export.py               # CSV export, hiring reports
│       ├── eeo.py                  # Diversity/EEO tracking + aggregate reports
│       ├── automations.py          # Automation rules engine
│       └── billing.py              # NEW M2 — LLM cost ledger dashboard (admin/superadmin only): summary/by-model/by-step/hourly/jobs/top/job-detail/export.csv. Reads `llm_call_log`
├── frontend/                         # SvelteKit 5 (20 Svelte files, 13,400+ LOC)
│   ├── src/
│   │   ├── app.css                   # Brutalist design system (852 LOC)
│   │   ├── app.html                  # HTML template (Space Grotesk + Material Symbols)
│   │   ├── routes/
│   │   │   ├── +layout.svelte        # Header, nav, notifications bell, dark mode, CLI terminal
│   │   │   ├── +page.svelte          # Positions grid with health scores, templates
│   │   │   ├── candidates/+page.svelte  # CV repo — filters, bulk, compare, import
│   │   │   ├── candidates/[id]/+page.svelte  # LinkedIn-style profile (7 tabs)
│   │   │   ├── jds/+page.svelte      # JD repository list
│   │   │   ├── jds/[id]/+page.svelte  # JD detail (full page, two-column)
│   │   │   ├── positions/[slug]/+page.svelte  # Position workspace (7 tabs + AI)
│   │   │   ├── chat/+page.svelte     # HR Brain chat with SSE streaming
│   │   │   ├── analytics/+page.svelte # Dashboard — ECharts, heatmap, Sankey, leaderboard
│   │   │   ├── (interviews/ — REMOVED 2026-05-11)
│   │   │   ├── (pools/ — REMOVED 2026-05-11)
│   │   │   ├── careers/+page.svelte  # Public career page with apply
│   │   │   ├── careers/+layout.svelte # Standalone layout (no auth)
│   │   │   ├── login/+page.svelte    # Brutalist ACCESS_PORTAL login (M2 rewrite)
│   │   │   ├── login/+layout.svelte  # Standalone layout
│   │   │   └── +layout.ts            # Client-side route guard, redirects to /login (NEW M2)
│   │   └── lib/
│   │       ├── auth.ts               # getToken/setToken/me/logout — single source (NEW M2)
│   │       ├── api.ts                 # API helper, re-exports auth helpers
│   │       ├── types.ts              # TypeScript interfaces (18 types)
│   │       ├── Chart.svelte          # ECharts wrapper
│   │       ├── Toast.svelte          # Toast notifications
│   │       ├── Pagination.svelte     # Pagination component
│   │       ├── EmailCompose.svelte   # Email compose modal
│   │       ├── PdfViewer.svelte      # CV page viewer
│   │       ├── DocViewer.svelte      # PDF/PNG/DOCX universal viewer (zoom, download)
│   │       ├── SplitPane.svelte      # Resizable 2-col split with drag handle + localStorage
│   │       ├── PendingFilesTable.svelte  # CV intake queue + bulk run + filter chips
│   │       ├── UploadTracker.svelte  # Per-file parallel upload progress bars (XHR cap 4)
│   │       ├── PipelineCli.svelte    # Singleton bottom-right terminal panel
│   │       ├── PipelineStepper.svelte # Per-run pipeline trace (legacy, available for reuse)
│   │       ├── pipelineEvents.js     # Global event store (ring buffer 500, dedup by run|step|status)
│   │       ├── CompetencyPanel.svelte  # Reusable JD/Position competency editor
│   │       ├── MergeModal.svelte     # Field-level candidate merge review
│   │       └── analytics/
│   │           ├── *.svelte          # 7 V2 dashboards (overview/funnel/time/recruiter/dei/cost/qoh/predictive)
│   │           └── CompetencyDashboard.svelte  # Gap heatmap + interviewer calibration
│   ├── package.json
│   ├── svelte.config.js
│   └── vite.config.ts
├── db/
│   ├── init.sql                      # Full schema (44 tables)
│   └── migrations/                   # Versioned SQL migrations (002_evaluation.sql)
├── tests/                            # pytest (27 tests)
│   ├── test_auth.py
│   ├── test_scoring.py
│   └── test_cv_parser.py
├── scripts/
│   ├── entrypoint.sh                 # Docker entrypoint
│   └── backup.sh                     # pg_dump backup script
├── compose.yaml                      # Docker Compose (2 containers)
├── Dockerfile                        # Multi-stage build
├── instance.yaml                     # Branding, persona, categories
└── .env.example                      # Environment variables
```

## Design System

Brutalist/Industrial/Newspaper aesthetic:
- **Font**: Space Grotesk (all text)
- **Colors**: #feffd6 surface, #383832 ink, #00fc40 CTA, #007518 primary
- **Borders**: Asymmetric ink borders (2px top/left, 4px right/bottom)
- **Shadows**: Hard stamp shadows (4px 4px, no blur)
- **Corners**: Zero border-radius everywhere
- **Labels**: All uppercase, 0.05-0.1em letter spacing
- **Dark mode**: Toggle in header, persisted in localStorage

## Key Concepts

### Central CV Repository
All CVs stored once, processed via 13-step pipeline (12 + Step 2.5 VERIFY):
CLASSIFY → EXTRACT → **VERIFY** (Step 2.5, optional) → SCREENSHOTS → STRUCTURE → ENRICH → SAVE → KNOWLEDGE → HyPE_EMBED → CONTEXT_EMBED → QUALITY → TAG → AUTO_MATCH

**Manual upload flow (default):** files staged via `/api/ingest/?auto_process=false`, listed in **Pending Files** table on CV REPO page. User clicks `▶ RUN` to trigger pipeline, watches **Global CLI Terminal** (bottom-right of CV REPO) stream events live.

**Per-step trace persisted** in `pipeline_trace` table (run_id, step_order, model, status, latency_ms, cost_usd, input/output_tokens). Cost computed from `PRICES` table in cv_pipeline.py for each LLM/embedding call.

### Hybrid OCR (no GPU required)
- Digital PDF → PyMuPDF (FREE)
- Scanned/typed → PaddleOCR (FREE, local)
- Handwritten → Vision LLM Gemini-3-Flash (paid)
- **Step 2.5 VERIFY** → Claude Opus 4.7 second-pass on 5 critical fields (name, dob, phone, national_id, email + 4 demographic) when handwritten/image. Overrides any Flash misreads on digit-precision fields. Configurable via `ENABLE_VISION_VERIFIER=true` + `VISION_VERIFIER_MODEL`.
- Tesseract as final fallback
- Multi-language detection (English, Hindi, Arabic, Chinese, Japanese, Korean, **Burmese (full Myanmar block U+1000–U+109F + Extended-A/B): Burmese / Shan / Mon / Karen / Kayah / Pa'O / Khamti**). Zawgyi → Unicode normalization via `myanmartools` (Google ZawgyiDetector) + ICU `Zawgyi-my` transliterator. PaddleOCR auto-skipped for `lang=my` (no model); routes to Vision LLM instead. Tesseract fallback uses `mya+eng` traineddata pack (installed in Dockerfile).
- **Pre-OCR image enhancement** (`enhance_image_for_ocr` in `cv_parser.py`): EXIF rotate · LANCZOS upscale to ≥2000px if smaller · auto-contrast · UnsharpMask · brightness boost. Skipped when image already ≥2000px AND well-contrasted (std-dev ≥ 55). All OCR routes (Paddle / Vision-structured / Tesseract / language-peek) use enhanced image. Vision-handwritten path still uses original (sharpening can degrade stroke nuance). Free, CPU-only, ~50–200ms per image.

### Demographics Extraction (mig 022)
Vision verifier extracts 9 demographic fields from handwritten/government forms (Myanmar driver license, etc.):
- `dob`, `national_id` (e.g. NRC), `gender`, `marital_status`, `nationality`, `religion`, `height`, `weight`, `father_name`
- All stored as text (format-tolerant) on `candidates` table
- Surfaced on candidate profile **DEMOGRAPHICS** section with `✓ verified` badges

### Position Projects
Each position is a workspace with: JD (create/generate/attach from repo), scoring weights, candidate pipeline (drag-drop kanban), dashboard, chat.
When JD is saved, AI auto-scans central repo and recommends top matches.
When CV is uploaded, AI auto-matches against all open positions.

### CV-JD Matching Engine
Weighted composite scoring across **7 dimensions**: skills, experience, industry, education, certifications, culture, **competencies** (KF4D framework, mig 019).
Weight inheritance chain: tenant → sector → JD → position w/ JD lock support. Per-dimension score bars, match explanations, side-by-side comparison.

### Competency Layer (KF4D — Korn Ferry 4 Dimensions)
- 12 seeded competencies (strategic-thinking, decision-making, technical-leadership, communication, etc.)
- 7th scoring dimension; per-source weighted aggregation (manual=1.0, scorecard=0.9, manager=0.95, cv-extract=0.6)
- Auto-extract on JD save + CV upload
- Position competency-fit chart vs candidate demonstrated levels with critical-gap detection
- Admin tab → competency library CRUD
- Analytics → calibration + gap heatmap

### Candidate Profile Split View
Profile page = **always-on 2-column layout**: source document (PDF/PNG/DOCX) on left, extracted-data tabs on right. Drag the divider to resize, persists to localStorage `hire_profile_split`. Mobile <900px stacks vertical.
Tabs: PROFILE, EXPERIENCE, SKILLS, COMPETENCIES, ASSIGNMENTS, NOTES, INTERVIEWS, SCORECARDS, PIPELINE (with Processing Artifacts panel), ACTIVITY.

### Global CLI Pipeline Terminal
Singleton `<PipelineCli />` panel docked bottom-right of CV REPO. Self-polls `/candidates/pending?include_recent=true` every 1.5s, dedups events by `run_id|step_order|status`, ring buffer 500. Color-coded: green ✓, yellow ⏳ pulsing, red ✗, dim ☐. Footer: `2 RUNNING · 5 DONE · $0.087 SPENT · 1m 32s`. Buttons: MIN / CLEAR / SAVE (downloads JSON).

### Pending Files Table (CV intake)
- Lists `is_processed=false` candidates + 24h window of recently DONE
- Status filter chips: ALL/PENDING/RUNNING/DONE/ERROR
- Per-row: `▶ RUN` (pending), `→ PROFILE` (done), `↻ RETRY` (error), `✗ DISMISS` (localStorage-persisted hide)
- Bulk: select N → `▶ RUN N` triggers `/api/candidates/bulk_process`
- Multi-file upload: parallel XHR (cap 4) with per-file progress bars in `<UploadTracker />`

### Evaluation System (auto-generated, zero clicks)
- **Scorecard Templates** — 6 role-type templates (Engineering, Sales, Design, Product, Marketing, General), auto-matched to position by title/department
- **Competency Rubrics** — Auto-generated from JD on save/enhance, per-dimension 1-5 score labels, editable in Settings
- **Culture/Values Scoring** — 6th scoring dimension, keyword matching from position's culture_values config
- **AI Red/Green/Amber Flags** — Deterministic rules: job hopping, employment gaps, overqualified, underqualified, missing skills, domain mismatch, strong fits
- **Consensus Scoring** — Auto-recomputed on every scorecard submission, std-dev-based agreement level, lone dissent detection
- **Hiring Committee Votes** — Derived from scorecard recommendations (strong_hire/hire/no_hire/strong_no_hire)
- **Stack Ranking** — Composite(60%) + consensus(30%) + flag penalty(10%), auto-displayed as #1, #2, #3 badges
- **Calibration Report** — Per-interviewer stats (avg score, std dev, harshness index), position-level and org-wide

### AI Features (requires OPENROUTER_API_KEY)
- Auto-scan CVs when JD saved
- Auto-match positions when CV uploaded
- AI JD generation (500+ words, 7 sections)
- AI JD enhancement (DEI/legal/completeness scoring)
- AI interview questions (from CV gaps vs JD)
- AI candidate summary (executive brief)
- AI pipeline insights ("5 candidates stuck in screening")
- Smart NLP search ("Find backend engineers with 5+ years from FAANG")
- AI salary recommender
- AI rejection/offer email composer
- AI scorecard pre-fill
- Auto-generate evaluation rubrics from JD

### Chat v2 (Agno agent — flag-gated)

Opt-in replacement for legacy keyword chat. Default **OFF** (`AGENT_V2=false`); legacy SSE path in `backend/routes/chat.py` is preserved untouched. When `AGENT_V2=true`, chat dispatches to `backend/agents/hr_agent.py:arun()` async generator and emits SSE with `X-Chat-Version: 2` header so frontend renders `<AgentSteps />` + `<ToolTrace />`.

**Tools (11) — role allowlist matrix:**

| Tool | recruiter | analyst | admin / superadmin |
|------|-----------|---------|--------------------|
| `query_cvs` | ✓ | ✓ | ✓ |
| `get_candidate_brief` | ✓ | ✓ | ✓ |
| `score_cv_vs_position` | ✓ | ✓ | ✓ |
| `list_candidate_pipeline` | ✓ | ✓ | ✓ |
| `query_positions` | ✓ | ✓ | ✓ |
| `get_position_brief` | ✓ | ✓ | ✓ |
| `get_pipeline` | ✓ | ✓ | ✓ |
| `query_brain` | ✓ | ✓ | ✓ |
| `update_brain` (write) | ✗ | ✓ | ✓ |
| `query_funnel` | ✓ | ✓ | ✓ |
| `draft_email` | ✓ | ✗ | ✓ |

**PII redaction** on tool inputs (logged to `tool_traces`): `national_id`, `dob`, `phone`, `email` masked before persist.

**Memory recall:** every turn embeds the user query (cached 24h via `embed_cache`), cosine-searches `agent_memory` (pgvector) top-K (`AGNO_MEMORY_TOPK=5`), injects into LLM context. Successful turn writes summary back.

**Persistence tables:** `agent_runs` (mig 033 — session, cost, status), `agent_memory` (mig 034 — pgvector vectors), `tool_traces` (mig 035 — per-tool input/output/latency).

**Cost tracking:** every agent LLM call writes to `llm_call_log` with `step='agent'` → billing dashboard auto-aggregates. Per-session cap enforced via `AGENT_SESSION_CAP_USD` (queries `agent_runs.cost_usd`).

**Eval gate:** `python -m backend.agents.eval.run_eval` runs 30-case golden set; CI fails if mean rubric score < 4.0.

**Rollback:** set `AGENT_V2=false` in `.env`, recreate api container — flips back to legacy keyword chat instantly. No DB changes required (new tables remain, harmless).

**Runtime note:** Agno SDK not yet in local pip — `hr_agent.py` shim falls back to direct OpenRouter tool-loop with identical event contract. Switches to Agno-native after next Docker rebuild that pulls `agno`.

### Automation
- Rules engine: trigger → condition → action (auto-move stage, send email, tag)
- Email sequences (multi-step)
- SLA tracking (flag overdue candidates)
- Offer approval chains
- Auto-trigger chain: JD save → rubrics generated → candidate scored → flags generated → scorecard submitted → consensus recomputed

## Commands

```bash
# Development
cd frontend && npm install && npm run dev    # Frontend on :5173
cd backend && pip3 install -r requirements.txt
uvicorn backend.main:app --reload --port 8002  # Backend on :8002

# Run tests
python3 -m pytest tests/ -v

# Database backup
./scripts/backup.sh

# Production
cp .env.example .env   # Edit with real values
docker compose up -d --build
```

## Environment Variables

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-xxx   # AI features (get from openrouter.ai/keys)
DB_USER=pulse
DB_PASS=change-me
DB_DATABASE=pulsedb

# Optional
DEV_MODE=true                      # Bypass auth in development
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8090
LOG_FORMAT=json                    # "text" (default) or "json" for structured logs
PRELOAD_OCR=true                   # Pre-warm PaddleOCR on startup
DISABLE_PADDLE_OCR=true            # Disable PaddleOCR (use Vision LLM only)

# Auth (login system) — REQUIRED in prod
JWT_SECRET=<openssl rand -hex 32>
JWT_EXPIRY_H=8
SUPERADMIN_ID=admin
SUPERADMIN_PASS_HASH=$2b$12$...    # bcrypt; generate via `python -m backend.scripts.hash_pw <pw>`
# SUPERADMIN_PASS=change-me        # dev only — auto-hashed at startup, logs warning
ALLOW_REGISTER=false
LOGIN_LOCKOUT_AFTER=5
LOGIN_LOCKOUT_MIN=15

# File security — signed URLs for /file (5-min TTL HMAC)
FILE_SIGN_SECRET=<openssl rand -hex 32>   # falls back to JWT_SECRET if unset

# LLM safety
LLM_CALL_TIMEOUT_S=60
LLM_DAILY_CAP_USD=200            # bumped for 10-user load

# Concurrency tuning (10 parallel users baseline)
WORKERS=4                        # uvicorn workers (rule: 2 × CPU cores)
DB_POOL_MIN=5
DB_POOL_MAX=20                   # 4 workers × 20 = 80 conns < PG max 100
OCR_CONCURRENCY=2                # PaddleOCR parallel jobs (~500MB each)
LLM_MAX_CONCURRENT=8             # OpenRouter calls per worker
RATE_LIMIT=600/minute            # global default (per-route stricter)

# OCR image enhancement (pre-OCR upscale + sharpen + contrast)
OCR_UPSCALE_MIN_PX=2000          # below this → LANCZOS upscale; skip if already crisp
OCR_UPSCALE_MAX_PX=4000          # cap so 200×200 thumbs don't become 8000×8000

# Ops
APP_VERSION=1.0.0-beta

# Vision verifier (Step 2.5) — second-pass OCR on critical fields
ENABLE_VISION_VERIFIER=true
VISION_VERIFIER_MODEL=anthropic/claude-opus-4.7   # Best for digit precision; ~$0.014/doc

# Chat v2 — Agno agent (NEW; default OFF, legacy keyword chat preserved)
AGENT_V2=false                       # master flag; flip to true to enable agent loop
AGNO_MODEL=                          # override agent LLM (else falls back to CHAT_MODEL)
AGNO_MAX_STEPS=8                     # max tool-loop iterations per turn
AGNO_TOOL_TIMEOUT_S=15               # per-tool execution timeout
AGNO_MEMORY_TOPK=5                   # pgvector recall results injected into context
AGNO_ENABLE_REFLECTION=false         # post-step self-critique (off by default; cost)
AGENT_SESSION_CAP_USD=1              # per-session $ ceiling (queries agent_runs.cost_usd)
REDIS_URL=redis://redis:6379/0       # embed + tool-result cache; in-mem fallback if down
```

## LLM Models (via OpenRouter)

- **CHAT_MODEL**: google/gemini-3-flash-preview (user-facing, vision OCR, structure step) — $0.30/$2.50 per 1M tokens
- **DEEP_MODEL**: openai/gpt-5.4-mini (complex reasoning)
- **LITE_MODEL**: google/gemini-3.1-flash-lite-preview (page classify, enrich, knowledge, quality, tag, auto_match) — $0.10/$0.40
- **VERIFIER_MODEL**: anthropic/claude-opus-4.7 (Step 2.5 critical-field verifier, handwritten only) — $15/$75
- **Embeddings**: gemini-embedding-2-preview, 1536 dimensions

### Vision bench (10-model comparison on Myanmar driver-form)
See `bench/vision_results.xlsx`. Tiered Flash + Opus-verify = $0.015/doc, 17/17 fields, 3/3 critical exact. 4× cheaper than full Opus. Cheapest viable = Flash-Lite ($0.0005/doc, 1-day DOB error).

## Security

### Login + Auth (M2)
- **Login flow**: brutalist `/login` page (ACCESS_PORTAL design) → `POST /api/auth/login` `{operator_id, access_key}` → JWT HS256 (8h exp) → stored in `localStorage.hire_token` + `hire_token_exp`
- **Endpoints**: `/api/auth/{login,register,me,logout,config}`. `/config` is public, returns `{allow_register, app_name}` for frontend gating
- **Bcrypt** cost 12; **lockout** after `LOGIN_LOCKOUT_AFTER=5` fails for `LOGIN_LOCKOUT_MIN=15`min (returns 429 with `retry_after`)
- **Generic 401** `INVALID_CREDENTIALS` (no user enumeration)
- **Superadmin bootstrap**: `bootstrap_superadmin()` runs at startup. If `SUPERADMIN_PASS_HASH` set → UPSERTs row with role='superadmin'. If only `SUPERADMIN_PASS` set → bcrypt-hash at boot + log warning
- **Self-register** off by default (`ALLOW_REGISTER=false`); elevated roles require superadmin Bearer
- **CLI**: `python -m backend.scripts.hash_pw <password>` generates bcrypt hash for env
- **Migration**: `db/migrations/028_users.sql` (operator_id, pass_hash, role, last_login_at, failed_login_count, locked_until)
- **Backward-compat**: `core/auth.validate_token` tries JWT first, falls back to legacy hex-token DB lookup. Both work side-by-side
- **Frontend guard**: `frontend/src/routes/+layout.ts` SSR-disabled load function calls `me()` and redirects to `/login` on 401. Skips `/login`, `/register`, `/careers`
- **Logout**: top-nav `LOGOUT` button → `clearToken()` + redirect

### File access (signed URLs)
- `GET /candidates/{id}/file/sign` (Bearer) → `{url, exp, ttl_s}` with HMAC-signed query
- `GET /candidates/{id}/file?sig=…&exp=…` validates HMAC + expiry. Replaces token-in-query (which leaked to logs/Referer/history)
- Legacy `?token=` accepted with deprecation log
- `FILE_SIGN_SECRET` env (falls back to `JWT_SECRET`)
- `DocViewer.svelte` calls `/file/sign` first, falls back to legacy if endpoint absent

### Other hardening
- File upload: **20MB max** + MIME whitelist (pdf/docx/doc/txt/png/jpg). Early 413 before pipeline
- `/file` endpoint returns JSON 404 `{error:"file_missing"}` instead of 500 when path missing on disk
- **CORS**: env-driven `ALLOWED_ORIGINS` list, no wildcard. Logged at startup
- **CSRF**: Origin-based middleware, reuses parsed origins list
- **Rate limit** (slowapi): default `RATE_LIMIT=600/minute` global (env-tunable), 5/min upload + login + register, 30/min LLM endpoints (chat, ai-summary, export.docx)
- **Concurrency gates**: `OCR_GATE = Semaphore(2)` in `cv_parser.py`, `LLM_GATE = Semaphore(8)` in `config.py`. Cap PaddleOCR jobs (RAM) and OpenRouter in-flight calls per worker. Tune via `OCR_CONCURRENCY` / `LLM_MAX_CONCURRENT` env.
- **XSS**: all `{@html}` sinks (mdLite, renderNoteWithMentions) escape `&<>"'` BEFORE markdown transforms — LLM output + note content can carry candidate-injected payload
- **LLM safety**: `LLM_CALL_TIMEOUT_S=60` per-call wrap; `cost_cap.check_and_record()` enforces `LLM_DAILY_CAP_USD` per tenant; structured JSON log per call (`{ts,tenant,model,latency_ms,in_tokens,out_tokens,cost_usd,status}`)
- **Step 13 isolation**: AI_SUMMARY failure no longer kills upload. Sets `candidates.ai_summary_status='failed'` (mig 027), upload returns success
- **Report.docx**: built in `loop.run_in_executor()` with 30s `wait_for` timeout; large fields truncated to 50KB; `StreamingResponse` for large payloads
- **Pipeline trace cap**: pruned to 50 rows per candidate
- **Request ID**: UUID per request in `X-Request-Id` header
- **SQL**: parameterized queries
- **Health**: `/api/health` returns `{status, db, llm IDs, disk writable, version, uptime, db_pool, ai_available}`
- **Startup probe**: `/data/cvs` writability checked + logged
- **Volume**: `compose.yaml` documents named-volume vs bind-mount tradeoff (use bind for prod)
- **Admin role gate**: `require_admin` accepts both `admin` AND `superadmin` (was `admin` only — broke `pulse_admin` access). Used by all `/api/admin/*` routes incl. flag toggles + billing
- **Feature flags**: `system_flags` table (key `feature_*`), seeded via migration 007. **Defaults: Interviews + Pools OFF** (migration 032). Superadmin toggles via `/admin` → SYSTEM tab → FEATURES section. Frontend nav reads `/api/system/features` (public read-only) and filters via `$derived` in `+layout.svelte`. `updated_by IS NULL` distinguishes env-seeded vs admin-touched (migration 032 only flips untouched rows)
- **Billing dashboard**: `/billing` route, admin/superadmin only. Reads `llm_call_log` (per-call ledger written by `_log_llm_call` in `config.py`, best-effort, never blocks LLM). Endpoints: `summary`, `by-model`, `by-step`, `hourly`, `jobs`, `top`, `job/{run_id}`, `export.csv`. Filters: today / 7d / 30d / mtd. 30s auto-refresh. Cap progress bar (green→orange→red at 50/80%)

### Open items before GA
- HttpOnly cookie auth (currently localStorage JWT — XSS-stealable)
- MFA / TOTP
- Password reset flow + email
- Audit log retention policy
- Verifier model ID `claude-opus-4.7` matches `claude-opus-4.\d` audit warn — verify against current Anthropic naming before prod (real format uses dashes: `claude-opus-4-N-YYYYMMDD`)

## API Docs

- Swagger UI: http://localhost:8002/api/docs
- ReDoc: http://localhost:8002/api/redoc
- OpenAPI JSON: http://localhost:8002/api/openapi.json
- Health: http://localhost:8002/api/health
- OCR Health: http://localhost:8002/api/health/ocr
- AI Status: http://localhost:8002/api/ai-status

## Debugging Svelte 5 `effect_update_depth_exceeded`

**Symptom**: Page stuck on loading dots. Console shows
`Uncaught Error: https://svelte.dev/e/effect_update_depth_exceeded` with
recursive `#v` frames in minified runtime chunk (e.g. `CqD3Buz7.js`).

### Root cause pattern
A `$effect` that reads reactive state in its **sync portion** (before any
`await`) and also writes to that same state. Each write invalidates the
effect, which re-runs, reads, writes — infinite loop until Svelte aborts.

Common offenders:
- Loader function called inside effect that does `if (myState.includes(...))`
  early-return AND also `myState = ...` assignment
- Multiple `*Loaded = true; loadX()` synchronous writes inside one effect
  (each write fires re-run before effect finishes)
- MutationObserver writing reactive state on every DOM mutation

### Diagnostic procedure
1. Enable sourcemaps + skip minify in `frontend/vite.config.ts`:
   ```ts
   build: { sourcemap: true, minify: false }
   ```
2. Add a counter to every `$effect` in the suspect page:
   ```js
   let _dbg = (typeof window !== 'undefined') && (window.__hireFx = window.__hireFx || {});
   function _t(label) { if (!_dbg) return; _dbg[label] = (_dbg[label] || 0) + 1;
     if (_dbg[label] > 50) console.warn('[fx-loop]', label, _dbg[label]); }

   $effect(() => { _t('fx_main'); /* ... */ });
   ```
3. Rebuild + redeploy. Reload page. The first label that warns >50 = looper.
4. Inspect that effect's body and its callees for the read-then-write pattern.

### Fix patterns
- Wrap callee in `untrack`:
  ```js
  import { untrack } from 'svelte';
  $effect(() => { if (id) untrack(() => loadStuff()); });
  ```
- Defer state writes out of sync portion:
  ```js
  $effect(() => {
    const v = activeTab;
    queueMicrotask(() => { if (!loaded) { loaded = true; loadX(); } });
  });
  ```
- Replace `MutationObserver`-based path tracking with `$app/state` page:
  ```js
  import { page } from '$app/state';
  let currentPath = $derived(page.url?.pathname || '/');
  ```

### Reset state on `[id]` route param change
SvelteKit reuses component instance when only the `id` param changes
(e.g. `/candidates/9` → `/candidates/8`). State persists. Reset
per-record state at top of the loader:
```js
async function loadCandidate() {
  loading = true;
  candidate = null;
  notes = []; interviews = []; /* ... */
  notesLoaded = false; /* ... */
  activeTab = 'profile';
  candidate = await apiJson(`/candidates/${candidateId}`);
  loading = false;
}
```

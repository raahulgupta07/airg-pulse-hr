# PULSE — Upgrade Guide

This guide covers safe upgrades, the contract every PR must follow, and
what to do when something breaks.

---

## 1. Golden Rules

- **Additive migrations only.** Never `DROP TABLE`, `DROP COLUMN`,
  `RENAME COLUMN`, `ALTER COLUMN ... TYPE`, or `TRUNCATE` in
  `db/migrations/*.sql`. CI enforces this — see
  `.github/workflows/migration-lint.yml`. To override (rare, requires
  explicit data-migration plan), apply the PR label
  `allow-destructive-migration`.
- **No env-var settings for user-tweakable knobs.** Anything an operator
  should change from the UI lives in the `settings` table (mig 030,
  `backend/core/settings.py`). Env vars are only for secrets, infra
  endpoints, and immutable build config.
- **Never `docker compose down -v`.** The `-v` flag deletes named
  volumes, including `pgdata` and `hire-data`. Use `down` (no flag) or
  `restart` to bounce containers without data loss.
- **Always take a pre-upgrade snapshot.** Run `./scripts/pre_upgrade.sh`
  before any pull. This produces a timestamped `pg_dump.gz` plus a
  CV-storage tarball under `./data/backups/`.
- **Never skip migrations.** `/api/health` reports `migrations.pending`;
  treat any non-empty list as a failed deploy.

---

## 2. Standard Upgrade Flow

1. `git pull`
2. `./scripts/pre_upgrade.sh`
3. `docker compose pull && docker compose up -d --build`
4. `curl http://localhost:8090/api/health` — confirm `status:ok` and
   `migrations.pending:[]` (if exposed). At minimum verify `db:ok`,
   `disk.writable:true`.
5. Smoke test: log in as superadmin, upload one CV, watch the pipeline
   complete in the global CLI terminal.
6. If broken, roll back:
   ```
   ./scripts/restore.sh ./data/backups/pre_upgrade_<timestamp>.dump.gz --confirm
   ```

---

## 3. What's Preserved Automatically

| Surface                          | Storage                                        | Survives redeploy? |
| -------------------------------- | ---------------------------------------------- | ------------------ |
| Postgres data (all 44+ tables)   | `pgdata` named volume                          | Yes                |
| CV files (PDF/PNG/DOCX)          | `hire-data` volume → `/data/cvs`               | Yes                |
| Settings (branding, weights, …)  | `settings` table (mig 030)                     | Yes                |
| Auth users — additional accounts | `users` table (mig 028)                        | Yes                |
| Auth users — superadmin          | re-bootstrapped each boot from env vars        | Yes (re-seeded)    |
| Pipeline traces                  | `pipeline_trace` table                         | Yes                |
| Candidates, JDs, scorecards      | DB                                             | Yes                |
| Notes, interviews, offers        | DB                                             | Yes                |
| Saved searches, pools, automations | DB                                           | Yes                |

The superadmin row is UPSERTed from `SUPERADMIN_ID` +
`SUPERADMIN_PASS_HASH` on every boot — rotating those env vars
transparently rotates the superadmin credentials without touching
other accounts.

---

## 4. What Requires Manual Migration

Rare. Tracked here per release.

| Release | Change | Action required |
| ------- | ------ | --------------- |
| _none yet_ | — | — |

Anything that would belong in this table requires the
`allow-destructive-migration` label and a documented data-migration
script under `scripts/migrate_<version>.sh`.

---

## 5. Disaster Recovery

Restore from the most recent pre-upgrade snapshot:

```bash
./scripts/restore.sh ./data/backups/pre_upgrade_<timestamp>.dump.gz --confirm
```

The script:

1. Stops the API container (leaves DB up).
2. Drops + recreates the target database.
3. Restores from the gzipped `pg_dump` file.
4. Restarts the API.

For ad-hoc backups outside the upgrade flow, use `./scripts/backup.sh`.

---

## 6. Pre-merge Checklist for Feature PRs

- [ ] New migration is additive only (no `DROP` / `RENAME` / `TRUNCATE`
      / `ALTER COLUMN ... TYPE`).
- [ ] All tests pass (`pytest tests/ -v`).
- [ ] Backward-compatible API change (or new versioned endpoint under
      `/api/v1/...` / `/api/v2/...`).
- [ ] User-tweakable settings stored in the `settings` table, not env
      vars. New env vars are reserved for secrets and infra.
- [ ] No new required env vars without a corresponding entry in
      `.env.example`.
- [ ] `/api/health` returns `ok` after running new migrations against a
      fresh DB **and** against a copy of production data.
- [ ] If a destructive migration is genuinely required, PR has the
      `allow-destructive-migration` label and links a data-migration
      script.

---

## 7. Local Pre-commit Hook (optional)

Run the same migration lint locally before each commit:

```bash
./scripts/install_hooks.sh
```

This installs `.githooks/pre-commit` via `git config core.hooksPath`.
Uninstall by resetting `core.hooksPath`:

```bash
git config --unset core.hooksPath
```

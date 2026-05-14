#!/usr/bin/env bash
# ============================================================================
# pre_upgrade.sh — Atomic pre-deploy snapshot
# ============================================================================
# Captures EVERYTHING needed to roll back a failed deploy:
#   1. PostgreSQL custom-format dump (gzipped) of `pulsedb`
#   2. Tarball of the `hire-data` named volume (CV files at /data)
#   3. Manifest JSON: timestamp, image SHA, git commit, db size
#
# Usage:    bash scripts/pre_upgrade.sh
# Aborts with non-zero exit on any failure. Safe to invoke from CI.
# ============================================================================
set -euo pipefail

# ---- Locate repo root ------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

BACKUP_DIR="${ROOT_DIR}/data/backups"
mkdir -p "${BACKUP_DIR}"

TS="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/pre_upgrade_${TS}.dump.gz"
CV_TAR="${BACKUP_DIR}/cvs_${TS}.tar.gz"
MANIFEST="${BACKUP_DIR}/pre_upgrade_${TS}.manifest.json"

# ---- Load .env -------------------------------------------------------------
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi
DB_USER="${DB_USER:-pulse}"
DB_DATABASE="${DB_DATABASE:-pulsedb}"

banner() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }
ok()     { printf "\033[1;32m[ok]\033[0m %s\n" "$*"; }
warn()   { printf "\033[1;33m[warn]\033[0m %s\n" "$*" >&2; }
fail()   { printf "\033[1;31m[fail]\033[0m %s\n" "$*" >&2; exit 1; }

banner "Pre-upgrade snapshot — ${TS}"

# ---- Step 0: docker available? --------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  warn "docker not on PATH; skipping snapshot. Install Docker to enable."
  exit 0
fi
if ! docker info >/dev/null 2>&1; then
  warn "docker daemon not reachable; skipping snapshot. Start Docker Desktop / dockerd."
  exit 0
fi

# ---- Step 1: db healthy? ---------------------------------------------------
banner "Checking db health"
if ! docker compose ps --format json db 2>/dev/null | grep -q '"Health":"healthy"'; then
  # Fallback: tolerate older compose JSON, also try plain 'ps'
  if ! docker compose ps db 2>/dev/null | grep -Eq '\(healthy\)|healthy'; then
    fail "db is not healthy. Run \`docker compose up -d db\` first, then retry."
  fi
fi
ok "db is healthy"

# ---- Step 2: pg_dump -------------------------------------------------------
banner "Dumping ${DB_DATABASE} (custom format, gzipped)"
if ! docker exec -e PGPASSWORD="${DB_PASS:-pulse_secret}" pulse-db \
      pg_dump -U "${DB_USER}" -d "${DB_DATABASE}" -F c \
      | gzip > "${DUMP_FILE}"; then
  fail "pg_dump failed"
fi
DUMP_BYTES=$(wc -c < "${DUMP_FILE}" | tr -d ' ')
ok "wrote ${DUMP_FILE} (${DUMP_BYTES} bytes)"

# ---- Step 3: tar hire-data volume -----------------------------------------
banner "Tarring hire-data volume (CV files)"
# Use a throwaway alpine container that mounts pulse-api's volumes.
if ! docker run --rm --volumes-from pulse-api -v "${BACKUP_DIR}:/out" alpine \
      tar czf "/out/cvs_${TS}.tar.gz" -C /data . ; then
  fail "tar of hire-data volume failed"
fi
CV_BYTES=$(wc -c < "${CV_TAR}" | tr -d ' ')
ok "wrote ${CV_TAR} (${CV_BYTES} bytes)"

# ---- Step 4: manifest ------------------------------------------------------
banner "Writing manifest"
IMAGE_SHA="$(docker inspect -f '{{.Image}}' pulse-api 2>/dev/null || echo 'unknown')"
GIT_COMMIT="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo 'unknown')"
DB_SIZE_BYTES="$(docker exec -e PGPASSWORD="${DB_PASS:-pulse_secret}" pulse-db \
                  psql -U "${DB_USER}" -d "${DB_DATABASE}" -tAc \
                  "SELECT pg_database_size('${DB_DATABASE}');" 2>/dev/null | tr -d ' \r' || echo '0')"

cat > "${MANIFEST}" <<JSON
{
  "timestamp": "${TS}",
  "iso_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "image_sha": "${IMAGE_SHA}",
  "git_commit": "${GIT_COMMIT}",
  "db_database": "${DB_DATABASE}",
  "db_size_bytes": ${DB_SIZE_BYTES:-0},
  "dump_file": "$(basename "${DUMP_FILE}")",
  "dump_bytes": ${DUMP_BYTES},
  "cv_tar_file": "$(basename "${CV_TAR}")",
  "cv_tar_bytes": ${CV_BYTES}
}
JSON
ok "wrote ${MANIFEST}"

banner "Snapshot complete"
echo "  dump:     ${DUMP_FILE}"
echo "  cv tar:   ${CV_TAR}"
echo "  manifest: ${MANIFEST}"
echo
printf "\033[1;32mNow run: docker compose up -d --build\033[0m\n"

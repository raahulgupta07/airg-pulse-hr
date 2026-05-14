#!/usr/bin/env bash
# ============================================================================
# restore.sh — Restore PostgreSQL from a snapshot
# ============================================================================
# Usage:    bash scripts/restore.sh <dump-file> --confirm
# Supports: pulse_*.dump.gz  (pg_dump -F c, gzipped)  → pg_restore
#           pulse_*.sql.gz   (plain SQL, gzipped)     → psql
#
# DESTRUCTIVE: drops + re-creates objects in `pulsedb`.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi
DB_USER="${DB_USER:-pulse}"
DB_DATABASE="${DB_DATABASE:-pulsedb}"
DB_PASS="${DB_PASS:-pulse_secret}"

usage() {
  cat <<USAGE
USAGE: bash scripts/restore.sh <dump-file> --confirm

  <dump-file>   Path to .dump.gz (custom format) or .sql.gz (plain SQL).
  --confirm     Required. Acknowledges destructive intent.

This will:
  1. Stop the api container (db keeps running).
  2. Restore the dump into the running pulse-db (--clean --if-exists).
  3. Restart api and curl /api/health.
USAGE
}

danger_banner() {
  printf "\n\033[1;41;97m  !!  DANGER: DESTRUCTIVE RESTORE  !!  \033[0m\n"
  printf "\033[1;31mThis WILL drop and replace data in database '%s'.\033[0m\n\n" "${DB_DATABASE}"
}

if [[ $# -lt 1 ]]; then
  danger_banner; usage; exit 2
fi

DUMP="$1"; shift || true
CONFIRM="${1:-}"

if [[ ! -f "${DUMP}" ]]; then
  echo "[fail] dump file not found: ${DUMP}" >&2; exit 2
fi
if [[ "${CONFIRM}" != "--confirm" ]]; then
  danger_banner
  echo "Refusing to run without --confirm."
  usage
  exit 2
fi

# ---- Detect format ---------------------------------------------------------
case "${DUMP}" in
  *.dump.gz) MODE="pg_restore" ;;
  *.sql.gz)  MODE="psql" ;;
  *.dump)    MODE="pg_restore_plain" ;;
  *.sql)     MODE="psql_plain" ;;
  *) echo "[fail] unknown extension; expected .dump.gz / .sql.gz / .dump / .sql" >&2; exit 2 ;;
esac

echo "[info] dump=${DUMP}  mode=${MODE}  target_db=${DB_DATABASE}"

# ---- Step 1: stop api ------------------------------------------------------
echo "[step] stopping api container..."
docker compose stop api || echo "[warn] api stop returned non-zero (already down?)"

# ---- Step 2: restore -------------------------------------------------------
echo "[step] restoring..."
case "${MODE}" in
  pg_restore)
    gunzip -c "${DUMP}" | docker exec -i -e PGPASSWORD="${DB_PASS}" pulse-db \
      pg_restore --clean --if-exists --no-owner -U "${DB_USER}" -d "${DB_DATABASE}"
    ;;
  pg_restore_plain)
    docker exec -i -e PGPASSWORD="${DB_PASS}" pulse-db \
      pg_restore --clean --if-exists --no-owner -U "${DB_USER}" -d "${DB_DATABASE}" < "${DUMP}"
    ;;
  psql)
    gunzip -c "${DUMP}" | docker exec -i -e PGPASSWORD="${DB_PASS}" pulse-db \
      psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_DATABASE}"
    ;;
  psql_plain)
    docker exec -i -e PGPASSWORD="${DB_PASS}" pulse-db \
      psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_DATABASE}" < "${DUMP}"
    ;;
esac
echo "[ok] restore finished"

# ---- Step 3: start api -----------------------------------------------------
echo "[step] starting api..."
docker compose start api

# ---- Step 4: health probe --------------------------------------------------
PORT="${PORT:-8090}"
URL="http://localhost:${PORT}/api/health"
echo "[step] waiting up to 60s for ${URL}"
for i in $(seq 1 30); do
  if curl -fsS "${URL}" >/dev/null 2>&1; then
    echo "[ok] api healthy:"
    curl -fsS "${URL}" || true
    echo
    exit 0
  fi
  sleep 2
done
echo "[fail] api did not become healthy within 60s — investigate logs: docker compose logs api" >&2
exit 1

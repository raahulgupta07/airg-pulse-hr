#!/bin/bash
set -e

# Ensure data dirs exist + writable (covers bind-mount + named-volume cases)
for d in /data /data/cvs /data/screenshots /data/uploads /data/exports /data/brain_uploads; do
    mkdir -p "$d" 2>/dev/null || true
    chmod -R u+rwX "$d" 2>/dev/null || true
done

# Wait for database if requested
if [ "$WAIT_FOR_DB" = "true" ]; then
    echo "Waiting for database..."
    DB_WAIT=0
    until pg_isready -h "${DB_HOST:-db}" -U "${DB_USER:-pulse}" -q 2>/dev/null; do
        sleep 1
        DB_WAIT=$((DB_WAIT + 1))
        if [ "$DB_WAIT" -ge 120 ]; then
            echo "Database wait timed out after 120s — proceeding anyway (app will retry)."
            break
        fi
    done
    echo "Database is ready."
fi

# Start the application
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-1}

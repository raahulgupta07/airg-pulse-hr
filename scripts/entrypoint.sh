#!/bin/bash
set -e

# Wait for database if requested
if [ "$WAIT_FOR_DB" = "true" ]; then
    echo "Waiting for database..."
    until pg_isready -h "${DB_HOST:-db}" -U "${DB_USER:-hire}" -q 2>/dev/null; do
        sleep 1
    done
    echo "Database is ready."
fi

# Start the application
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-2}

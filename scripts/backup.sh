#!/bin/bash
BACKUP_DIR="${BACKUP_DIR:-./data/backups}"
DB_USER="${DB_USER:-hire}"
DB_NAME="${DB_DATABASE:-hiredb}"
DB_HOST="${DB_HOST:-localhost}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
pg_dump -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/hire_${TIMESTAMP}.sql"
echo "Backup saved: $BACKUP_DIR/hire_${TIMESTAMP}.sql"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/hire_*.sql | tail -n +8 | xargs rm -f 2>/dev/null
echo "Old backups cleaned (keeping last 7)"

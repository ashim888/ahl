#!/usr/bin/env bash
# Backs up the MySQL database and the media directory — previously nothing
# in this repo or its docs touched backups at all (no mysqldump cron, no
# media backup step, not even a manual runbook note). Meant to be run from
# cron on the production host, e.g.:
#   0 2 * * * cd /path/to/ahl && ./backup.sh >> backups/backup.log 2>&1
# Every step here is safe to re-run — output files are timestamped, nothing
# is overwritten, and old backups beyond BACKUP_RETENTION_DAYS are pruned
# automatically so this can't silently fill the disk over time.
#
# Usage: ./backup.sh
set -euo pipefail
cd "$(dirname "$0")"

# Same .env this project's own settings.py loads via python-dotenv — reused
# here rather than duplicating DB_NAME/DB_USER/DB_PASSWORD/MEDIA_ROOT in a
# second place that could drift out of sync with the real config.
if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

DB_NAME="${DB_NAME:-ajna_health_lens}"
DB_USER="${DB_USER:-ajna_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
MEDIA_ROOT="${MEDIA_ROOT:-media}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "==> [1/3] Dumping MySQL database ($DB_NAME)"
# MYSQL_PWD (not --password=...) so the DB password never shows up in `ps`
# output — mysqldump/mysql both honor it the same way.
MYSQL_PWD="${DB_PASSWORD:-}" mysqldump \
    --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" \
    --single-transaction --routines --triggers \
    "$DB_NAME" | gzip > "$BACKUP_DIR/db-$TIMESTAMP.sql.gz"

echo "==> [2/3] Archiving media directory ($MEDIA_ROOT)"
if [ -d "$MEDIA_ROOT" ]; then
    tar -czf "$BACKUP_DIR/media-$TIMESTAMP.tar.gz" "$MEDIA_ROOT"
else
    echo "    $MEDIA_ROOT does not exist — nothing to archive yet, skipping"
fi

echo "==> [3/3] Pruning backups older than $BACKUP_RETENTION_DAYS days"
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.sql.gz' -o -name 'media-*.tar.gz' \) \
    -mtime "+$BACKUP_RETENTION_DAYS" -print -delete

echo "==> Done. Wrote $BACKUP_DIR/db-$TIMESTAMP.sql.gz"

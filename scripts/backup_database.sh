#!/usr/bin/env bash
# backup_database.sh – Backup the SQLite database
# Can be run manually or via cron inside the container

set -euo pipefail

DB_PATH="${DATABASE_PATH:-/app/data/content_ai.db}"
BACKUP_PATH="${BACKUP_PATH:-/app/data/content_ai_backup.db}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_DATED="/app/data/content_ai_backup_${TIMESTAMP}.db"

if [ ! -f "$DB_PATH" ]; then
    echo "[ERROR] Database not found at $DB_PATH"
    exit 1
fi

# Create a timestamped backup
cp "$DB_PATH" "$BACKUP_DATED"
# Also update the latest backup symlink
cp "$DB_PATH" "$BACKUP_PATH"

echo "[INFO] Database backed up to $BACKUP_DATED"

# Prune old backups (keep last 7)
ls -t /app/data/content_ai_backup_*.db 2>/dev/null | tail -n +8 | xargs -r rm --
echo "[INFO] Old backups pruned"

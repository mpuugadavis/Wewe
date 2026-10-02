#!/usr/bin/env bash
set -euo pipefail

: "${BACKUP_MAX_AGE_SECONDS:?BACKUP_MAX_AGE_SECONDS must be set}"
BACKUP="${1:?Usage: BACKUP_MAX_AGE_SECONDS=... $0 backup.dump}"

[[ -f "$BACKUP" ]] || { echo "Backup file not found: $BACKUP" >&2; exit 1; }
command -v pg_restore >/dev/null 2>&1 || { echo "pg_restore is required but was not found in PATH" >&2; exit 1; }

if ! [[ "$BACKUP_MAX_AGE_SECONDS" =~ ^[0-9]+$ ]] || (( BACKUP_MAX_AGE_SECONDS < 1 )); then
  echo "BACKUP_MAX_AGE_SECONDS must be a positive integer" >&2
  exit 1
fi

NOW=$(date +%s)
MODIFIED=$(stat -c %Y "$BACKUP" 2>/dev/null || stat -f %m "$BACKUP")
AGE=$((NOW - MODIFIED))

if (( AGE < 0 )); then echo "Backup modification time is in the future" >&2; exit 1; fi
if (( AGE > BACKUP_MAX_AGE_SECONDS )); then echo "Backup is stale: age=$AGE s max=$BACKUP_MAX_AGE_SECONDS s" >&2; exit 1; fi

pg_restore --list "$BACKUP" >/dev/null
echo "Backup is fresh and archive-valid: $BACKUP (age=$AGE s)"

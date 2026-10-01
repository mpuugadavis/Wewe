#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL must be set}"
: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=YES to authorize a restore}"

if [[ "$RESTORE_CONFIRM" != "YES" ]]; then
  echo "Restore refused: RESTORE_CONFIRM must equal YES" >&2
  exit 1
fi

DUMP="${1:?Usage: RESTORE_CONFIRM=YES DATABASE_URL=... RESTORE_DATABASE_URL=... $0 backup.dump}"

[[ -f "$DUMP" ]] || {
  echo "Backup file not found: $DUMP" >&2
  exit 1
}

command -v pg_restore >/dev/null 2>&1 || {
  echo "pg_restore is required but was not found in PATH" >&2
  exit 1
}

# Restore is intentionally limited to a separately supplied target database.
# The target must be empty or disposable; the script never drops the database.
pg_restore \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  --dbname="$RESTORE_DATABASE_URL" \
  "$DUMP"

echo "Restore completed successfully into the supplied target database."

#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"
OUTPUT="${1:-./backups/wewe-$(date -u +%Y%m%dT%H%M%SZ).dump}"

command -v pg_dump >/dev/null 2>&1 || {
  echo "pg_dump is required but was not found in PATH" >&2
  exit 1
}

mkdir -p "$(dirname "$OUTPUT")"
umask 077

pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="$OUTPUT" \
  "$DATABASE_URL"

pg_restore --list "$OUTPUT" >/dev/null

echo "Backup created and archive-validated: $OUTPUT"

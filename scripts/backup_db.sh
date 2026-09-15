#!/usr/bin/env bash
set -euo pipefail

output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || { echo "--output requires a path" >&2; exit 2; }
      output="$2"; shift 2
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$output" ]]; then
  mkdir -p backups
  output="backups/commerce-agent-$(date -u +%Y%m%dT%H%M%SZ).dump"
fi
db_url="${DATABASE_MIGRATION_URL:-${DATABASE_URL:-}}"
[[ -n "$db_url" ]] || { echo "DATABASE_MIGRATION_URL or DATABASE_URL is required" >&2; exit 2; }
# SQLAlchemy's ``postgresql+psycopg://`` URL is accepted by the app but not by
# libpq utilities; normalize only the scheme and leave credentials untouched.
db_url="${db_url/postgresql+psycopg:\/\//postgresql:\/\/}"
parent="$(dirname -- "$output")"
mkdir -p "$parent"
umask 077
tmp="${output}.tmp.$$"
trap 'rm -f "$tmp"' EXIT
pg_dump --format=custom --no-owner --no-privileges --file "$tmp" "$db_url"
mv -- "$tmp" "$output"
chmod 600 "$output"
printf 'backup_created path=%s bytes=%s\n' "$output" "$(wc -c < "$output")"

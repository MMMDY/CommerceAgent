#!/usr/bin/env bash
set -euo pipefail

input=""
target=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      [[ $# -ge 2 ]] || { echo "--input requires a path" >&2; exit 2; }
      input="$2"; shift 2
      ;;
    --target-url)
      [[ $# -ge 2 ]] || { echo "--target-url requires a value" >&2; exit 2; }
      target="$2"; shift 2
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$input" && -f "$input" ]] || { echo "a readable --input dump is required" >&2; exit 2; }
[[ -n "$target" ]] || { echo "an explicit --target-url is required" >&2; exit 2; }
target="${target/postgresql+psycopg:\/\//postgresql:\/\/}"
# No implicit DROP is performed. Restore into an explicitly selected target.
pg_restore --no-owner --no-privileges --exit-on-error --dbname "$target" "$input"
printf 'restore_completed input=%s\n' "$input"

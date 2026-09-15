#!/usr/bin/env bash
set -euo pipefail

root="evals/reports"
days=30
dry_run=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) root="${2:-}"; shift 2 ;;
    --days) days="${2:-}"; shift 2 ;;
    --apply) dry_run=0; shift ;;
    *) echo "usage: $0 [--root evals/reports] [--days 30] [--apply]" >&2; exit 2 ;;
  esac
done
[[ "$root" != "/" && -d "$root" ]] || { echo "refusing invalid report root" >&2; exit 2; }
[[ "$days" =~ ^[1-9][0-9]*$ ]] || { echo "days must be positive" >&2; exit 2; }
mapfile -t candidates < <(find "$root" -mindepth 1 -maxdepth 1 -type d -mtime "+$days" -print)
for path in "${candidates[@]}"; do
  if (( dry_run )); then
    printf 'would_remove path=%s\n' "$path"
  else
    rm -rf -- "$path"
    printf 'removed path=%s\n' "$path"
  fi
done
printf 'cleanup_count=%s dry_run=%s retention_days=%s\n' "${#candidates[@]}" "$dry_run" "$days"

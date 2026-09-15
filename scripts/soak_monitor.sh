#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 --duration 10m --interval 30 --output path --detach|--status|--stop" >&2
}

duration=""; interval=30; output=""; action=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) duration="${2:-}"; shift 2 ;;
    --interval) interval="${2:-}"; shift 2 ;;
    --output) output="${2:-}"; shift 2 ;;
    --detach) action=detach; shift ;;
    --status) action=status; shift ;;
    --stop) action=stop; shift ;;
    --worker) action=worker; shift ;;
    *) usage; exit 2 ;;
  esac
done
[[ -n "$output" ]] || { usage; exit 2; }
pid_file="${output}.pid"
parse_seconds() {
  local value="$1"
  [[ "$value" =~ ^([0-9]+)(s|m|h)$ ]] || return 1
  case "${BASH_REMATCH[2]}" in
    s) echo "${BASH_REMATCH[1]}" ;;
    m) echo "$((BASH_REMATCH[1] * 60))" ;;
    h) echo "$((BASH_REMATCH[1] * 3600))" ;;
  esac
}
if [[ "$action" == status ]]; then
  if [[ -f "$output" ]]; then sed -n '1p' "$output"; else echo '{"status":"not_started"}'; fi
  exit 0
fi
if [[ "$action" == stop ]]; then
  if [[ -f "$pid_file" ]]; then
    pid="$(sed -n '1p' "$pid_file")"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then kill "$pid"; fi
  fi
  echo '{"status":"stopped"}'
  exit 0
fi
if [[ "$action" == detach ]]; then
  duration="${duration:-24h}"
  [[ "$interval" =~ ^[1-9][0-9]*$ ]] || { echo "interval must be positive seconds" >&2; exit 2; }
  mkdir -p "$(dirname -- "$output")"
  nohup "$0" --duration "$duration" --interval "$interval" --output "$output" --worker >/dev/null 2>&1 &
  worker_pid=$!
  printf '%s\n' "$worker_pid" > "$pid_file"
  printf '{"status":"running","pid":%s,"output":"%s"}\n' "$worker_pid" "$output"
  exit 0
fi
[[ "$action" == worker ]] || { usage; exit 2; }
seconds="$(parse_seconds "${duration:-24h}")" || { echo "duration must use Ns/Nm/Nh" >&2; exit 2; }
[[ "$interval" =~ ^[1-9][0-9]*$ ]] || { echo "interval must be positive seconds" >&2; exit 2; }
mkdir -p "$(dirname -- "$output")"
umask 077
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; start_epoch="$(date +%s)"; samples=""; state=running
write_state() {
  local now="$1"; local tmp="${output}.tmp.$$"
  printf '{"schema_version":"1.0","status":"%s","started_at":"%s","updated_at":"%s","samples":[%s]}\n' \
    "$state" "$started" "$now" "${samples#,}" > "$tmp"
  mv -- "$tmp" "$output"
}
on_stop() { state=stopped; write_state "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 0; }
trap on_stop TERM INT
while true; do
  now_epoch="$(date +%s)"; elapsed=$((now_epoch - start_epoch))
  memory="null"
  [[ -r /sys/fs/cgroup/memory.current ]] && memory="$(sed -n '1p' /sys/fs/cgroup/memory.current)"
  disk="$(df -Pk "$(dirname -- "$output")" | awk 'NR==2 {print $4 * 1024}')"
  errors=0
  if command -v docker >/dev/null 2>&1; then
    errors="$(docker compose logs --no-color app 2>/dev/null | grep -c '"'"'"level"'"'".*"'"'"ERROR"'"'"' || true)"
  fi
  sample="{\"at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"elapsed_seconds\":$elapsed,\"memory_bytes\":$memory,\"disk_free_bytes\":$disk,\"error_count\":$errors}"
  samples="$samples,$sample"; write_state "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if (( elapsed >= seconds )); then state=completed; write_state "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 0; fi
  sleep "$interval"
done

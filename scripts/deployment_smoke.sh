#!/usr/bin/env sh
set -eu

request_id="phase0-smoke-$(date +%s)"
response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT

curl -fsS -X POST http://127.0.0.1:18437/v1/conversations \
    -H 'Content-Type: application/json' \
    --data "{\"client_request_id\":\"${request_id}\"}" >"$response_file"

conversation_id="$(sed -n 's/.*"id":"\([^"]*\)".*/\1/p' "$response_file")"
test -n "$conversation_id"

docker compose restart app db

attempt=0
until curl -fsS http://127.0.0.1:18437/health/ready >/dev/null; do
    attempt=$((attempt + 1))
    test "$attempt" -lt 30
    sleep 1
done

curl -fsS http://127.0.0.1:18437/v1/conversations | grep -F "$conversation_id" >/dev/null

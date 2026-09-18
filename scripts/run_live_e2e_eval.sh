#!/usr/bin/env bash
set -euo pipefail

# Live calls are opt-in.  The Python runner emits an explicit incomplete
# report when --allow-live or a real model/Judge profile is absent.
exec python -m src.harness.live_runner "$@"

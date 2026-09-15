#!/usr/bin/env bash
set -euo pipefail

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "${CONDA_DEFAULT_ENV:-}" = commerce
docker compose config --quiet
docker compose ps
curl -fsS http://127.0.0.1:19473/health/live >/dev/null
curl -fsS http://127.0.0.1:19473/health/ready >/dev/null
printf 'release-smoke passed\n'

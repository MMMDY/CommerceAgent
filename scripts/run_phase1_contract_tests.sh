#!/usr/bin/env bash
# Run PostgreSQL repository contracts against a dedicated Compose project.
# Credentials stay in process environment; this script never prints a URL.
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce

set -a
source .env
set +a

contract_project=commerceagent_phase1_contract
docker compose -p "$contract_project" up -d --no-build db

db_container="${contract_project}-db-1"
for _ in $(seq 1 30); do
    if [ "$(docker inspect -f '{{.State.Health.Status}}' "$db_container")" = "healthy" ]; then
        break
    fi
    sleep 1
done
test "$(docker inspect -f '{{.State.Health.Status}}' "$db_container")" = healthy

export DB_TEST_HOST
DB_TEST_HOST=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$db_container")

make_database_url() {
    local username_var=$1
    local password_var=$2
    python -c '
import os
from urllib.parse import quote
print(
    "postgresql+psycopg://%s:%s@%s:5432/%s"
    % (
        quote(os.environ[os.environ["USERNAME_VAR"]], safe=""),
        quote(os.environ[os.environ["PASSWORD_VAR"]], safe=""),
        os.environ["DB_TEST_HOST"],
        quote(os.environ["POSTGRES_DB"], safe=""),
    )
)
'
}

export USERNAME_VAR=POSTGRES_MIGRATION_USER PASSWORD_VAR=POSTGRES_MIGRATION_PASSWORD
export DATABASE_MIGRATION_URL
DATABASE_MIGRATION_URL=$(make_database_url "$USERNAME_VAR" "$PASSWORD_VAR")
python -m src.migrate

export USERNAME_VAR=POSTGRES_RUNTIME_USER PASSWORD_VAR=POSTGRES_RUNTIME_PASSWORD
export DATABASE_TEST_URL
DATABASE_TEST_URL=$(make_database_url "$USERNAME_VAR" "$PASSWORD_VAR")
python -m pytest tests/contract "$@"

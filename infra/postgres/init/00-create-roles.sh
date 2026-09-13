#!/bin/sh
set -eu

for role_name in "$POSTGRES_USER" "$POSTGRES_MIGRATION_USER" "$POSTGRES_RUNTIME_USER"; do
    case "$role_name" in
        [A-Za-z_][A-Za-z0-9_]*) ;;
        *) echo "invalid PostgreSQL role name" >&2; exit 1 ;;
    esac
done

psql --quiet --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=migration_user="$POSTGRES_MIGRATION_USER" \
    --set=migration_password="$POSTGRES_MIGRATION_PASSWORD" \
    --set=runtime_user="$POSTGRES_RUNTIME_USER" \
    --set=runtime_password="$POSTGRES_RUNTIME_PASSWORD" \
    --set=database_name="$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'migration_user', :'migration_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_user')
\gexec
SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
    :'runtime_user',
    :'runtime_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'runtime_user')
\gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'database_name', :'migration_user')
\gexec
SQL

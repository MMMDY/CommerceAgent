"""Contracts for the immutable Phase 1 PostgreSQL migration chain."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine, create_engine, text

from src.db import EXPECTED_ALEMBIC_REVISION

EXPECTED_TABLES = {
    "conversation": {"conversations", "messages"},
    "runtime": {
        "agent_runs",
        "confirmation_tokens",
        "idempotency_records",
        "model_invocations",
        "run_checkpoints",
        "run_events",
        "runtime_outbox",
        "tool_invocations",
    },
    "domain": {"policy_versions", "workflow_versions"},
    "memory": {"memory_facts"},
    "knowledge": {"knowledge_chunks", "knowledge_documents"},
    "evaluation": {"eval_case_results", "eval_runs", "judge_results"},
    "audit": {"audit_events"},
}


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_empty_database_reaches_phase1_head_with_all_expected_tables(engine: Engine) -> None:
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rows = connection.execute(
            text(
                "SELECT schemaname, tablename FROM pg_tables "
                "WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(EXPECTED_TABLES)},
        ).all()

    actual: dict[str, set[str]] = {schema: set() for schema in EXPECTED_TABLES}
    for schema, table in rows:
        actual[schema].add(table)
    assert revision == EXPECTED_ALEMBIC_REVISION
    assert actual == EXPECTED_TABLES


def test_phase1_uses_postgresql_native_types_and_active_run_constraint(engine: Engine) -> None:
    with engine.connect() as connection:
        types = connection.execute(
            text(
                "SELECT column_name, data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = 'runtime' AND table_name = 'agent_runs' "
                "AND column_name = ANY(:columns)"
            ),
            {"columns": ["run_id", "deadline_at", "row_version"]},
        ).all()
        payload_type = connection.execute(
            text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = 'runtime' AND table_name = 'run_events' "
                "AND column_name = 'payload_json'"
            )
        ).one()
        index_definition = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'runtime' "
                "AND indexname = 'uq_agent_runs_active_conversation'"
            )
        ).scalar_one()

    assert {name: (data_type, udt_name) for name, data_type, udt_name in types} == {
        "run_id": ("uuid", "uuid"),
        "deadline_at": ("timestamp with time zone", "timestamptz"),
        "row_version": ("bigint", "int8"),
    }
    assert tuple(payload_type) == ("jsonb", "jsonb")
    assert "WHERE" in index_definition
    for terminal_status in ("completed", "failed", "cancelled", "expired"):
        assert terminal_status in index_definition

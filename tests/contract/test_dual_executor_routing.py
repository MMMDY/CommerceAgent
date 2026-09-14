"""PostgreSQL contracts for the immutable dual-executor run selection."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def _insert_conversation(engine: Engine) -> tuple[UUID, str]:
    conversation_id = uuid4()
    tenant_id = f"dual-executor-{uuid4()}"
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, 'actor', :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "request_id": str(uuid4()),
                "now": now,
            },
        )
    return conversation_id, tenant_id


def _insert_run(
    engine: Engine,
    *,
    status: str,
    execution_mode: str | None,
    workflow_id: str | None,
    workflow_version: str | None,
) -> UUID:
    conversation_id, tenant_id = _insert_conversation(engine)
    run_id = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO runtime.agent_runs "
                "(run_id, conversation_id, tenant_id, actor_ref, status, execution_mode, "
                "workflow_id, workflow_version, policy_version, model_config_hash, "
                "prompt_version, current_step, step_count, max_steps, deadline_at, "
                "created_at, updated_at) "
                "VALUES (:run_id, :conversation_id, :tenant_id, 'actor', :status, "
                ":execution_mode, :workflow_id, :workflow_version, 'policy', 'model', "
                "'prompt', 'route', 0, 6, :deadline_at, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "status": status,
                "execution_mode": execution_mode,
                "workflow_id": workflow_id,
                "workflow_version": workflow_version,
                "deadline_at": now + timedelta(minutes=5),
                "now": now,
            },
        )
    return run_id


def test_created_and_direct_handoff_runs_allow_no_executor_selection(engine: Engine) -> None:
    _insert_run(
        engine,
        status="created",
        execution_mode=None,
        workflow_id=None,
        workflow_version=None,
    )
    _insert_run(
        engine,
        status="waiting_human",
        execution_mode=None,
        workflow_id=None,
        workflow_version=None,
    )


@pytest.mark.parametrize(
    ("status", "execution_mode", "workflow_id", "workflow_version"),
    (
        ("created", "handoff", "handoff", "1"),
        ("running_readonly", "workflow", "faq", "1"),
        ("running_workflow", "readonly_loop", "refund", "1"),
    ),
)
def test_database_rejects_invalid_execution_mode_shapes(
    engine: Engine,
    status: str,
    execution_mode: str,
    workflow_id: str,
    workflow_version: str,
) -> None:
    with pytest.raises(IntegrityError):
        _insert_run(
            engine,
            status=status,
            execution_mode=execution_mode,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
        )


def test_executor_and_workflow_version_are_immutable_after_selection(engine: Engine) -> None:
    run_id = _insert_run(
        engine,
        status="routing",
        execution_mode=None,
        workflow_id=None,
        workflow_version=None,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE runtime.agent_runs SET execution_mode = 'readonly_loop', "
                "workflow_id = 'faq', workflow_version = '1', status = 'running_readonly' "
                "WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        )
    for assignment in (
        "execution_mode = 'workflow'",
        "workflow_id = 'other'",
        "workflow_version = '2'",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text(f"UPDATE runtime.agent_runs SET {assignment} WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )

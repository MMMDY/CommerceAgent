"""PostgreSQL contracts for durable creation-time run configuration."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.orchestration.run_creation import ExecutionMode, RunCreationSpec
from src.protocols import RunContext, RunStatus
from src.repositories.run_lifecycle import RunLifecycleRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_create_run_persists_every_execution_pin(engine: Engine) -> None:
    now = datetime.now(UTC)
    conversation_id = uuid4()
    run_id = uuid4()
    tenant_id = f"lifecycle-{uuid4()}"
    deadline = now + timedelta(minutes=7)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :actor_id, :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "actor_id": "lifecycle-actor",
                "request_id": str(uuid4()),
                "now": now,
            },
        )

    repository = RunLifecycleRepository(engine)
    repository.create_run(
        context=RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id="lifecycle-actor",
            workflow_id="returns",
            workflow_version="1.0",
            status=RunStatus.CREATED,
        ),
        spec=RunCreationSpec(
            execution_mode=ExecutionMode.WORKFLOW,
            policy_version="policy-2026-09",
            model_config_hash="sha256:model-config-v1",
            prompt_version="returns-prompt-1",
            current_step="classify",
            max_steps=5,
            deadline_at=deadline,
        ),
    )

    created = repository.load_definition(run_id=run_id, tenant_id=tenant_id)
    assert created is not None
    assert created.workflow_id == "returns"
    assert created.workflow_version == "1.0"
    assert created.policy_version == "policy-2026-09"
    assert created.model_config_hash == "sha256:model-config-v1"
    assert created.prompt_version == "returns-prompt-1"
    assert created.execution_mode is ExecutionMode.WORKFLOW
    assert created.current_step == "classify"
    assert created.max_steps == 5
    assert created.deadline_at == deadline
    assert repository.load_definition(run_id=run_id, tenant_id="another-tenant") is None


def test_published_v2_does_not_retarget_existing_v1_run(engine: Engine) -> None:
    now = datetime.now(UTC)
    workflow_id = f"version-lock-{uuid4()}"
    conversation_id = uuid4()
    run_id = uuid4()
    tenant_id = f"version-lock-{uuid4()}"
    v1_hash = f"sha256:{uuid4().hex}{uuid4().hex}"
    v2_hash = f"sha256:{uuid4().hex}{uuid4().hex}"
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
        connection.execute(
            text(
                "INSERT INTO domain.workflow_versions "
                "(workflow_id, version, definition_json, definition_hash, status, created_at, "
                "activated_at) VALUES (:workflow_id, '1.0', CAST(:definition AS jsonb), "
                ":definition_hash, 'active', :now, :now)"
            ),
            {
                "workflow_id": workflow_id,
                "definition": '{"steps":["v1"]}',
                "definition_hash": v1_hash,
                "now": now,
            },
        )

    repository = RunLifecycleRepository(engine)
    repository.create_run(
        context=RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id="actor",
            workflow_id=workflow_id,
            workflow_version="1.0",
            status=RunStatus.CREATED,
        ),
        spec=RunCreationSpec(
            execution_mode=ExecutionMode.WORKFLOW,
            policy_version="policy-v1",
            model_config_hash="sha256:model-v1",
            prompt_version="prompt-v1",
            current_step="v1",
            deadline_at=now + timedelta(minutes=5),
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO domain.workflow_versions "
                "(workflow_id, version, definition_json, definition_hash, status, created_at, "
                "activated_at) VALUES (:workflow_id, '2.0', CAST(:definition AS jsonb), "
                ":definition_hash, 'active', :now, :now)"
            ),
            {
                "workflow_id": workflow_id,
                "definition": '{"steps":["v2"]}',
                "definition_hash": v2_hash,
                "now": now,
            },
        )

    existing = repository.load_definition(run_id=run_id, tenant_id=tenant_id)
    assert existing is not None
    assert existing.workflow_version == "1.0"
    assert existing.current_step == "v1"

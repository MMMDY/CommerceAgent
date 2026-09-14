"""Database-level recovery contracts for runtime checkpoints.

These tests are deliberately opt-in: ``DATABASE_TEST_URL`` must point at an
isolated PostgreSQL database whose migrations have already been applied.  The
test module never reads application configuration or ``.env``.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.orchestration.persistence import RepositoryCheckpointStore
from src.protocols import DomainEvent, EventType, RunContext, RunStatus
from src.repositories.runs import RunRepository, VersionConflictError


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL recovery tests")
    return create_engine(database_url, pool_pre_ping=True)


def _create_run(engine: Engine) -> tuple[RunContext, RunRepository]:
    """Create a self-contained tenant conversation/run for one test."""

    now = datetime.now(UTC)
    run_id = uuid4()
    conversation_id = uuid4()
    tenant_id = f"recovery-{uuid4()}"
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
                "actor_id": "recovery-actor",
                "request_id": str(uuid4()),
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO runtime.agent_runs "
                "(run_id, conversation_id, tenant_id, actor_ref, status, execution_mode, "
                "workflow_id, workflow_version, policy_version, model_config_hash, "
                "prompt_version, current_step, step_count, max_steps, deadline_at, "
                "created_at, updated_at) "
                "VALUES (:run_id, :conversation_id, :tenant_id, :actor_ref, 'running_readonly', "
                "'readonly_loop', 'recovery', '1.0', 'policy-1.0', 'model-hash', 'prompt-1.0', "
                "'start', 0, 6, :deadline_at, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "actor_ref": "recovery-actor",
                "deadline_at": now + timedelta(minutes=5),
                "now": now,
            },
        )
    return (
        RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id="recovery-actor",
            workflow_id="recovery",
            workflow_version="1.0",
            status=RunStatus.RUNNING_READONLY,
        ),
        RunRepository(engine),
    )


def _event(label: str) -> DomainEvent:
    return DomainEvent(event_type=EventType.STEP_COMPLETED, payload={"label": label})


def test_checkpoint_survives_store_recreation_and_replays_latest_context(engine: Engine) -> None:
    context, repository = _create_run(engine)
    original_store = RepositoryCheckpointStore(repository)
    checkpoint_version = original_store.checkpoint(
        context=context,
        status=RunStatus.WAITING_USER,
        next_step="collect_order_id",
        state={"awaiting": "order_id", "safe_counter": 1},
        events=(_event("persist-before-crash"),),
    )
    assert checkpoint_version == 1

    # A reconstructed process must recover solely from durable state.
    recovered = RepositoryCheckpointStore(RunRepository(engine)).resume(
        run_id=context.run_id, tenant_id=context.tenant_id
    )
    assert recovered is not None
    assert recovered.run_id == context.run_id
    assert recovered.conversation_id == context.conversation_id
    assert recovered.workflow_id == "recovery"
    assert recovered.workflow_version == "1.0"
    assert recovered.status is RunStatus.WAITING_USER
    assert recovered.state == {"awaiting": "order_id", "safe_counter": 1}
    assert recovered.step_count == 1
    assert recovered.checkpoint_version == 1

    # Recovery is tenant-scoped even when the run UUID is known.
    assert (
        RepositoryCheckpointStore(RunRepository(engine)).resume(
            run_id=context.run_id, tenant_id=f"other-{context.tenant_id}"
        )
        is None
    )


def test_concurrent_checkpoint_advance_commits_one_complete_unit(engine: Engine) -> None:
    context, repository = _create_run(engine)

    def advance() -> str:
        store = RepositoryCheckpointStore(RunRepository(engine))
        try:
            store.checkpoint(
                context=context,
                status=RunStatus.RUNNING_READONLY,
                next_step="observe",
                state={"attempt": "same-base-version"},
                events=(_event("concurrent-advance"),),
            )
        except VersionConflictError:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: advance(), range(2)))

    assert sorted(results) == ["committed", "conflict"]
    snapshot = repository.load_run(run_id=context.run_id, tenant_id=context.tenant_id)
    assert snapshot is not None
    assert snapshot.row_version == 1
    assert snapshot.last_checkpoint_seq == 1

    restored = RepositoryCheckpointStore(repository).resume(
        run_id=context.run_id, tenant_id=context.tenant_id
    )
    assert restored is not None
    assert restored.checkpoint_version == 1
    assert restored.step_count == 1
    with engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM runtime.run_events WHERE run_id = :run_id), "
                "(SELECT count(*) FROM runtime.run_checkpoints WHERE run_id = :run_id)"
            ),
            {"run_id": context.run_id},
        ).one()
    assert tuple(counts) == (1, 1)

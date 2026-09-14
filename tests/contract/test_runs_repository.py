"""Integration contracts for atomic, tenant-scoped run persistence.

These tests intentionally require an explicitly supplied isolated PostgreSQL
database.  They never silently select the developer's default application DB.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from src.repositories.runs import RunRepository, VersionConflictError


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


@pytest.fixture
def repository(engine: Engine) -> RunRepository:
    return RunRepository(engine)


def _create_run(
    engine: Engine,
    *,
    tenant_id: str | None = None,
    status: str = "running_readonly",
    execution_mode: str = "readonly_loop",
) -> tuple[UUID, str]:
    """Create one isolated conversation/run using only the runtime role."""

    now = datetime.now(UTC)
    tenant = tenant_id or f"contract-{uuid4()}"
    conversation_id = uuid4()
    run_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :actor_id, :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant,
                "actor_id": "contract-actor",
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
                "VALUES (:run_id, :conversation_id, :tenant_id, :actor_ref, :status, "
                ":execution_mode, 'contract', '1.0', 'policy-1.0', 'model-hash', 'prompt-1.0', "
                "'start', 0, 6, :deadline_at, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant,
                "actor_ref": "contract-actor",
                "status": status,
                "execution_mode": execution_mode,
                "deadline_at": now + timedelta(minutes=5),
                "now": now,
            },
        )
    return run_id, tenant


def _event(*, event_id: UUID | None = None) -> dict[str, object]:
    return {
        "event_id": event_id or uuid4(),
        "event_type": "step_completed",
        "step_id": "contract_step",
        "payload": '{"outcome":"ok"}',
        "payload_hash": "event-hash",
        "correlation_id": uuid4(),
    }


def _commit(repository: RunRepository, *, run_id: UUID, tenant_id: str, version: int) -> None:
    repository.commit_step(
        run_id=run_id,
        tenant_id=tenant_id,
        expected_version=version,
        next_status="running_readonly",
        next_step="contract_step",
        checkpoint={"contract": "state"},
        checkpoint_hash="checkpoint-hash",
        events=[_event()],
    )


def test_commit_step_writes_events_checkpoint_and_run_as_one_unit(
    engine: Engine, repository: RunRepository
) -> None:
    run_id, tenant_id = _create_run(engine)

    snapshot = repository.commit_step(
        run_id=run_id,
        tenant_id=tenant_id,
        expected_version=0,
        next_status="running_readonly",
        next_step="contract_step",
        checkpoint={"contract": "state"},
        checkpoint_hash="checkpoint-hash",
        events=[_event(), _event()],
    )

    assert snapshot.row_version == 1
    assert snapshot.last_checkpoint_seq == 1
    with engine.connect() as connection:
        checkpoint = connection.execute(
            text(
                "SELECT checkpoint_seq, event_from_seq, event_to_seq "
                "FROM runtime.run_checkpoints WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        ).one()
        event_count = connection.execute(
            text("SELECT count(*) FROM runtime.run_events WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).scalar_one()
    assert tuple(checkpoint) == (1, 1, 2)
    assert event_count == 2


def test_commit_step_rolls_back_every_write_when_event_insert_fails(
    engine: Engine, repository: RunRepository
) -> None:
    other_run_id, other_tenant_id = _create_run(engine)
    duplicate_event_id = uuid4()
    repository.commit_step(
        run_id=other_run_id,
        tenant_id=other_tenant_id,
        expected_version=0,
        next_status="running_readonly",
        next_step="contract_step",
        checkpoint={"contract": "first"},
        checkpoint_hash="checkpoint-hash",
        events=[_event(event_id=duplicate_event_id)],
    )
    run_id, tenant_id = _create_run(engine)

    with pytest.raises(IntegrityError):
        repository.commit_step(
            run_id=run_id,
            tenant_id=tenant_id,
            expected_version=0,
            next_status="running_readonly",
            next_step="contract_step",
            checkpoint={"contract": "must-roll-back"},
            checkpoint_hash="checkpoint-hash",
            events=[_event(event_id=duplicate_event_id)],
        )

    snapshot = repository.load_run(run_id=run_id, tenant_id=tenant_id)
    assert snapshot is not None
    assert snapshot.row_version == 0
    assert snapshot.last_checkpoint_seq == 0
    with engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM runtime.run_events WHERE run_id = :run_id), "
                "(SELECT count(*) FROM runtime.run_checkpoints WHERE run_id = :run_id)"
            ),
            {"run_id": run_id},
        ).one()
    assert tuple(counts) == (0, 0)


def test_concurrent_commits_allow_exactly_one_expected_version(
    engine: Engine, repository: RunRepository
) -> None:
    run_id, tenant_id = _create_run(engine)

    def attempt() -> str:
        try:
            _commit(repository, run_id=run_id, tenant_id=tenant_id, version=0)
        except VersionConflictError:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    assert sorted(results) == ["committed", "conflict"]
    snapshot = repository.load_run(run_id=run_id, tenant_id=tenant_id)
    assert snapshot is not None
    assert snapshot.row_version == 1


def test_other_tenant_cannot_load_or_advance_run(engine: Engine, repository: RunRepository) -> None:
    run_id, tenant_id = _create_run(engine)
    assert repository.load_run(run_id=run_id, tenant_id=f"other-{tenant_id}") is None
    with pytest.raises(VersionConflictError):
        _commit(repository, run_id=run_id, tenant_id=f"other-{tenant_id}", version=0)
    snapshot = repository.load_run(run_id=run_id, tenant_id=tenant_id)
    assert snapshot is not None
    assert snapshot.row_version == 0


def test_checkpoint_requires_a_domain_event(engine: Engine, repository: RunRepository) -> None:
    run_id, tenant_id = _create_run(engine)
    with pytest.raises(ValueError, match="domain event"):
        repository.commit_step(
            run_id=run_id,
            tenant_id=tenant_id,
            expected_version=0,
            next_status="running_readonly",
            next_step="contract_step",
            checkpoint={"contract": "state"},
            checkpoint_hash="checkpoint-hash",
            events=[],
        )

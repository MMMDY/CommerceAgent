"""PostgreSQL recovery contract for mutation outcome + checkpoint + outbox.

These tests only use an explicitly supplied isolated ``DATABASE_TEST_URL``.
They do not read application configuration or ``.env``.
"""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from src.mutation_safety import (
    MutationAdapterResult,
    MutationAdapterStatus,
    MutationCompletion,
    MutationExecutionIntent,
    MutationExecutionStatus,
)
from src.orchestration.mutation_execution import DurableMutationBoundary
from src.orchestration.persistence import RepositoryCheckpointStore
from src.protocols import DomainEvent, EventType, RunContext, RunStatus
from src.repositories.mutations import MutationExecutionRepository
from src.repositories.runs import OutboxMessage, RunRepository
from tests.contract.test_runs_repository import _create_run, _event


class SimulatedProcessCrash(BaseException):
    pass


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL recovery tests")
    return create_engine(database_url, pool_pre_ping=True)


def _reserved_intent(
    engine: Engine, *, run_id: UUID, tenant_id: str
) -> tuple[MutationExecutionIntent, MutationExecutionRepository]:
    intent = MutationExecutionIntent(
        record_id=uuid4(),
        tenant_id=tenant_id,
        operation="commit_refund",
        request_fingerprint=f"sha256:{run_id}",
    )
    repository = MutationExecutionRepository(engine)
    repository.reserve(intent)
    return intent, repository


def _checkpoint(
    *,
    run_repository: RunRepository,
    run_id: UUID,
    tenant_id: str,
    completion: MutationCompletion,
    event: dict[str, object],
) -> None:
    run_repository.commit_step(
        run_id=run_id,
        tenant_id=tenant_id,
        expected_version=0,
        next_status="verifying",
        next_step="verify_mutation",
        checkpoint={"mutation_status": completion.status.value},
        checkpoint_hash="sha256:checkpoint",
        events=[event],
        mutation_completion=completion,
        outbox_messages=(
            OutboxMessage(
                event_id=cast(UUID, event["event_id"]),
                topic="mutation.observed",
                payload_redacted={"status": completion.status.value},
            ),
        ),
    )


def _run_context(engine: Engine, *, run_id: UUID, tenant_id: str) -> RunContext:
    with engine.connect() as connection:
        conversation_id = connection.execute(
            text(
                "SELECT conversation_id FROM runtime.agent_runs "
                "WHERE run_id = :run_id AND tenant_id = :tenant_id"
            ),
            {"run_id": run_id, "tenant_id": tenant_id},
        ).scalar_one()
    return RunContext(
        run_id=run_id,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        actor_id="contract-actor",
        workflow_id="contract",
        workflow_version="1.0",
        status=RunStatus.COMMITTING,
    )


def test_crash_after_adapter_recovers_unknown_without_second_side_effect(engine: Engine) -> None:
    run_id, tenant_id = _create_run(
        engine, status="running_workflow", execution_mode="workflow"
    )
    intent, intent_repository = _reserved_intent(engine, run_id=run_id, tenant_id=tenant_id)
    boundary = DurableMutationBoundary(intent_repository)
    adapter_calls = 0

    def adapter(key: str) -> MutationAdapterResult:
        nonlocal adapter_calls
        adapter_calls += 1
        assert key == str(intent.record_id)
        return MutationAdapterResult(status=MutationAdapterStatus.SUCCEEDED)

    with pytest.raises(SimulatedProcessCrash):
        boundary.execute(
            intent=intent,
            adapter=adapter,
            checkpoint=lambda _: None,
            after_adapter=lambda: (_ for _ in ()).throw(SimulatedProcessCrash()),
        )

    checkpoint_store = RepositoryCheckpointStore(RunRepository(engine))
    context = _run_context(engine, run_id=run_id, tenant_id=tenant_id)

    def checkpoint_unknown(completion: MutationCompletion) -> None:
        checkpoint_store.checkpoint_mutation(
            context=context,
            status=RunStatus.VERIFYING,
            next_step="verify_mutation",
            state={"mutation_status": completion.status.value},
            events=(
                DomainEvent(
                    event_type=EventType.TOOL_OBSERVED,
                    payload={"status": completion.status.value},
                ),
            ),
            completion=completion,
        )

    recovered = boundary.recover(
        intent=intent,
        checkpoint=checkpoint_unknown,
    )
    replay = boundary.execute(
        intent=intent, adapter=adapter, checkpoint=lambda _: pytest.fail("unexpected checkpoint")
    )

    assert recovered.status is MutationExecutionStatus.UNKNOWN
    assert replay.status is MutationExecutionStatus.UNKNOWN
    assert adapter_calls == 1
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT i.status, r.last_checkpoint_seq, "
                "(SELECT count(*) FROM runtime.runtime_outbox WHERE run_id = :run_id) "
                "FROM runtime.idempotency_records i CROSS JOIN runtime.agent_runs r "
                "WHERE i.idempotency_record_id = :record_id AND r.run_id = :run_id"
            ),
            {"record_id": intent.record_id, "run_id": run_id},
        ).one()
    assert tuple(row) == ("unknown", 1, 1)


def test_failed_checkpoint_rolls_back_mutation_completion_and_outbox(engine: Engine) -> None:
    other_run_id, other_tenant_id = _create_run(engine)
    duplicate_event = _event()
    RunRepository(engine).commit_step(
        run_id=other_run_id,
        tenant_id=other_tenant_id,
        expected_version=0,
        next_status="running_readonly",
        next_step="seed",
        checkpoint={"seed": True},
        checkpoint_hash="sha256:seed",
        events=[duplicate_event],
    )

    run_id, tenant_id = _create_run(
        engine, status="running_workflow", execution_mode="workflow"
    )
    intent, intent_repository = _reserved_intent(engine, run_id=run_id, tenant_id=tenant_id)
    claim = intent_repository.claim(intent)
    assert claim.acquired is True
    assert claim.execution.status is MutationExecutionStatus.IN_PROGRESS
    completion = MutationCompletion(
        record_id=intent.record_id,
        request_fingerprint=intent.request_fingerprint,
        status=MutationExecutionStatus.SUCCEEDED,
        response_redacted={"state": "accepted"},
    )

    with pytest.raises(IntegrityError):
        _checkpoint(
            run_repository=RunRepository(engine),
            run_id=run_id,
            tenant_id=tenant_id,
            completion=completion,
            event=duplicate_event,
        )

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT i.status, r.last_checkpoint_seq, "
                "(SELECT count(*) FROM runtime.runtime_outbox WHERE run_id = :run_id) "
                "FROM runtime.idempotency_records i CROSS JOIN runtime.agent_runs r "
                "WHERE i.idempotency_record_id = :record_id AND r.run_id = :run_id"
            ),
            {"record_id": intent.record_id, "run_id": run_id},
        ).one()
    assert tuple(row) == ("in_progress", 0, 0)

"""Opt-in PostgreSQL contracts for safe run-event replay after recovery.

``DATABASE_TEST_URL`` must identify an isolated, migrated PostgreSQL database.
This module intentionally never reads the normal application database or ``.env``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.orchestration.persistence import RepositoryCheckpointStore
from src.protocols import DomainEvent, EventType, RunContext, RunStatus
from src.repositories.runs import EventReplayError, RunRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL recovery tests")
    return create_engine(database_url, pool_pre_ping=True)


def _create_run(engine: Engine) -> RunContext:
    now = datetime.now(UTC)
    run_id = uuid4()
    conversation_id = uuid4()
    tenant_id = f"event-replay-{uuid4()}"
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
                "actor_id": "event-replay-actor",
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
                "VALUES (:run_id, :conversation_id, :tenant_id, :actor_ref, "
                "'running_readonly', 'readonly', 'event-replay', '1.0', 'policy-1.0', "
                "'model-hash', 'prompt-1.0', 'start', 0, 6, :deadline_at, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "actor_ref": "event-replay-actor",
                "deadline_at": now + timedelta(minutes=5),
                "now": now,
            },
        )
    return RunContext(
        run_id=run_id,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        actor_id="event-replay-actor",
        workflow_id="event-replay",
        workflow_version="1.0",
        status=RunStatus.RUNNING_READONLY,
    )


def _checkpoint(store: RepositoryCheckpointStore, context: RunContext, label: str) -> None:
    store.checkpoint(
        context=context,
        status=RunStatus.RUNNING_READONLY,
        next_step="observe",
        state={"last_label": label},
        events=(DomainEvent(event_type=EventType.STEP_COMPLETED, payload={"label": label}),),
    )


def _hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def test_recreated_repository_replays_ordered_tenant_page(engine: Engine) -> None:
    context = _create_run(engine)
    store = RepositoryCheckpointStore(RunRepository(engine))
    _checkpoint(store, context, "first")
    recovered = store.resume(run_id=context.run_id, tenant_id=context.tenant_id)
    assert recovered is not None
    _checkpoint(store, recovered, "second")

    # Simulate process reconstruction: no state from the original repository is reused.
    repository = RunRepository(engine)
    all_events = repository.replay_events(run_id=context.run_id, tenant_id=context.tenant_id)
    remaining = repository.replay_events(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
        after_sequence=1,
        limit=1,
    )

    assert [event.sequence for event in all_events] == [1, 2]
    assert [event.event.payload for event in all_events] == [
        {"label": "first"},
        {"label": "second"},
    ]
    assert [event.sequence for event in remaining] == [2]
    assert (
        repository.replay_events(
            run_id=context.run_id,
            tenant_id=f"other-{context.tenant_id}",
        )
        == ()
    )


@pytest.mark.parametrize(
    ("column_update", "expected_error"),
    [
        ("event_version = '2.0'", "unsupported persisted event version"),
        ("event_type = 'unknown_event'", "domain event contract"),
    ],
)
def test_persisted_contract_corruption_fails_closed(
    engine: Engine, column_update: str, expected_error: str
) -> None:
    context = _create_run(engine)
    _checkpoint(RepositoryCheckpointStore(RunRepository(engine)), context, "corrupt")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE runtime.run_events SET {column_update} "
                "WHERE run_id = :run_id AND event_seq = 1"
            ),
            {"run_id": context.run_id},
        )

    with pytest.raises(EventReplayError, match=expected_error):
        RunRepository(engine).replay_events(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
        )


def test_unredacted_database_payload_never_crosses_replay_boundary(engine: Engine) -> None:
    context = _create_run(engine)
    _checkpoint(RepositoryCheckpointStore(RunRepository(engine)), context, "safe")
    unsafe_payload = {"confirmation_token": "plaintext-token"}
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE runtime.run_events SET payload_json = CAST(:payload AS jsonb), "
                "payload_hash = :payload_hash WHERE run_id = :run_id AND event_seq = 1"
            ),
            {
                "payload": json.dumps(unsafe_payload),
                "payload_hash": _hash(unsafe_payload),
                "run_id": context.run_id,
            },
        )

    with pytest.raises(EventReplayError, match="not redacted"):
        RunRepository(engine).replay_events(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
        )


def test_sequence_gap_is_detected_instead_of_silently_replayed(engine: Engine) -> None:
    context = _create_run(engine)
    _checkpoint(RepositoryCheckpointStore(RunRepository(engine)), context, "first")
    with engine.begin() as connection:
        event_id: UUID = connection.execute(
            text(
                "SELECT event_id FROM runtime.run_events WHERE run_id = :run_id AND event_seq = 1"
            ),
            {"run_id": context.run_id},
        ).scalar_one()
        connection.execute(
            text("UPDATE runtime.run_events SET event_seq = 2 WHERE event_id = :event_id"),
            {"event_id": event_id},
        )

    with pytest.raises(EventReplayError, match="sequence contains a gap"):
        RunRepository(engine).replay_events(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
        )

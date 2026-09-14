"""Tenant-scoped runtime persistence with optimistic checkpoint commits."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.mutation_safety import MutationCompletion, MutationExecutionStatus


class VersionConflictError(RuntimeError):
    """Raised when another worker advanced the same run first."""


class MutationCompletionConflictError(RuntimeError):
    """The durable mutation intent cannot be completed by this checkpoint."""


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    event_id: UUID
    topic: str
    payload_redacted: dict[str, Any]
    outbox_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: UUID
    tenant_id: str
    status: str
    current_step: str
    row_version: int
    last_checkpoint_seq: int


class RunRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_run(self, *, run_id: UUID, tenant_id: str) -> RunSnapshot | None:
        statement = text(
            "SELECT run_id, tenant_id, status, current_step, row_version, last_checkpoint_seq "
            "FROM runtime.agent_runs WHERE run_id = :run_id AND tenant_id = :tenant_id"
        )
        with self._engine.connect() as connection:
            row = connection.execute(
                statement,
                {"run_id": run_id, "tenant_id": tenant_id},
            ).one_or_none()
        return RunSnapshot(**dict(row._mapping)) if row is not None else None

    def commit_step(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        expected_version: int,
        next_status: str,
        next_step: str,
        checkpoint: dict[str, Any],
        checkpoint_hash: str,
        events: list[dict[str, Any]],
        mutation_completion: MutationCompletion | None = None,
        outbox_messages: tuple[OutboxMessage, ...] = (),
    ) -> RunSnapshot:
        """Commit events, mutation outcome, outbox, checkpoint, and run atomically."""

        if not events:
            raise ValueError("a checkpoint commit must include at least one domain event")
        event_ids = {event.get("event_id") for event in events}
        if any(message.event_id not in event_ids for message in outbox_messages):
            raise ValueError("an outbox message must reference an event in the same checkpoint")
        if mutation_completion is not None and mutation_completion.status not in {
            MutationExecutionStatus.SUCCEEDED,
            MutationExecutionStatus.FAILED,
            MutationExecutionStatus.UNKNOWN,
        }:
            raise ValueError("mutation completion must be a terminal observation")

        with self._engine.begin() as connection:
            current = connection.execute(
                text(
                    "SELECT last_checkpoint_seq FROM runtime.agent_runs "
                    "WHERE run_id = :run_id AND tenant_id = :tenant_id "
                    "AND row_version = :version FOR UPDATE"
                ),
                {"run_id": run_id, "tenant_id": tenant_id, "version": expected_version},
            ).one_or_none()
            if current is None:
                raise VersionConflictError("run is unavailable or stale")
            if mutation_completion is not None:
                changed_mutation = connection.execute(
                    text(
                        "UPDATE runtime.idempotency_records SET status = :mutation_status, "
                        "business_reference = :business_reference, "
                        "response_redacted_json = CAST(:response AS jsonb), updated_at = now(), "
                        "row_version = row_version + 1 "
                        "WHERE idempotency_record_id = :record_id AND tenant_id = :tenant_id "
                        "AND request_fingerprint = :request_fingerprint "
                        "AND status = 'in_progress'"
                    ),
                    {
                        "mutation_status": mutation_completion.status.value,
                        "business_reference": mutation_completion.business_reference,
                        "response": json.dumps(mutation_completion.response_redacted),
                        "record_id": mutation_completion.record_id,
                        "tenant_id": tenant_id,
                        "request_fingerprint": mutation_completion.request_fingerprint,
                    },
                )
                if changed_mutation.rowcount != 1:
                    raise MutationCompletionConflictError(
                        "mutation intent is unavailable, stale, or already completed"
                    )
            checkpoint_sequence = current.last_checkpoint_seq + 1
            last_event_sequence = connection.execute(
                text(
                    "SELECT COALESCE(MAX(event_seq), 0) FROM runtime.run_events "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).scalar_one()
            event_from_sequence = last_event_sequence + 1
            for offset, event in enumerate(events, start=1):
                connection.execute(
                    text(
                        "INSERT INTO runtime.run_events "
                        "(event_id, run_id, event_seq, event_type, event_version, step_id, "
                        "payload_json, payload_hash, correlation_id, created_at) "
                        "VALUES (:event_id, :run_id, :event_seq, :event_type, '1.0', :step_id, "
                        "CAST(:payload AS jsonb), :payload_hash, :correlation_id, now())"
                    ),
                    {
                        **event,
                        "run_id": run_id,
                        "event_seq": event_from_sequence + offset - 1,
                    },
                )
            for message in outbox_messages:
                connection.execute(
                    text(
                        "INSERT INTO runtime.runtime_outbox "
                        "(outbox_id, run_id, event_id, topic, payload_redacted_json, "
                        "available_at, created_at) "
                        "VALUES (:outbox_id, :run_id, :event_id, :topic, "
                        "CAST(:payload AS jsonb), now(), now())"
                    ),
                    {
                        "outbox_id": message.outbox_id,
                        "run_id": run_id,
                        "event_id": message.event_id,
                        "topic": message.topic,
                        "payload": json.dumps(message.payload_redacted),
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO runtime.run_checkpoints "
                    "(run_id, checkpoint_seq, schema_version, step_id, state_json, state_hash, "
                    "event_from_seq, event_to_seq, created_at) "
                    "VALUES (:run_id, :seq, '1.0', :step, CAST(:state AS jsonb), :state_hash, "
                    ":event_from, :event_to, now())"
                ),
                {
                    "run_id": run_id,
                    "seq": checkpoint_sequence,
                    "step": next_step,
                    "state": json.dumps(checkpoint),
                    "state_hash": checkpoint_hash,
                    "event_from": event_from_sequence,
                    "event_to": event_from_sequence + len(events) - 1,
                },
            )
            changed = connection.execute(
                text(
                    "UPDATE runtime.agent_runs SET status = :status, current_step = :step, "
                    "step_count = step_count + 1, last_checkpoint_seq = :seq, "
                    "row_version = row_version + 1, updated_at = now() "
                    "WHERE run_id = :run_id AND tenant_id = :tenant_id AND row_version = :version"
                ),
                {
                    "status": next_status,
                    "step": next_step,
                    "seq": checkpoint_sequence,
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "version": expected_version,
                },
            )
            if changed.rowcount != 1:
                raise VersionConflictError("run was updated concurrently")
        snapshot = self.load_run(run_id=run_id, tenant_id=tenant_id)
        if snapshot is None:
            raise VersionConflictError("run disappeared after commit")
        return snapshot

    def load_latest_checkpoint(self, *, run_id: UUID, tenant_id: str) -> dict[str, Any] | None:
        """Load only the latest tenant-owned checkpoint for crash recovery."""

        statement = text(
            "SELECT checkpoint.state_json FROM runtime.run_checkpoints AS checkpoint "
            "JOIN runtime.agent_runs AS run ON run.run_id = checkpoint.run_id "
            "WHERE checkpoint.run_id = :run_id AND run.tenant_id = :tenant_id "
            "ORDER BY checkpoint.checkpoint_seq DESC LIMIT 1"
        )
        with self._engine.connect() as connection:
            state = connection.execute(
                statement, {"run_id": run_id, "tenant_id": tenant_id}
            ).scalar_one_or_none()
        if state is None:
            return None
        if isinstance(state, str):
            state = json.loads(state)
        if not isinstance(state, dict):
            raise ValueError("persisted checkpoint is not an object")
        return state

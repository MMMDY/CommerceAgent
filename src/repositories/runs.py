"""Tenant-scoped runtime persistence with optimistic checkpoint commits."""

# ruff: noqa: E501

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from math import isfinite
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.mutation_safety import MutationCompletion, MutationExecutionStatus
from src.protocols import SCHEMA_VERSION, DomainEvent, EventType

_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)")
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "secret",
        "password",
        "confirmation_token",
        "chain_of_thought",
        "reasoning",
        "hidden_reasoning",
    }
)
_MAX_EVENT_PAYLOAD_DEPTH = 32
_MAX_EVENT_PAYLOAD_NODES = 10_000


class VersionConflictError(RuntimeError):
    """Raised when another worker advanced the same run first."""


class MutationCompletionConflictError(RuntimeError):
    """The durable mutation intent cannot be completed by this checkpoint."""


class EventReplayError(ValueError):
    """A persisted event cannot be replayed through the safe event boundary."""


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
    conversation_id: UUID | None = None
    step_count: int = 0
    terminal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayedRunEvent:
    """Strictly decoded, tenant-authorized append-only run event."""

    event_id: UUID
    run_id: UUID
    sequence: int
    step_id: str
    correlation_id: UUID
    causation_id: UUID | None
    occurred_at: datetime
    payload_hash: str
    event: DomainEvent

    @classmethod
    def from_persisted_row(cls, row: Mapping[str, Any]) -> ReplayedRunEvent:
        """Validate database values before exposing an event to runtime/API code."""

        event_id = _require_uuid(row, "event_id")
        run_id = _require_uuid(row, "run_id")
        sequence = _require_int(row, "event_seq", minimum=1)
        event_version = _require_string(row, "event_version", maximum=16)
        if event_version != SCHEMA_VERSION:
            raise EventReplayError("unsupported persisted event version")
        step_id = _require_string(row, "step_id", maximum=64)
        correlation_id = _require_uuid(row, "correlation_id")
        causation_id = row.get("causation_id")
        if causation_id is not None and not isinstance(causation_id, UUID):
            raise EventReplayError("persisted causation_id is not a UUID")
        occurred_at = row.get("created_at")
        if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
            raise EventReplayError("persisted event timestamp must be timezone-aware")

        payload = _decode_payload(row.get("payload_json"))
        _assert_safe_payload(payload)
        payload_hash = _require_string(row, "payload_hash", maximum=80)
        if not _HASH_PATTERN.fullmatch(payload_hash):
            raise EventReplayError("persisted event hash has an unsupported format")
        expected_hash = _payload_hash(payload)
        if payload_hash != expected_hash:
            raise EventReplayError("persisted event payload hash mismatch")

        try:
            event_type = EventType(_require_string(row, "event_type", maximum=64))
            event = DomainEvent.model_validate(
                {
                    "schema_version": event_version,
                    "event_type": event_type,
                    "payload": payload,
                },
                strict=True,
            )
        except ValueError as exc:
            raise EventReplayError("persisted event violates the domain event contract") from exc
        return cls(
            event_id=event_id,
            run_id=run_id,
            sequence=sequence,
            step_id=step_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            payload_hash=payload_hash,
            event=event,
        )


class RunRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_run(self, *, run_id: UUID, tenant_id: str) -> RunSnapshot | None:
        statement = text(
            "SELECT run_id, tenant_id, status, current_step, row_version, last_checkpoint_seq, "
            "conversation_id, step_count, terminal_reason "
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

    def replay_events(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> tuple[ReplayedRunEvent, ...]:
        """Return an ordered, tenant-scoped page of verified run events.

        A missing run and a run owned by another tenant intentionally produce the
        same empty result. Persisted corruption, sequence gaps, unknown event
        versions/types, and payloads that cross the redaction boundary fail closed.
        """

        if not isinstance(run_id, UUID):
            raise ValueError("run_id must be a UUID")
        if not tenant_id or len(tenant_id) > 64:
            raise ValueError("tenant_id must contain between 1 and 64 characters")
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int):
            raise ValueError("after_sequence must be an integer")
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        statement = text(
            "SELECT event.event_id, event.run_id, event.event_seq, event.event_type, "
            "event.event_version, event.step_id, event.payload_json, event.payload_hash, "
            "event.causation_id, event.correlation_id, event.created_at "
            "FROM runtime.run_events AS event "
            "JOIN runtime.agent_runs AS run ON run.run_id = event.run_id "
            "WHERE event.run_id = :run_id AND run.tenant_id = :tenant_id "
            "AND event.event_seq > :after_sequence "
            "ORDER BY event.event_seq ASC LIMIT :limit"
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "after_sequence": after_sequence,
                    "limit": limit,
                },
            ).all()
        events = tuple(ReplayedRunEvent.from_persisted_row(dict(row._mapping)) for row in rows)
        for expected, event in enumerate(events, start=after_sequence + 1):
            if event.sequence != expected:
                raise EventReplayError("persisted event sequence contains a gap")
            if event.run_id != run_id:
                raise EventReplayError("persisted event belongs to an unexpected run")
        return events


def _decode_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EventReplayError("persisted event payload is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise EventReplayError("persisted event payload is not an object")
    return raw


def _assert_safe_payload(payload: dict[str, Any]) -> None:
    node_count = 0

    def visit(value: Any, *, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > _MAX_EVENT_PAYLOAD_NODES:
            raise EventReplayError("persisted event payload is too large")
        if depth > _MAX_EVENT_PAYLOAD_DEPTH:
            raise EventReplayError("persisted event payload is too deeply nested")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise EventReplayError("persisted event payload contains a non-string key")
                if key.lower() in _FORBIDDEN_PAYLOAD_KEYS and item != "[REDACTED]":
                    raise EventReplayError("persisted event payload is not redacted")
                visit(item, depth=depth + 1)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth=depth + 1)
            return
        if isinstance(value, str):
            if _PHONE_PATTERN.search(value):
                raise EventReplayError("persisted event payload contains unredacted PII")
            return
        if value is None or isinstance(value, bool | int):
            return
        if isinstance(value, float) and isfinite(value):
            return
        raise EventReplayError("persisted event payload contains a non-JSON value")

    visit(payload, depth=0)


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def _require_uuid(row: Mapping[str, Any], name: str) -> UUID:
    value = row.get(name)
    if not isinstance(value, UUID):
        raise EventReplayError(f"persisted {name} is not a UUID")
    return value


def _require_int(row: Mapping[str, Any], name: str, *, minimum: int) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EventReplayError(f"persisted {name} is invalid")
    return value


def _require_string(row: Mapping[str, Any], name: str, *, maximum: int) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise EventReplayError(f"persisted {name} is invalid")
    return value

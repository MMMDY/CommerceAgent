"""Append-only, tenant-scoped audit event persistence."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class AuditEvent:
    audit_event_id: UUID
    tenant_id: str | None
    actor_ref: str | None
    event_type: str
    payload: dict[str, object]


class AuditRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, *, tenant_id: str | None, actor_ref: str | None, event_type: str,
               payload: dict[str, object], payload_hash: str) -> UUID:
        event_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO audit.audit_events "
                "(audit_event_id, tenant_id, actor_ref, event_type, payload_redacted_json, payload_hash, created_at) "
                "VALUES (:event_id, :tenant_id, :actor_ref, :event_type, CAST(:payload AS jsonb), :payload_hash, now())"),
                {"event_id": event_id, "tenant_id": tenant_id, "actor_ref": actor_ref,
                 "event_type": event_type, "payload": json.dumps(payload), "payload_hash": payload_hash})
        return event_id

    def for_tenant(self, *, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        if not 1 <= limit <= 500:
            raise ValueError("invalid audit limit")
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT audit_event_id, tenant_id, actor_ref, event_type, payload_redacted_json "
                "FROM audit.audit_events WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit"),
                {"tenant_id": tenant_id, "limit": limit}).all()
        return [AuditEvent(*tuple(row)) for row in rows]

    def recent_safety_p0(self, *, tenant_id: str, limit: int = 50) -> list[dict[str, object]]:
        """Return only redacted P0 safety audit projections for an admin drill-down.

        The event payload is written by the safety boundary and contains IDs,
        taxonomy and detector metadata only.  Filtering by event type and
        tenant in SQL keeps the endpoint from becoming a general audit dump.
        """

        if not 1 <= limit <= 200:
            raise ValueError("invalid safety audit limit")
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT audit_event_id, event_type, payload_redacted_json, created_at "
                    "FROM audit.audit_events "
                    "WHERE tenant_id = :tenant_id AND event_type = 'safety_p0_detected' "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"tenant_id": tenant_id, "limit": limit},
            ).mappings().all()
        allowed = {"run_id", "category", "reason_code", "detector_version", "disposition"}
        return [
            {
                "audit_event_id": str(row["audit_event_id"]),
                "event_type": row["event_type"],
                "created_at": row["created_at"].isoformat(),
                "payload": {
                    key: value
                    for key, value in dict(row["payload_redacted_json"] or {}).items()
                    if key in allowed
                },
            }
            for row in rows
        ]

    def latest_evaluation_approval(
        self, *, tenant_id: str, eval_run_id: str
    ) -> dict[str, object] | None:
        """Return the latest redacted human approval decision for an evaluation.

        Approval decisions are append-only audit events so an evaluation report
        remains immutable.  Only the allowlisted decision projection crosses
        this repository boundary; the approver's free-form reason is retained
        as a one-way hash.
        """

        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT audit_event_id, actor_ref, payload_redacted_json, created_at "
                    "FROM audit.audit_events "
                    "WHERE tenant_id = :tenant_id "
                    "AND event_type = 'evaluation_human_approval' "
                    "AND payload_redacted_json->>'eval_run_id' = :eval_run_id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id, "eval_run_id": eval_run_id},
            ).mappings().first()
        if row is None:
            return None
        payload = dict(row["payload_redacted_json"] or {})
        allowed = {
            "eval_run_id",
            "decision",
            "status",
            "reason_hash",
            "idempotency_key",
        }
        return {
            "approval_id": str(row["audit_event_id"]),
            "approver_ref": row["actor_ref"],
            "decided_at": row["created_at"].isoformat(),
            **{key: payload[key] for key in allowed if key in payload},
        }

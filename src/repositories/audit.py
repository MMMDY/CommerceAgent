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

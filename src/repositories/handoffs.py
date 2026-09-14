"""Tenant-scoped human handoff tickets for uncertain mutation outcomes."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class HandoffTicket:
    ticket_id: UUID
    run_id: UUID
    tenant_id: str
    actor_ref: str
    reason_code: str
    status: str
    operation: str | None
    details: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None
    resolution: str | None


class HandoffRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        actor_ref: str,
        reason_code: str,
        operation: str | None,
        details: dict[str, object],
    ) -> UUID:
        ticket_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.handoff_tickets "
                    "(ticket_id, run_id, tenant_id, actor_ref, reason_code, status, operation, "
                    "details_redacted_json, created_at) VALUES (:ticket_id, :run_id, :tenant_id, "
                    ":actor_ref, :reason_code, 'open', :operation, CAST(:details AS jsonb), now())"
                ),
                {
                    "ticket_id": ticket_id,
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "reason_code": reason_code,
                    "operation": operation,
                    "details": _json(details),
                },
            )
        return ticket_id

    def get_for_actor(
        self, *, ticket_id: UUID, tenant_id: str, actor_ref: str
    ) -> HandoffTicket | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT ticket_id, run_id, tenant_id, actor_ref, reason_code, status, operation, "
                    "details_redacted_json, created_at, resolved_at, resolution "
                    "FROM runtime.handoff_tickets WHERE ticket_id = :ticket_id "
                    "AND tenant_id = :tenant_id AND actor_ref = :actor_ref"
                ),
                {"ticket_id": ticket_id, "tenant_id": tenant_id, "actor_ref": actor_ref},
            ).one_or_none()
        if row is None:
            return None
        values = dict(row._mapping)
        details = values["details_redacted_json"]
        if not isinstance(details, dict):
            raise ValueError("handoff details are not an object")
        values["details"] = details
        del values["details_redacted_json"]
        return HandoffTicket(**values)

    def resolve(
        self,
        *,
        ticket_id: UUID,
        tenant_id: str,
        resolution: str,
        expected_status: str = "open",
    ) -> HandoffTicket | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "UPDATE runtime.handoff_tickets SET status = 'resolved', resolution = :resolution, "
                    "resolved_at = now() WHERE ticket_id = :ticket_id AND tenant_id = :tenant_id "
                    "AND status = :expected_status RETURNING ticket_id, run_id, tenant_id, actor_ref, "
                    "reason_code, status, operation, details_redacted_json, created_at, resolved_at, resolution"
                ),
                {
                    "ticket_id": ticket_id,
                    "tenant_id": tenant_id,
                    "resolution": resolution,
                    "expected_status": expected_status,
                },
            ).one_or_none()
        if row is None:
            return None
        values = dict(row._mapping)
        details = values.pop("details_redacted_json")
        if not isinstance(details, dict):
            raise ValueError("handoff details are not an object")
        values["details"] = details
        return HandoffTicket(**values)


def _json(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

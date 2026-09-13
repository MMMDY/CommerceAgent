"""Reliable outbox leasing; workers never participate in agent decisions."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class OutboxLease:
    outbox_id: UUID
    run_id: UUID
    event_id: UUID
    topic: str
    payload: dict[str, object]
    attempt_count: int


class OutboxRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def lease_pending(self, *, limit: int, lease_for: timedelta) -> list[OutboxLease]:
        if not 1 <= limit <= 100 or lease_for.total_seconds() <= 0:
            raise ValueError("invalid outbox lease request")
        with self._engine.begin() as connection:
            rows = connection.execute(
                text(
                    "WITH candidates AS (SELECT outbox_id FROM runtime.runtime_outbox "
                    "WHERE (status = 'pending' AND available_at <= now()) OR "
                    "(status = 'publishing' AND locked_at <= now() - CAST(:lease_for AS interval)) "
                    "ORDER BY available_at "
                    "FOR UPDATE SKIP LOCKED LIMIT :limit) "
                    "UPDATE runtime.runtime_outbox o SET status = 'publishing', locked_at = now(), "
                    "attempt_count = attempt_count + 1 FROM candidates c WHERE o.outbox_id = c.outbox_id "
                    "RETURNING o.outbox_id, o.run_id, o.event_id, o.topic, o.payload_redacted_json, o.attempt_count"
                ), {"limit": limit, "lease_for": f"{int(lease_for.total_seconds())} seconds"},
            ).all()
        return [OutboxLease(*tuple(row)) for row in rows]

    def mark_published(self, *, outbox_id: UUID) -> bool:
        with self._engine.begin() as connection:
            changed = connection.execute(text("UPDATE runtime.runtime_outbox SET status = 'published', "
                "published_at = now(), locked_at = NULL WHERE outbox_id = :outbox_id AND status = 'publishing'"),
                {"outbox_id": outbox_id})
        return changed.rowcount == 1

    def retry(self, *, outbox_id: UUID, error_code: str, delay: timedelta) -> bool:
        if delay.total_seconds() < 0:
            raise ValueError("retry delay must not be negative")
        with self._engine.begin() as connection:
            changed = connection.execute(text("UPDATE runtime.runtime_outbox SET status = 'pending', locked_at = NULL, "
                "last_error = :error_code, available_at = now() + CAST(:seconds AS interval) "
                "WHERE outbox_id = :outbox_id AND status = 'publishing'"),
                {"outbox_id": outbox_id, "error_code": error_code,
                 "seconds": f"{int(delay.total_seconds())} seconds"})
        return changed.rowcount == 1

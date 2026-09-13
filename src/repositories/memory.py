"""Tenant-scoped long-term memory facts."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class MemoryFact:
    fact_id: UUID
    tenant_id: str
    actor_ref: str
    fact_type: str
    value: dict[str, object]


class MemoryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, *, tenant_id: str, actor_ref: str, fact_type: str, value: dict[str, object],
            source_type: str, source_ref: str, confidence: float, observed_at: datetime,
            valid_until: datetime | None = None) -> UUID:
        fact_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO memory.memory_facts "
                "(fact_id, tenant_id, actor_ref, fact_type, value_json, source_type, source_ref, confidence, "
                "observed_at, valid_until, status, created_at) VALUES (:fact_id, :tenant_id, :actor_ref, "
                ":fact_type, CAST(:value AS jsonb), :source_type, :source_ref, :confidence, :observed_at, "
                ":valid_until, 'active', now())"),
                {"fact_id": fact_id, "tenant_id": tenant_id, "actor_ref": actor_ref, "fact_type": fact_type,
                 "value": json.dumps(value), "source_type": source_type, "source_ref": source_ref,
                 "confidence": confidence, "observed_at": observed_at, "valid_until": valid_until})
        return fact_id

    def active_for_actor(self, *, tenant_id: str, actor_ref: str) -> list[MemoryFact]:
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT fact_id, tenant_id, actor_ref, fact_type, value_json "
                "FROM memory.memory_facts WHERE tenant_id = :tenant_id AND actor_ref = :actor_ref "
                "AND status = 'active' AND (valid_until IS NULL OR valid_until > now()) ORDER BY observed_at DESC"),
                {"tenant_id": tenant_id, "actor_ref": actor_ref}).all()
        return [MemoryFact(*tuple(row)) for row in rows]

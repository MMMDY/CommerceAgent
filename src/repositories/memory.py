"""Tenant-scoped long-term memory facts."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

ALLOWED_PREFERENCE_TYPES = frozenset(
    {
        "preferred_category",
        "preferred_size",
        "preferred_color",
        "preferred_delivery_method",
        "preferred_language",
    }
)
FORBIDDEN_FACT_TYPES = frozenset(
    {"order_status", "payment_status", "refund_status", "delivery_status", "inferred_preference"}
)


class MemoryValidationError(ValueError):
    """A memory write is outside the controlled preference contract."""


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

    def add(
        self,
        *,
        tenant_id: str,
        actor_ref: str,
        fact_type: str,
        value: dict[str, object],
        source_type: str,
        source_ref: str,
        confidence: float,
        observed_at: datetime,
        valid_until: datetime | None = None,
    ) -> UUID:
        self._validate_write(
            fact_type=fact_type,
            source_type=source_type,
            confidence=confidence,
            value=value,
        )
        fact_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO memory.memory_facts "
                    "(fact_id, tenant_id, actor_ref, fact_type, value_json, source_type, source_ref, confidence, "
                    "observed_at, valid_until, status, created_at) VALUES (:fact_id, :tenant_id, :actor_ref, "
                    ":fact_type, CAST(:value AS jsonb), :source_type, :source_ref, :confidence, :observed_at, "
                    ":valid_until, 'active', now())"
                ),
                {
                    "fact_id": fact_id,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "fact_type": fact_type,
                    "value": json.dumps(value),
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "confidence": confidence,
                    "observed_at": observed_at,
                    "valid_until": valid_until,
                },
            )
        return fact_id

    def upsert_preference(
        self,
        *,
        tenant_id: str,
        actor_ref: str,
        fact_type: str,
        value: dict[str, object],
        source_type: str,
        source_ref: str,
        confidence: float,
        observed_at: datetime,
        valid_until: datetime | None = None,
    ) -> UUID:
        """Write one stable preference and supersede the previous value atomically."""
        self._validate_write(
            fact_type=fact_type, source_type=source_type, confidence=confidence, value=value
        )
        fact_id = uuid4()
        with self._engine.begin() as connection:
            previous = connection.execute(
                text(
                    "SELECT fact_id FROM memory.memory_facts WHERE tenant_id = :tenant_id "
                    "AND actor_ref = :actor_ref AND fact_type = :fact_type AND status = 'active' "
                    "ORDER BY observed_at DESC LIMIT 1 FOR UPDATE"
                ),
                {"tenant_id": tenant_id, "actor_ref": actor_ref, "fact_type": fact_type},
            ).first()
            if previous is not None:
                connection.execute(
                    text(
                        "UPDATE memory.memory_facts SET status = 'superseded' "
                        "WHERE fact_id = :fact_id AND tenant_id = :tenant_id"
                    ),
                    {"fact_id": previous[0], "tenant_id": tenant_id},
                )
            connection.execute(
                text(
                    "INSERT INTO memory.memory_facts (fact_id, tenant_id, actor_ref, fact_type, value_json, "
                    "source_type, source_ref, confidence, observed_at, valid_until, supersedes_fact_id, status, created_at) "
                    "VALUES (:fact_id, :tenant_id, :actor_ref, :fact_type, CAST(:value AS jsonb), :source_type, "
                    ":source_ref, :confidence, :observed_at, :valid_until, :supersedes, 'active', now())"
                ),
                {
                    "fact_id": fact_id,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "fact_type": fact_type,
                    "value": json.dumps(value),
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "confidence": confidence,
                    "observed_at": observed_at,
                    "valid_until": valid_until,
                    "supersedes": previous[0] if previous is not None else None,
                },
            )
        return fact_id

    def delete(self, *, fact_id: UUID, tenant_id: str, actor_ref: str) -> bool:
        """Tombstone a fact only for its owning tenant and actor."""
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE memory.memory_facts SET status = 'deleted' WHERE fact_id = :fact_id "
                    "AND tenant_id = :tenant_id AND actor_ref = :actor_ref AND status = 'active'"
                ),
                {"fact_id": fact_id, "tenant_id": tenant_id, "actor_ref": actor_ref},
            )
        return result.rowcount == 1

    def active_for_actor(self, *, tenant_id: str, actor_ref: str) -> list[MemoryFact]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT fact_id, tenant_id, actor_ref, fact_type, value_json "
                    "FROM memory.memory_facts WHERE tenant_id = :tenant_id AND actor_ref = :actor_ref "
                    "AND status = 'active' AND (valid_until IS NULL OR valid_until > now()) ORDER BY observed_at DESC"
                ),
                {"tenant_id": tenant_id, "actor_ref": actor_ref},
            ).all()
        return [MemoryFact(*tuple(row)) for row in rows]

    @staticmethod
    def _validate_write(
        *, fact_type: str, source_type: str, confidence: float, value: dict[str, object]
    ) -> None:
        if fact_type not in ALLOWED_PREFERENCE_TYPES or fact_type in FORBIDDEN_FACT_TYPES:
            raise MemoryValidationError("only controlled preference facts may be stored")
        if source_type not in {"user", "tool"}:
            raise MemoryValidationError("memory source must be user or tool")
        if not 0 <= confidence <= 1:
            raise MemoryValidationError("memory confidence must be between 0 and 1")
        if not value or len(value) > 8:
            raise MemoryValidationError("memory value is invalid")

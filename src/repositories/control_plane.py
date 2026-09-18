"""Idempotency boundary for human-gated control-plane mutations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


class ControlPlaneIdempotencyConflictError(RuntimeError):
    """The same key was reused for a different control-plane request."""


class ControlPlaneIdempotencyInProgressError(RuntimeError):
    """Another worker currently owns this control-plane mutation."""


@dataclass(frozen=True, slots=True)
class ControlPlaneIdempotencyClaim:
    record_id: UUID
    acquired: bool
    response: dict[str, Any] | None = None


class ControlPlaneIdempotencyRepository:
    """Reserve and replay admin mutations without repeating their side effects.

    The existing runtime idempotency table is deliberately reused.  Only a
    one-way key hash and a request fingerprint are persisted; response JSON is
    limited to the already-redacted control-plane DTO.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(
        self,
        *,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ControlPlaneIdempotencyClaim:
        if not 8 <= len(idempotency_key) <= 128:
            raise ValueError("invalid_idempotency_key")
        if not 1 <= len(operation) <= 80 or not request_fingerprint:
            raise ValueError("invalid_idempotency_request")
        key_hash = _hash(idempotency_key)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.idempotency_records "
                    "(idempotency_record_id, tenant_id, operation, idempotency_key_hash, "
                    "request_fingerprint, status, created_at, updated_at) "
                    "VALUES (:record_id, :tenant_id, :operation, :key_hash, "
                    ":fingerprint, 'reserved', now(), now()) ON CONFLICT DO NOTHING"
                ),
                {
                    "record_id": uuid4(),
                    "tenant_id": tenant_id,
                    "operation": operation,
                    "key_hash": key_hash,
                    "fingerprint": request_fingerprint,
                },
            )
            row = connection.execute(
                text(
                    "SELECT idempotency_record_id, request_fingerprint, status, "
                    "response_redacted_json FROM runtime.idempotency_records "
                    "WHERE tenant_id = :tenant_id AND operation = :operation "
                    "AND idempotency_key_hash = :key_hash"
                ),
                {"tenant_id": tenant_id, "operation": operation, "key_hash": key_hash},
            ).mappings().one()
            if row["request_fingerprint"] != request_fingerprint:
                raise ControlPlaneIdempotencyConflictError("idempotency_fingerprint_conflict")
            if row["status"] == "completed":
                response = row["response_redacted_json"]
                if not isinstance(response, dict):
                    raise RuntimeError("completed_idempotency_response_invalid")
                return ControlPlaneIdempotencyClaim(
                    record_id=row["idempotency_record_id"], acquired=False, response=response
                )
            if row["status"] != "reserved":
                raise ControlPlaneIdempotencyInProgressError("idempotency_request_in_progress")
            claimed = connection.execute(
                text(
                    "UPDATE runtime.idempotency_records SET status = 'in_progress', "
                    "updated_at = now(), row_version = row_version + 1 "
                    "WHERE idempotency_record_id = :record_id AND status = 'reserved' "
                    "RETURNING idempotency_record_id"
                ),
                {"record_id": row["idempotency_record_id"]},
            ).first()
            if claimed is None:
                raise ControlPlaneIdempotencyInProgressError("idempotency_request_in_progress")
            return ControlPlaneIdempotencyClaim(record_id=claimed[0], acquired=True)

    def complete(self, *, tenant_id: str, record_id: UUID, response: dict[str, Any]) -> None:
        encoded = json.loads(json.dumps(response, ensure_ascii=False))
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE runtime.idempotency_records SET status = 'completed', "
                    "response_redacted_json = CAST(:response AS jsonb), updated_at = now(), "
                    "row_version = row_version + 1 WHERE idempotency_record_id = :record_id "
                    "AND tenant_id = :tenant_id AND status = 'in_progress'"
                ),
                {
                    "tenant_id": tenant_id,
                    "record_id": record_id,
                    "response": json.dumps(encoded, ensure_ascii=False),
                },
            ).rowcount
        if changed != 1:
            raise RuntimeError("idempotency_completion_failed")

    def abandon(self, *, tenant_id: str, record_id: UUID) -> None:
        """Release a claim when its guarded mutation rolled back before commit."""

        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM runtime.idempotency_records "
                    "WHERE idempotency_record_id = :record_id "
                    "AND tenant_id = :tenant_id AND status = 'in_progress'"
                ),
                {"tenant_id": tenant_id, "record_id": record_id},
            )


def _hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ControlPlaneIdempotencyClaim",
    "ControlPlaneIdempotencyConflictError",
    "ControlPlaneIdempotencyInProgressError",
    "ControlPlaneIdempotencyRepository",
]

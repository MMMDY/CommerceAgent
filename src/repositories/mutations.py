"""Tenant-bound confirmation and idempotency persistence."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from src.mutation_safety import (
    MutationExecutionClaim,
    MutationExecutionIntent,
    MutationExecutionStatus,
    StoredMutationExecution,
)


class ConfirmationUnavailableError(RuntimeError):
    """The token is missing, owned by another actor, expired, or already used."""


class IdempotencyConflictError(RuntimeError):
    """One key was presented for two different mutation fingerprints."""


class MutationExecutionUnavailableError(RuntimeError):
    """A mutation intent is absent, belongs to another tenant, or conflicts."""


@dataclass(frozen=True, slots=True)
class ConfirmationTokenInput:
    token_hash: str
    run_id: UUID
    tenant_id: str
    actor_ref: str
    mutation_type: str
    resource_ref: str
    preview_hash: str
    arguments_hash: str
    policy_version: str
    workflow_version: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyReservation:
    record_id: UUID
    status: str
    reused: bool


@dataclass(frozen=True, slots=True)
class ConfirmationTokenRecord:
    token_id: UUID
    token_hash: str
    run_id: UUID
    tenant_id: str
    actor_ref: str
    mutation_type: str
    resource_ref: str
    preview_hash: str
    arguments_hash: str
    policy_version: str
    workflow_version: str
    status: str
    expires_at: datetime
    row_version: int


class ConfirmationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def issue(self, token: ConfirmationTokenInput) -> UUID:
        token_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.confirmation_tokens "
                    "(token_id, token_hash, run_id, tenant_id, actor_ref, mutation_type, "
                    "resource_ref, preview_hash, arguments_hash, policy_version, workflow_version, "
                    "status, expires_at, created_at) "
                    "VALUES (:token_id, :token_hash, :run_id, :tenant_id, :actor_ref, :mutation_type, "
                    ":resource_ref, :preview_hash, :arguments_hash, :policy_version, :workflow_version, "
                    "'waiting', :expires_at, now())"
                ),
                {**asdict(token), "token_id": token_id},
            )
        return token_id

    def load_for_run(
        self, *, run_id: UUID, tenant_id: str, actor_ref: str, token_hash: str | None = None
    ) -> ConfirmationTokenRecord | None:
        predicate = "AND token_hash = :token_hash" if token_hash is not None else ""
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT token_id, token_hash, run_id, tenant_id, actor_ref, mutation_type, "
                    "resource_ref, preview_hash, arguments_hash, policy_version, workflow_version, "
                    "status, expires_at, row_version FROM runtime.confirmation_tokens "
                    "WHERE run_id = :run_id AND tenant_id = :tenant_id AND actor_ref = :actor_ref "
                    + predicate
                    + " ORDER BY created_at DESC LIMIT 1"
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "token_hash": token_hash,
                },
            ).one_or_none()
        return ConfirmationTokenRecord(**dict(row._mapping)) if row is not None else None

    def invalidate_waiting(
        self, *, run_id: UUID, tenant_id: str, actor_ref: str, expected_preview_hash: str
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE runtime.confirmation_tokens SET status = 'invalidated', row_version = row_version + 1 "
                    "WHERE run_id = :run_id AND tenant_id = :tenant_id AND actor_ref = :actor_ref "
                    "AND preview_hash = :preview_hash AND status = 'waiting'"
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "preview_hash": expected_preview_hash,
                },
            )

    def rotate_waiting(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        actor_ref: str,
        expected_preview_hash: str,
        token: ConfirmationTokenInput,
    ) -> UUID:
        """Invalidate and issue a replacement token in one database transaction."""

        token_id = uuid4()
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE runtime.confirmation_tokens SET status = 'invalidated', row_version = row_version + 1 "
                    "WHERE run_id = :run_id AND tenant_id = :tenant_id AND actor_ref = :actor_ref "
                    "AND preview_hash = :preview_hash AND status = 'waiting' AND expires_at > now()"
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "preview_hash": expected_preview_hash,
                },
            )
            if changed.rowcount != 1:
                raise ConfirmationUnavailableError("confirmation token unavailable")
            connection.execute(
                text(
                    "INSERT INTO runtime.confirmation_tokens "
                    "(token_id, token_hash, run_id, tenant_id, actor_ref, mutation_type, "
                    "resource_ref, preview_hash, arguments_hash, policy_version, workflow_version, "
                    "status, expires_at, created_at) VALUES (:token_id, :token_hash, :run_id, "
                    ":tenant_id, :actor_ref, :mutation_type, :resource_ref, :preview_hash, "
                    ":arguments_hash, :policy_version, :workflow_version, 'waiting', :expires_at, now())"
                ),
                {**asdict(token), "token_id": token_id},
            )
        return token_id

    def reject(
        self, *, token_hash: str, tenant_id: str, actor_ref: str, expected_version: int
    ) -> None:
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE runtime.confirmation_tokens SET status = 'rejected', row_version = row_version + 1 "
                    "WHERE token_hash = :token_hash AND tenant_id = :tenant_id AND actor_ref = :actor_ref "
                    "AND status = 'waiting' AND expires_at > now() AND row_version = :expected_version"
                ),
                {
                    "token_hash": token_hash,
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref,
                    "expected_version": expected_version,
                },
            )
        if changed.rowcount != 1:
            raise ConfirmationUnavailableError("confirmation token unavailable")

    def expire_waiting(self, *, limit: int = 500) -> int:
        """Move expired waiting tokens to a terminal state idempotently."""

        if not 1 <= limit <= 5000:
            raise ValueError("invalid expiration batch size")
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE runtime.confirmation_tokens SET status = 'expired', "
                    "row_version = row_version + 1 "
                    "WHERE token_id IN (SELECT token_id FROM runtime.confirmation_tokens "
                    "WHERE status = 'waiting' AND expires_at <= now() "
                    "ORDER BY expires_at LIMIT :limit)"
                ),
                {"limit": limit},
            )
        return int(changed.rowcount or 0)

    def consume_and_reserve(
        self,
        *,
        token_hash: str,
        tenant_id: str,
        actor_ref: str,
        expected_token_version: int,
        operation: str,
        idempotency_key_hash: str,
        request_fingerprint: str,
        expires_at: datetime | None,
    ) -> IdempotencyReservation:
        existing = self._load_idempotency(tenant_id, operation, idempotency_key_hash)
        if existing is not None:
            return self._match_existing(existing, request_fingerprint)
        try:
            return self._consume_and_insert(
                token_hash=token_hash,
                tenant_id=tenant_id,
                actor_ref=actor_ref,
                expected_token_version=expected_token_version,
                operation=operation,
                idempotency_key_hash=idempotency_key_hash,
                request_fingerprint=request_fingerprint,
                expires_at=expires_at,
            )
        except IntegrityError:
            existing = self._load_idempotency(tenant_id, operation, idempotency_key_hash)
            if existing is None:
                raise
            return self._match_existing(existing, request_fingerprint)

    def _consume_and_insert(self, **params: object) -> IdempotencyReservation:
        record_id = uuid4()
        with self._engine.begin() as connection:
            consumed = connection.execute(
                text(
                    "UPDATE runtime.confirmation_tokens SET status = 'consumed', consumed_at = now(), "
                    "row_version = row_version + 1 WHERE token_hash = :token_hash "
                    "AND tenant_id = :tenant_id AND actor_ref = :actor_ref AND status = 'waiting' "
                    "AND expires_at > now() AND row_version = :expected_token_version RETURNING token_id"
                ),
                params,
            ).one_or_none()
            if consumed is None:
                raise ConfirmationUnavailableError("confirmation token unavailable")
            connection.execute(
                text(
                    "INSERT INTO runtime.idempotency_records "
                    "(idempotency_record_id, tenant_id, operation, idempotency_key_hash, "
                    "request_fingerprint, status, created_at, updated_at, expires_at) "
                    "VALUES (:record_id, :tenant_id, :operation, :idempotency_key_hash, "
                    ":request_fingerprint, 'reserved', now(), now(), :expires_at)"
                ),
                {**params, "record_id": record_id},
            )
        return IdempotencyReservation(record_id=record_id, status="reserved", reused=False)

    def _load_idempotency(
        self, tenant_id: str, operation: str, key_hash: str
    ) -> tuple[UUID, str, str] | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT idempotency_record_id, request_fingerprint, status "
                    "FROM runtime.idempotency_records WHERE tenant_id = :tenant_id AND operation = :operation "
                    "AND idempotency_key_hash = :key_hash"
                ),
                {"tenant_id": tenant_id, "operation": operation, "key_hash": key_hash},
            ).one_or_none()
        return cast(tuple[UUID, str, str] | None, tuple(row) if row is not None else None)

    @staticmethod
    def _match_existing(
        existing: tuple[UUID, str, str], fingerprint: str
    ) -> IdempotencyReservation:
        record_id, actual_fingerprint, status = existing
        if actual_fingerprint != fingerprint:
            raise IdempotencyConflictError("idempotency fingerprint conflict")
        return IdempotencyReservation(record_id=record_id, status=status, reused=True)


class MutationExecutionRepository:
    """Durable execution intents used by the mutation orchestration boundary.

    A worker must atomically claim ``reserved -> in_progress`` before calling
    an external adapter.  An ``in_progress`` record is never claimed again:
    after a crash its external status is unknown and must be verified instead
    of blindly repeating the mutation.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def reserve(
        self, intent: MutationExecutionIntent, *, expires_at: datetime | None = None
    ) -> StoredMutationExecution:
        """Create a low-write intent, or return the exact existing intent."""

        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.idempotency_records "
                    "(idempotency_record_id, tenant_id, operation, idempotency_key_hash, "
                    "request_fingerprint, status, created_at, updated_at, expires_at) "
                    "VALUES (:record_id, :tenant_id, :operation, :key_hash, "
                    ":request_fingerprint, 'reserved', now(), now(), :expires_at) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "record_id": intent.record_id,
                    "tenant_id": intent.tenant_id,
                    "operation": intent.operation,
                    "key_hash": _record_key_hash(intent.record_id),
                    "request_fingerprint": intent.request_fingerprint,
                    "expires_at": expires_at,
                },
            )
        stored = self.load(intent)
        if stored is None:
            raise MutationExecutionUnavailableError("mutation execution intent unavailable")
        return stored

    def load(self, intent: MutationExecutionIntent) -> StoredMutationExecution | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT idempotency_record_id, tenant_id, operation, request_fingerprint, "
                    "status, business_reference, response_redacted_json "
                    "FROM runtime.idempotency_records "
                    "WHERE idempotency_record_id = :record_id AND tenant_id = :tenant_id"
                ),
                {"record_id": intent.record_id, "tenant_id": intent.tenant_id},
            ).one_or_none()
        if row is None:
            return None
        stored = _stored_execution(dict(row._mapping))
        _require_same_intent(intent, stored.intent)
        return stored

    def claim(self, intent: MutationExecutionIntent) -> MutationExecutionClaim:
        """Claim once.  A concurrent or recovered worker never reclaims it."""

        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "UPDATE runtime.idempotency_records "
                    "SET status = 'in_progress', updated_at = now(), row_version = row_version + 1 "
                    "WHERE idempotency_record_id = :record_id AND tenant_id = :tenant_id "
                    "AND operation = :operation AND request_fingerprint = :request_fingerprint "
                    "AND status = 'reserved' "
                    "RETURNING idempotency_record_id, tenant_id, operation, request_fingerprint, "
                    "status, business_reference, response_redacted_json"
                ),
                {
                    "record_id": intent.record_id,
                    "tenant_id": intent.tenant_id,
                    "operation": intent.operation,
                    "request_fingerprint": intent.request_fingerprint,
                },
            ).one_or_none()
        if row is not None:
            return MutationExecutionClaim(
                execution=_stored_execution(dict(row._mapping)), acquired=True
            )
        stored = self.load(intent)
        if stored is None:
            raise MutationExecutionUnavailableError("mutation execution intent unavailable")
        return MutationExecutionClaim(execution=stored, acquired=False)


def _record_key_hash(record_id: UUID) -> str:
    # The stable UUID, not this database-only hash, is sent as the upstream
    # idempotency key.  Keeping only a hash in this column follows the schema's
    # non-replayable-at-rest contract.
    from hashlib import sha256

    return f"sha256:{sha256(str(record_id).encode()).hexdigest()}"


def _stored_execution(row: dict[str, Any]) -> StoredMutationExecution:
    response = row["response_redacted_json"]
    if response is not None and not isinstance(response, dict):
        raise ValueError("persisted mutation response is not an object")
    try:
        status = MutationExecutionStatus(row["status"])
    except ValueError as error:
        raise ValueError("persisted mutation execution status is invalid") from error
    return StoredMutationExecution(
        intent=MutationExecutionIntent(
            record_id=row["idempotency_record_id"],
            tenant_id=row["tenant_id"],
            operation=row["operation"],
            request_fingerprint=row["request_fingerprint"],
        ),
        status=status,
        business_reference=row["business_reference"],
        response_redacted=response,
    )


def _require_same_intent(
    expected: MutationExecutionIntent, actual: MutationExecutionIntent
) -> None:
    if expected != actual:
        raise IdempotencyConflictError("idempotency fingerprint conflict")

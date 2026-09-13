"""Tenant-bound confirmation and idempotency persistence."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


class ConfirmationUnavailableError(RuntimeError):
    """The token is missing, owned by another actor, expired, or already used."""


class IdempotencyConflictError(RuntimeError):
    """One key was presented for two different mutation fingerprints."""


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

    def consume_and_reserve(
        self, *, token_hash: str, tenant_id: str, actor_ref: str, expected_token_version: int,
        operation: str, idempotency_key_hash: str, request_fingerprint: str, expires_at: datetime | None
    ) -> IdempotencyReservation:
        existing = self._load_idempotency(tenant_id, operation, idempotency_key_hash)
        if existing is not None:
            return self._match_existing(existing, request_fingerprint)
        try:
            return self._consume_and_insert(
                token_hash=token_hash, tenant_id=tenant_id, actor_ref=actor_ref,
                expected_token_version=expected_token_version, operation=operation,
                idempotency_key_hash=idempotency_key_hash, request_fingerprint=request_fingerprint,
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
                ), params,
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
                ), {**params, "record_id": record_id},
            )
        return IdempotencyReservation(record_id=record_id, status="reserved", reused=False)

    def _load_idempotency(self, tenant_id: str, operation: str, key_hash: str) -> tuple[UUID, str, str] | None:
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT idempotency_record_id, request_fingerprint, status "
                "FROM runtime.idempotency_records WHERE tenant_id = :tenant_id AND operation = :operation "
                "AND idempotency_key_hash = :key_hash"),
                {"tenant_id": tenant_id, "operation": operation, "key_hash": key_hash}).one_or_none()
        return cast(tuple[UUID, str, str] | None, tuple(row) if row is not None else None)

    @staticmethod
    def _match_existing(existing: tuple[UUID, str, str], fingerprint: str) -> IdempotencyReservation:
        record_id, actual_fingerprint, status = existing
        if actual_fingerprint != fingerprint:
            raise IdempotencyConflictError("idempotency fingerprint conflict")
        return IdempotencyReservation(record_id=record_id, status=status, reused=True)

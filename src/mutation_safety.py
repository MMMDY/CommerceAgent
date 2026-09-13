"""Deterministic in-process guards for confirmation and idempotency semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True, slots=True)
class ConfirmationToken:
    token_hash: str
    tenant_id: str
    actor_id: str
    preview_hash: str
    expires_at: datetime
    row_version: int = 0
    status: str = "waiting"


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    tenant_id: str
    operation: str
    key_hash: str
    request_fingerprint: str
    status: str = "reserved"


class MutationGuards:
    """Thread-safe reference semantics mirrored by the SQL repository."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._tokens: dict[str, ConfirmationToken] = {}
        self._idempotency: dict[tuple[str, str, str], IdempotencyRecord] = {}

    def register_token(self, token: ConfirmationToken) -> None:
        with self._lock:
            if token.token_hash in self._tokens:
                raise ValueError("duplicate confirmation token")
            self._tokens[token.token_hash] = token

    def consume_token(
        self, token_hash: str, *, tenant_id: str, actor_id: str, expected_version: int
    ) -> ConfirmationToken:
        with self._lock:
            token = self._tokens.get(token_hash)
            now = datetime.now(timezone.utc)
            if token is None or token.tenant_id != tenant_id or token.actor_id != actor_id:
                raise PermissionError("confirmation token unavailable")
            if (
                token.status != "waiting"
                or token.expires_at <= now
                or token.row_version != expected_version
            ):
                raise ValueError("confirmation token is stale")
            consumed = replace(token, status="consumed", row_version=token.row_version + 1)
            self._tokens[token_hash] = consumed
            return consumed

    def reserve_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        key = (record.tenant_id, record.operation, record.key_hash)
        with self._lock:
            existing = self._idempotency.get(key)
            if existing is not None:
                if existing.request_fingerprint != record.request_fingerprint:
                    raise ValueError("idempotency fingerprint conflict")
                return existing
            self._idempotency[key] = record
            return record

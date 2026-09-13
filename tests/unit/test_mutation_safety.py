from datetime import datetime, timedelta, timezone

import pytest

from src.mutation_safety import ConfirmationToken, IdempotencyRecord, MutationGuards


def test_confirmation_token_is_single_use_and_owner_bound() -> None:
    guards = MutationGuards()
    guards.register_token(
        ConfirmationToken(
            token_hash="token-1",
            tenant_id="tenant-a",
            actor_id="actor-a",
            preview_hash="preview",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
    )
    consumed = guards.consume_token(
        "token-1", tenant_id="tenant-a", actor_id="actor-a", expected_version=0
    )
    assert consumed.status == "consumed"
    with pytest.raises(ValueError):
        guards.consume_token(
            "token-1", tenant_id="tenant-a", actor_id="actor-a", expected_version=0
        )
    with pytest.raises(PermissionError):
        guards.consume_token(
            "token-1", tenant_id="tenant-b", actor_id="actor-a", expected_version=1
        )


def test_idempotency_reuses_same_fingerprint_and_rejects_conflict() -> None:
    guards = MutationGuards()
    record = IdempotencyRecord("tenant-a", "refund", "key-1", "fingerprint-1")
    assert guards.reserve_idempotency(record) == record
    assert guards.reserve_idempotency(record) == record
    with pytest.raises(ValueError):
        guards.reserve_idempotency(record.__class__("tenant-a", "refund", "key-1", "different"))

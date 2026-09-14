"""PostgreSQL contracts for confirmation and idempotency persistence."""

# ruff: noqa: E501

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.repositories.mutations import (
    ConfirmationRepository,
    ConfirmationTokenInput,
    ConfirmationUnavailableError,
    IdempotencyConflictError,
)
from tests.contract.test_runs_repository import _create_run


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


@pytest.fixture
def repository(engine: Engine) -> ConfirmationRepository:
    return ConfirmationRepository(engine)


def _issue(repository: ConfirmationRepository, engine: Engine) -> tuple[str, str]:
    run_id, tenant_id = _create_run(engine)
    token_hash = f"token-{uuid4()}"
    repository.issue(ConfirmationTokenInput(
        token_hash=token_hash, run_id=run_id, tenant_id=tenant_id, actor_ref="contract-actor",
        mutation_type="refund", resource_ref="order-1", preview_hash="preview", arguments_hash="args",
        policy_version="policy-1", workflow_version="workflow-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ))
    return token_hash, tenant_id


def test_consume_and_reserve_is_atomic_and_replay_safe(
    engine: Engine, repository: ConfirmationRepository
) -> None:
    token_hash, tenant_id = _issue(repository, engine)
    first = repository.consume_and_reserve(
        token_hash=token_hash, tenant_id=tenant_id, actor_ref="contract-actor",
        expected_token_version=0, operation="refund", idempotency_key_hash="key-1",
        request_fingerprint="fingerprint-1", expires_at=None,
    )
    replay = repository.consume_and_reserve(
        token_hash="not-used-for-replay", tenant_id=tenant_id, actor_ref="wrong-actor",
        expected_token_version=0, operation="refund", idempotency_key_hash="key-1",
        request_fingerprint="fingerprint-1", expires_at=None,
    )
    assert first.reused is False
    assert replay == first.__class__(first.record_id, "reserved", True)
    with engine.connect() as connection:
        state = connection.execute(text("SELECT status, row_version FROM runtime.confirmation_tokens "
            "WHERE token_hash = :token_hash"), {"token_hash": token_hash}).one()
        count = connection.execute(text("SELECT count(*) FROM runtime.idempotency_records "
            "WHERE tenant_id = :tenant_id AND idempotency_key_hash = 'key-1'"),
            {"tenant_id": tenant_id}).scalar_one()
    assert tuple(state) == ("consumed", 1)
    assert count == 1


def test_wrong_actor_or_fingerprint_conflict_cannot_consume_or_replace(
    engine: Engine, repository: ConfirmationRepository
) -> None:
    token_hash, tenant_id = _issue(repository, engine)
    with pytest.raises(ConfirmationUnavailableError):
        repository.consume_and_reserve(
            token_hash=token_hash, tenant_id=tenant_id, actor_ref="other", expected_token_version=0,
            operation="refund", idempotency_key_hash="key-2", request_fingerprint="fingerprint-2",
            expires_at=None,
        )
    first = repository.consume_and_reserve(
        token_hash=token_hash, tenant_id=tenant_id, actor_ref="contract-actor", expected_token_version=0,
        operation="refund", idempotency_key_hash="key-2", request_fingerprint="fingerprint-2",
        expires_at=None,
    )
    with pytest.raises(IdempotencyConflictError):
        repository.consume_and_reserve(
            token_hash="ignored", tenant_id=tenant_id, actor_ref="contract-actor", expected_token_version=0,
            operation="refund", idempotency_key_hash="key-2", request_fingerprint="different",
            expires_at=None,
        )
    assert first.reused is False


def test_concurrent_confirmation_consumption_has_one_winner(
    engine: Engine, repository: ConfirmationRepository
) -> None:
    token_hash, tenant_id = _issue(repository, engine)

    def consume() -> str:
        try:
            result = repository.consume_and_reserve(
                token_hash=token_hash,
                tenant_id=tenant_id,
                actor_ref="contract-actor",
                expected_token_version=0,
                operation="refund",
                idempotency_key_hash=f"concurrent-{uuid4()}",
                request_fingerprint="fingerprint-concurrent",
                expires_at=None,
            )
        except ConfirmationUnavailableError:
            return "lost"
        return "won" if not result.reused else "replayed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: consume(), range(2)))
    assert outcomes.count("won") == 1
    assert outcomes.count("lost") == 1
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, row_version FROM runtime.confirmation_tokens "
                "WHERE token_hash = :token_hash"
            ),
            {"token_hash": token_hash},
        ).one()
    assert tuple(row) == ("consumed", 1)

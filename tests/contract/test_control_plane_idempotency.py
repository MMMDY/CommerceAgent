"""PostgreSQL contract for human-gated control-plane idempotency."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine

from src.repositories.control_plane import (
    ControlPlaneIdempotencyConflictError,
    ControlPlaneIdempotencyRepository,
)


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_control_plane_claim_replays_completed_response_and_rejects_conflict(
    engine: Engine,
) -> None:
    repository = ControlPlaneIdempotencyRepository(engine)
    operation = "contract_control_plane_" + uuid4().hex
    key = "contract-key-" + uuid4().hex
    fingerprint = "sha256:" + uuid4().hex

    first = repository.claim(
        tenant_id="contract-tenant",
        operation=operation,
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )
    assert first.acquired
    repository.complete(
        tenant_id="contract-tenant",
        record_id=first.record_id,
        response={"status": "reviewed", "replayed": False},
    )

    replay = repository.claim(
        tenant_id="contract-tenant",
        operation=operation,
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )
    assert not replay.acquired
    assert replay.response == {"status": "reviewed", "replayed": False}

    with pytest.raises(ControlPlaneIdempotencyConflictError):
        repository.claim(
            tenant_id="contract-tenant",
            operation=operation,
            idempotency_key=key,
            request_fingerprint="sha256:" + uuid4().hex,
        )

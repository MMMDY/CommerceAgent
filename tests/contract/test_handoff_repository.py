"""PostgreSQL contracts for uncertain mutation handoff tickets."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine, create_engine

from src.repositories.handoffs import HandoffRepository
from tests.contract.test_runs_repository import _create_run


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_handoff_is_tenant_and_actor_bound_and_resolves_once(engine: Engine) -> None:
    run_id, tenant_id = _create_run(
        engine, status="waiting_human", execution_mode="workflow"
    )
    repository = HandoffRepository(engine)
    ticket_id = repository.create(
        run_id=run_id,
        tenant_id=tenant_id,
        actor_ref="contract-actor",
        reason_code="VERIFY_MISMATCH",
        operation="commit_refund",
        details={"business_reference": "redacted-ref", "readback_found": False},
    )
    assert repository.get_for_actor(
        ticket_id=ticket_id,
        tenant_id=tenant_id,
        actor_ref="other-actor",
    ) is None
    ticket = repository.get_for_actor(
        ticket_id=ticket_id,
        tenant_id=tenant_id,
        actor_ref="contract-actor",
    )
    assert ticket is not None
    assert ticket.status == "open"
    assert ticket.reason_code == "VERIFY_MISMATCH"
    assert ticket.details["readback_found"] is False

    resolved = repository.resolve(
        ticket_id=ticket_id,
        tenant_id=tenant_id,
        resolution="verified_failure",
    )
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolution == "verified_failure"
    assert repository.resolve(
        ticket_id=ticket_id,
        tenant_id=tenant_id,
        resolution="verified_success",
    ) is None

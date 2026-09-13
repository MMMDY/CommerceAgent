"""PostgreSQL contracts for audit event tenant filtering."""

# ruff: noqa: E501

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine

from src.repositories.audit import AuditRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def test_audit_reads_are_tenant_scoped(engine: Engine) -> None:
    repository = AuditRepository(engine)
    tenant_id = f"audit-{uuid4()}"
    repository.append(tenant_id=tenant_id, actor_ref="actor", event_type="tool_called", payload={"safe": True}, payload_hash="hash")
    assert [event.event_type for event in repository.for_tenant(tenant_id=tenant_id)] == ["tool_called"]
    assert repository.for_tenant(tenant_id=f"other-{tenant_id}") == []

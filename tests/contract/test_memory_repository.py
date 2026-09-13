"""PostgreSQL contracts for tenant-scoped memory."""

# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine

from src.repositories.memory import MemoryRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def test_memory_is_tenant_scoped_and_excludes_expired_facts(engine: Engine) -> None:
    repository = MemoryRepository(engine)
    now = datetime.now(UTC)
    tenant_id = f"memory-{uuid4()}"
    repository.add(tenant_id=tenant_id, actor_ref="actor", fact_type="size", value={"size": "M"},
        source_type="user", source_ref="message", confidence=1, observed_at=now)
    repository.add(tenant_id=tenant_id, actor_ref="actor", fact_type="old", value={"value": "old"},
        source_type="user", source_ref="message", confidence=1, observed_at=now,
        valid_until=now - timedelta(seconds=1))
    assert [fact.fact_type for fact in repository.active_for_actor(tenant_id=tenant_id, actor_ref="actor")] == ["size"]
    assert repository.active_for_actor(tenant_id="memory-b", actor_ref="actor") == []

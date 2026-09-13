"""PostgreSQL contracts for immutable version lookup."""

# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine

from src.repositories.versions import VersionRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def test_versions_are_read_by_exact_id_and_version(engine: Engine) -> None:
    repository = VersionRepository(engine)
    now = datetime.now(UTC)
    workflow_id = f"workflow-{uuid4()}"
    policy_id = f"policy-{uuid4()}"
    repository.publish_workflow(workflow_id=workflow_id, version="1", definition={"start": "route"}, definition_hash=str(uuid4()), created_at=now)
    repository.publish_policy(policy_id=policy_id, version="1", rules={"allow": True}, rules_hash=str(uuid4()), effective_from=now, created_at=now)
    assert repository.workflow(workflow_id=workflow_id, version="1").definition == {"start": "route"}
    assert repository.policy(policy_id=policy_id, version="1").definition == {"allow": True}
    assert repository.workflow(workflow_id=workflow_id, version="missing") is None

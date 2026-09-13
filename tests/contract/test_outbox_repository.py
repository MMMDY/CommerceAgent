"""PostgreSQL contracts for reliable outbox leases."""

# ruff: noqa: E501

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.repositories.outbox import OutboxRepository
from src.repositories.runs import RunRepository
from tests.contract.test_runs_repository import _create_run, _event


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_concurrent_workers_lease_each_outbox_row_once(engine: Engine) -> None:
    run_id, tenant_id = _create_run(engine)
    event = _event()
    RunRepository(engine).commit_step(
        run_id=run_id, tenant_id=tenant_id, expected_version=0, next_status="running",
        next_step="outbox", checkpoint={"outbox": True}, checkpoint_hash="checkpoint",
        events=[event],
    )
    outbox_ids = [uuid4(), uuid4()]
    with engine.begin() as connection:
        for outbox_id in outbox_ids:
            connection.execute(text("INSERT INTO runtime.runtime_outbox "
                "(outbox_id, run_id, event_id, topic, payload_redacted_json, available_at, created_at) "
                "VALUES (:outbox_id, :run_id, :event_id, :topic, CAST(:payload AS jsonb), now(), now())"),
                {"outbox_id": outbox_id, "run_id": run_id, "event_id": event["event_id"],
                 "topic": str(outbox_id), "payload": "{\"safe\":true}"})
    repository = OutboxRepository(engine)
    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(lambda _: repository.lease_pending(limit=1, lease_for=timedelta(minutes=1)), range(2)))
    leased_ids = {lease.outbox_id for group in leases for lease in group}
    assert leased_ids == set(outbox_ids)
    assert repository.mark_published(outbox_id=next(iter(leased_ids))) is True
    assert repository.mark_published(outbox_id=next(iter(leased_ids))) is False

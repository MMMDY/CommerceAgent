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


def test_safety_p0_projection_is_tenant_scoped_and_redacted(engine: Engine) -> None:
    repository = AuditRepository(engine)
    tenant_id = f"safety-audit-{uuid4()}"
    repository.append(
        tenant_id=tenant_id,
        actor_ref="safety-router",
        event_type="safety_p0_detected",
        payload={
            "run_id": str(uuid4()),
            "category": "privacy",
            "reason_code": "SENSITIVE_FIELD",
            "detector_version": "deterministic-safety-v1",
            "disposition": "deescalate",
            "raw_user_text": "must-not-leak",
        },
        payload_hash="hash",
    )
    result = repository.recent_safety_p0(tenant_id=tenant_id)
    assert len(result) == 1
    assert result[0]["payload"]["category"] == "privacy"
    assert "raw_user_text" not in result[0]["payload"]
    assert repository.recent_safety_p0(tenant_id=f"other-{tenant_id}") == []


def test_evaluation_approval_projection_is_latest_redacted_audit(engine: Engine) -> None:
    repository = AuditRepository(engine)
    tenant_id = f"eval-approval-{uuid4()}"
    eval_run_id = str(uuid4())
    repository.append(
        tenant_id=tenant_id,
        actor_ref="approver-a",
        event_type="evaluation_human_approval",
        payload={
            "eval_run_id": eval_run_id,
            "decision": "approve",
            "status": "approved",
            "reason_hash": "sha256:" + "a" * 64,
            "raw_reason": "must-not-leak",
        },
        payload_hash="approval-a",
    )
    result = repository.latest_evaluation_approval(
        tenant_id=tenant_id, eval_run_id=eval_run_id
    )
    assert result is not None
    assert result["status"] == "approved"
    assert result["approver_ref"] == "approver-a"
    assert "raw_reason" not in result
    assert repository.latest_evaluation_approval(
        tenant_id=f"other-{tenant_id}", eval_run_id=eval_run_id
    ) is None

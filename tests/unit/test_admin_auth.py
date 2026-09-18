from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.api.main import create_app, require_admin, require_approver
from src.config import Settings


def test_admin_auth_uses_constant_time_bearer_contract() -> None:
    settings = Settings(demo_mode=False, internal_admin_token=SecretStr("admin-secret"))
    assert require_admin("Bearer admin-secret", settings=settings) == "admin"
    try:
        require_admin("Bearer wrong", settings=settings)
    except HTTPException as error:
        assert error.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("invalid admin token must be rejected")


def test_demo_without_token_is_available_only_in_demo_mode() -> None:
    assert require_admin(
        None, x_demo_actor="demo-user-001", settings=Settings(demo_mode=True)
    ) == "demo-admin"


def test_approver_role_is_separate_from_read_only_admin() -> None:
    settings = Settings(
        demo_mode=False,
        internal_admin_token=SecretStr("admin-secret"),
        internal_approver_token=SecretStr("approver-secret"),
    )
    assert require_approver("Bearer approver-secret", settings=settings) == "approver"
    try:
        require_approver("Bearer admin-secret", settings=settings)
    except HTTPException as error:
        assert error.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("read-only admin token must not approve changes")


def test_internal_endpoint_rejects_unauthenticated_request_before_resource_lookup() -> None:
    app = create_app()
    client = TestClient(app)
    response = client.get("/internal/v1/metrics")

    assert response.status_code in {403, 404}
    assert "admin_required" in response.text or "not_found" in response.text


def test_safety_audit_endpoint_requires_admin() -> None:
    client = TestClient(create_app())
    response = client.get("/internal/v1/safety/events")

    assert response.status_code in {403, 404}
    assert "admin_required" in response.text or "not_found" in response.text


def test_learning_summary_endpoint_requires_admin() -> None:
    client = TestClient(create_app())
    response = client.get("/internal/v1/operations/learning-summary")

    assert response.status_code in {403, 404}
    assert "admin_required" in response.text or "not_found" in response.text


def test_failure_to_skill_endpoint_requires_admin() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/internal/v1/failures/00000000-0000-0000-0000-000000000001/skill",
        json={"idempotency_key": "failure-skill-001"},
    )

    assert response.status_code in {403, 404}
    assert "admin_required" in response.text or "not_found" in response.text


def test_skill_kill_switch_requires_approver() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/internal/v1/skills/kill-switch",
        json={
            "enabled": False,
            "reason": "incident",
            "confirmation": "CONFIRM SKILL_KILL_SWITCH demo-tenant",
            "idempotency_key": "kill-switch-001",
        },
    )

    assert response.status_code in {403, 404}
    assert "approver_required" in response.text or "not_found" in response.text


def test_skill_kill_switch_read_endpoint_requires_admin() -> None:
    client = TestClient(create_app())
    response = client.get("/internal/v1/skills/kill-switch")

    assert response.status_code in {403, 404}
    assert "admin_required" in response.text or "not_found" in response.text


def test_evaluation_approval_mutation_requires_approver() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/internal/v1/evals/00000000-0000-0000-0000-000000000001/approval",
        json={
            "decision": "approve",
            "reason": "reviewed",
            "confirmation": "CONFIRM EVALUATION_APPROVAL 00000000-0000-0000-0000-000000000001",
            "idempotency_key": "eval-approval-001",
        },
    )
    assert response.status_code in {403, 404}
    assert "approver_required" in response.text or "not_found" in response.text

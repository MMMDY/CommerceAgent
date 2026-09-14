"""Phase 0 application health contracts."""

from fastapi.testclient import TestClient

from apps.api.bootstrap import ReadinessDependencies
from apps.api.main import create_app
from src.config import Settings
from src.orchestration.readiness import RuntimeRegistrationContainer
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.policies.engine import FactCondition, PolicyEffect, PolicyEngine, PolicyRule
from src.protocols import RetryPolicy, ToolRisk, ToolSpec
from src.tools.registry import ToolRegistry


def _settings() -> Settings:
    return Settings(
        model="model",
        api_base="https://provider.test",
        api_key="secret",
        classifier_model="model",
        classifier_api_base="https://provider.test",
        classifier_api_key="secret",
        classifier_temperature=0.1,
    )


def _complete_runtime() -> RuntimeRegistrationContainer:
    return RuntimeRegistrationContainer(
        settings=_settings(),
        tools=ToolRegistry(
            (
                ToolSpec(
                    name="read",
                    version="1",
                    input_schema={},
                    output_schema={},
                    risk=ToolRisk.READ_ONLY,
                    required_scopes=(),
                    timeout_ms=1,
                    retry_policy=RetryPolicy(max_attempts=1),
                    model_visible=True,
                ),
            )
        ),
        workflows=WorkflowRegistry((WorkflowDefinition("w", "1", ("s",)),)),
        policy=PolicyEngine(
            version="v1",
            allowed_facts=frozenset({"owner"}),
            rules=(
                PolicyRule(
                    "allow",
                    "read",
                    1,
                    (FactCondition("owner", "eq", True),),
                    PolicyEffect.ALLOW,
                    "OK",
                ),
            ),
        ),
    )


def test_live_endpoint_is_always_available() -> None:
    response = TestClient(create_app()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_ready_endpoint_fails_closed_without_database_configuration() -> None:
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_ready_endpoint_requires_database_and_complete_runtime_registrations() -> None:
    database_calls = 0

    def database_ready() -> tuple[bool, str]:
        nonlocal database_calls
        database_calls += 1
        return True, "ready"

    dependencies = ReadinessDependencies(database=database_ready, runtime=_complete_runtime())

    response = TestClient(create_app(readiness=dependencies)).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert database_calls == 1


def test_ready_endpoint_checks_runtime_even_when_database_is_unavailable() -> None:
    runtime = RuntimeRegistrationContainer.unconfigured(
        settings=_settings()
    )
    dependencies = ReadinessDependencies(
        database=lambda: (False, "database_or_migration_unavailable"),
        runtime=runtime,
    )

    response = TestClient(create_app(readiness=dependencies)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "database_or_migration_unavailable",
    }


def test_ready_endpoint_reports_runtime_failure_after_database_passes() -> None:
    runtime = RuntimeRegistrationContainer.unconfigured(
        settings=_settings()
    )
    dependencies = ReadinessDependencies(database=lambda: (True, "ready"), runtime=runtime)

    response = TestClient(create_app(readiness=dependencies)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reason": "tool_registry_incomplete"}


def test_spa_routes_fall_back_to_the_built_web_shell() -> None:
    client = TestClient(create_app())

    for path in ("/", "/runs/demo", "/evals"):
        response = client.get(path)
        assert response.status_code == 200
        assert "CommerceAgent" in response.text

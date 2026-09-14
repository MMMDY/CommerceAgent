from src.config import Settings
from src.orchestration.readiness import RuntimeRegistrationContainer, check_runtime_ready
from src.orchestration.runtime_bootstrap import build_runtime_registrations
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.policies.engine import FactCondition, PolicyEffect, PolicyEngine, PolicyRule
from src.protocols import RetryPolicy, ToolRisk, ToolSpec
from src.tools.registry import ToolRegistry


def _policy() -> PolicyEngine:
    return PolicyEngine(
        version="v1",
        allowed_facts=frozenset({"owner"}),
        rules=(
            PolicyRule(
                "allow", "read", 1, (FactCondition("owner", "eq", True),), PolicyEffect.ALLOW, "OK"
            ),
        ),
    )


def _tools() -> ToolRegistry:
    return ToolRegistry(
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
    )


def test_runtime_readiness_requires_local_configuration_and_every_registry() -> None:
    kwargs = {
        "tools": _tools(),
        "workflows": WorkflowRegistry((WorkflowDefinition("w", "1", ("s",)),)),
        "policy": _policy(),
    }
    missing_model = Settings(model=None, api_base=None, api_key=None)
    assert check_runtime_ready(settings=missing_model, **kwargs) == (
        False,
        "model_configuration_unavailable",
    )
    settings = Settings(model="m", api_base="https://provider.test", api_key="key")
    assert check_runtime_ready(settings=settings, **kwargs) == (True, "ready")


def test_runtime_readiness_rejects_each_incomplete_registration() -> None:
    settings = Settings(model="m", api_base="https://provider.test", api_key="key")
    tools = _tools()
    workflows = WorkflowRegistry((WorkflowDefinition("w", "1", ("s",)),))
    policy = _policy()

    assert check_runtime_ready(
        settings=settings,
        tools=ToolRegistry(()),
        workflows=workflows,
        policy=policy,
    ) == (False, "tool_registry_incomplete")
    assert check_runtime_ready(
        settings=settings,
        tools=tools,
        workflows=WorkflowRegistry(()),
        policy=policy,
    ) == (False, "workflow_registry_incomplete")
    assert check_runtime_ready(
        settings=settings,
        tools=tools,
        workflows=workflows,
        policy=None,
    ) == (False, "policy_registry_incomplete")


def test_unconfigured_runtime_container_fails_closed() -> None:
    container = RuntimeRegistrationContainer.unconfigured(
        settings=Settings(model="m", api_base="https://provider.test", api_key="key")
    )

    assert container.check() == (False, "tool_registry_incomplete")


def test_phase2_bootstrap_registers_a_complete_local_runtime_catalog() -> None:
    container = build_runtime_registrations(
        settings=Settings(model="m", api_base="https://provider.test", api_key="key")
    )

    assert container.check() == (True, "ready")

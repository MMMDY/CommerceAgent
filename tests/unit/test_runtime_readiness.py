from src.config import Settings
from src.orchestration.readiness import check_runtime_ready
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

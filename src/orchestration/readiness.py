"""No-network runtime registration readiness checks."""

from __future__ import annotations

from src.config import Settings
from src.orchestration.workflows import WorkflowRegistry
from src.policies.engine import PolicyEngine
from src.tools.registry import ToolRegistry


def check_runtime_ready(
    *, settings: Settings, tools: ToolRegistry, workflows: WorkflowRegistry, policy: PolicyEngine
) -> tuple[bool, str]:
    """Check only local config/registration; never invoke a model provider."""

    if not settings.model or not settings.api_base or not settings.api_key:
        return False, "model_configuration_unavailable"
    if len(tools) == 0 or not tools.model_visible_names():
        return False, "tool_registry_incomplete"
    if len(workflows) == 0:
        return False, "workflow_registry_incomplete"
    if len(policy) == 0:
        return False, "policy_registry_incomplete"
    return True, "ready"

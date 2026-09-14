"""No-network runtime registration readiness checks."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from src.config import Settings
from src.orchestration.workflows import WorkflowRegistry
from src.policies.engine import PolicyEngine
from src.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class RuntimeRegistrationContainer:
    """The immutable runtime registrations inspected by API readiness.

    The container deliberately contains configuration and registries only.  A
    model gateway is not accepted here, so a health probe cannot accidentally
    make a billable or stateful provider request.
    """

    settings: Settings
    tools: ToolRegistry
    workflows: WorkflowRegistry
    policy: PolicyEngine | None

    @classmethod
    def unconfigured(cls, *, settings: Settings) -> RuntimeRegistrationContainer:
        """Create the fail-closed default used until Runtime bootstrap is wired."""

        return cls(
            settings=settings,
            tools=ToolRegistry(()),
            workflows=WorkflowRegistry(()),
            policy=None,
        )

    def check(self) -> tuple[bool, str]:
        return check_runtime_ready(
            settings=self.settings,
            tools=self.tools,
            workflows=self.workflows,
            policy=self.policy,
        )


def check_runtime_ready(
    *,
    settings: Settings,
    tools: ToolRegistry,
    workflows: WorkflowRegistry,
    policy: PolicyEngine | None,
) -> tuple[bool, str]:
    """Check only local config/registration; never invoke a model provider."""

    if not _non_empty(settings.model) or not _non_empty(settings.api_base):
        return False, "model_configuration_unavailable"
    if not _secret_configured(settings.api_key):
        return False, "model_configuration_unavailable"
    if not settings.classifier_configuration_is_valid():
        return False, "classifier_configuration_unavailable"
    if len(tools) == 0 or not tools.model_visible_names():
        return False, "tool_registry_incomplete"
    if len(workflows) == 0:
        return False, "workflow_registry_incomplete"
    if policy is None or len(policy) == 0:
        return False, "policy_registry_incomplete"
    return True, "ready"


def _non_empty(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _secret_configured(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())

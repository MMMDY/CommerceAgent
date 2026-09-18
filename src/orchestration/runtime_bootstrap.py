"""Static Phase 2 runtime registrations used by the API readiness boundary.

This module intentionally builds definitions only.  It does not create a
model gateway, adapter, database connection, or background worker, so loading
it during a health probe cannot make a provider request or a business call.
"""

from __future__ import annotations

from src.config import Settings
from src.orchestration.readiness import RuntimeRegistrationContainer
from src.orchestration.route_catalog import DEFAULT_INTENT_ROUTE_RULES
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.policies.engine import FactCondition, PolicyEffect, PolicyEngine, PolicyRule
from src.tools.readonly_specs import readonly_tool_specs
from src.tools.registry import ToolRegistry
from src.tools.write_specs import low_risk_tool_specs, prepare_tool_specs


def build_runtime_registrations(*, settings: Settings) -> RuntimeRegistrationContainer:
    """Return the immutable Phase 2 catalog checked by ``/health/ready``.

    ``retrieve_knowledge`` is a registered future readonly capability, not an
    adapter.  Phase 3 wires its PostgreSQL-backed adapter and API path.  Until
    then, any attempt to execute it has no adapter and fails closed.
    """

    tools = readonly_tool_specs() + prepare_tool_specs() + low_risk_tool_specs()
    policy = PolicyEngine(
        version="phase2-readonly-v1",
        allowed_facts=frozenset({"request.authenticated"}),
        rules=tuple(
            PolicyRule(
                rule_id=f"allow-authenticated-{tool.name}", applies_to=tool.name, priority=100,
                conditions=(FactCondition("request.authenticated", "eq", True),),
                effect=PolicyEffect.ALLOW, reason_code="AUTHENTICATED_READ",
            ) for tool in tools
        ),
    )
    workflows = {
        (rule.workflow_id, rule.workflow_version)
        for rule in DEFAULT_INTENT_ROUTE_RULES
    }
    workflows.add(("knowledge_query", "1"))
    workflows.add(("conversational_response", "1"))
    write_workflow_ids = {
        "cancel_order",
        "change_order",
        "refund",
        "return",
        "exchange",
        "invoice_request",
        "delivery_issue",
    }
    definitions: list[WorkflowDefinition] = []
    for workflow_id, version in sorted(workflows):
        steps: tuple[str, ...]
        if workflow_id in write_workflow_ids:
            steps = (
                "authenticate",
                "load_resource",
                "check_eligibility",
                "collect_slots",
                "prepare",
                "confirm_mutation",
                "commit_mutation",
                "verify_mutation",
            )
        else:
            steps = ("retrieve",)
        definitions.append(WorkflowDefinition(workflow_id, version, steps))
    return RuntimeRegistrationContainer(
        settings=settings,
        tools=ToolRegistry(tools),
        workflows=WorkflowRegistry(tuple(definitions)),
        policy=policy,
    )

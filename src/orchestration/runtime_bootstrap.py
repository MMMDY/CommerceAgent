"""Static Phase 2 runtime registrations used by the API readiness boundary.

This module intentionally builds definitions only.  It does not create a
model gateway, adapter, database connection, or background worker, so loading
it during a health probe cannot make a provider request or a business call.
"""

from __future__ import annotations

from src.config import Settings
from src.orchestration.readiness import RuntimeRegistrationContainer
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.policies.engine import FactCondition, PolicyEffect, PolicyEngine, PolicyRule
from src.protocols import RetryPolicy, ToolRisk, ToolSpec
from src.tools.registry import ToolRegistry


def build_runtime_registrations(*, settings: Settings) -> RuntimeRegistrationContainer:
    """Return the immutable Phase 2 catalog checked by ``/health/ready``.

    ``retrieve_knowledge`` is a registered future readonly capability, not an
    adapter.  Phase 3 wires its PostgreSQL-backed adapter and API path.  Until
    then, any attempt to execute it has no adapter and fails closed.
    """

    tool = ToolSpec(
        name="retrieve_knowledge",
        version="1",
        input_schema={
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "properties": {"evidence_ids": {"type": "array"}},
            "required": ["evidence_ids"],
            "additionalProperties": False,
        },
        risk=ToolRisk.READ_ONLY,
        required_scopes=("knowledge:read",),
        timeout_ms=3_000,
        retry_policy=RetryPolicy(max_attempts=2, backoff_ms=(100,)),
        model_visible=True,
        allowed_workflows=("knowledge_query@1",),
        allowed_steps=("retrieve",),
    )
    policy = PolicyEngine(
        version="phase2-readonly-v1",
        allowed_facts=frozenset({"request.authenticated"}),
        rules=(
            PolicyRule(
                rule_id="allow-authenticated-knowledge-read",
                applies_to="retrieve_knowledge",
                priority=100,
                conditions=(FactCondition("request.authenticated", "eq", True),),
                effect=PolicyEffect.ALLOW,
                reason_code="AUTHENTICATED_READ",
            ),
        ),
    )
    return RuntimeRegistrationContainer(
        settings=settings,
        tools=ToolRegistry((tool,)),
        workflows=WorkflowRegistry((WorkflowDefinition("knowledge_query", "1", ("retrieve",)),)),
        policy=policy,
    )

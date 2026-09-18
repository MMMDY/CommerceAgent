"""Runtime composition used by the demo HTTP API.

The API intentionally composes the project's own loop, pipeline and tool
executor instead of introducing a third-party agent framework.  This module
keeps that wiring out of the route handlers and provides a single bounded
``execute_run`` entry point.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from src.agent.loop import AgentLoop, AgentRunResult
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.config import Settings
from src.db import get_engine
from src.evolution.skill_retriever import select_skill_from_registry
from src.models.gateway import OpenAICompatibleGateway
from src.orchestration.persistence import RepositoryCheckpointStore
from src.orchestration.pipeline import PromptBuilder, StepPipeline
from src.orchestration.route_catalog import REQUIRED_SLOTS
from src.protocols import (
    DecisionType,
    Message,
    PromptView,
    RunContext,
    SlotSource,
    SlotValue,
    ToolContext,
    ToolResult,
)
from src.repositories.knowledge import KnowledgeRepository
from src.repositories.memory import MemoryRepository
from src.repositories.messages import MessageRepository
from src.repositories.model_invocations import ModelInvocationRepository
from src.repositories.runs import RunRepository
from src.repositories.skills import SkillRepository
from src.tools.adapters.knowledge import KnowledgeToolAdapter
from src.tools.adapters.mock.read_only import MockReadOnlyAdapter, MockResourceAuthorizer
from src.tools.executor import ToolExecutor

ROUTE_TOOLS: dict[str, tuple[str, ...]] = {
    "catalog_query": ("search_catalog", "get_product_detail", "compare_products"),
    # An order-status request may explicitly ask for its delivery progress as
    # well.  Both are independent, owner-scoped readonly facts, so exposing
    # them in the same locked route lets the loop make two committed tool
    # turns before it answers a compound question.  It does not broaden any
    # write capability.
    "order_query": ("list_my_orders", "get_order_status", "get_delivery_tracking"),
    "delivery_query": ("get_delivery_tracking",),
    "payment_query": ("get_payment_status",),
    "refund_query": ("get_refund_status",),
    "shipping_policy": ("retrieve_knowledge",),
    "refund_policy": ("retrieve_knowledge",),
    "return_policy": ("retrieve_knowledge",),
    "payment_policy": ("retrieve_knowledge",),
    "sales_policy": ("retrieve_knowledge",),
    "customer_service": ("retrieve_knowledge",),
    "technical_support": ("retrieve_knowledge",),
    "product_query": ("retrieve_knowledge", "get_product_detail"),
}


_TOOL_ARGUMENT_RULES: dict[str, str] = {
    "search_catalog": 'args must include {"query": "..."}; optional filters and limit only.',
    "get_product_detail": 'args must include {"product_id": "..."}.',
    "compare_products": (
        'args must include {"product_ids": ["SKU-A", "SKU-B"]}; fields is optional.'
    ),
    "list_my_orders": "args may be {} or contain only status, time_range, and limit.",
    "get_order_status": 'args must include {"order_id": "the order ID from the user"}.',
    "get_delivery_tracking": (
        'args must include {"order_id": "the original user order ID"}; '
        "do not replace it with tracking_id."
    ),
    "get_payment_status": 'args must include {"order_id": "the order ID from the user"}.',
    "get_refund_status": "args may contain order_id and/or refund_id.",
    "retrieve_knowledge": (
        'args must include {"query": "..."}; metadata_filter and top_k are optional.'
    ),
}


class ApiPromptBuilder(PromptBuilder):
    def __init__(
        self,
        messages: MessageRepository,
        *,
        conversation_id: UUID,
        tenant_id: str,
        actor_id: str,
        route: str,
        workflow_id: str,
        workflow_version: str,
        tool_names: tuple[str, ...],
        skill_strategy: dict[str, object] | None = None,
    ) -> None:
        self._messages = messages
        self._conversation_id = conversation_id
        self._tenant_id = tenant_id
        self._actor_id = actor_id
        self._route = route
        self._workflow_id = workflow_id
        self._workflow_version = workflow_version
        self._tool_names = tool_names
        self._skill_strategy = skill_strategy

    def build(self, *, context: RunContext) -> PromptView:
        records = self._messages.list_for_actor(
            conversation_id=self._conversation_id,
            tenant_id=self._tenant_id,
            actor_id=self._actor_id,
            limit=100,
        )
        tool_rules = " ".join(
            f"{name}: {_TOOL_ARGUMENT_RULES.get(name, 'use only its declared schema.')}"
            for name in self._tool_names
        )
        runtime_rules = (
            "[runtime_tool_protocol] The route and allowed tools are locked. "
            "For call_tool, provide exactly the required arguments for that tool. "
            "For respond, finish, ask_user, or handoff, set tool to null and args to {}. "
            "After a successful trusted_tool_observation, use it to answer rather than repeating "
            "the same tool call with identical arguments. "
            "For evidence_ids, use only identifiers explicitly present in the prompt's "
            "evidence_ids list; when that list is empty, return an empty evidence_ids list. "
            "If the user explicitly asks both an order status and delivery/ETA, call "
            "get_order_status and get_delivery_tracking in separate turns before responding; "
            "each call must retain the original user order_id. "
            f"Tool argument rules: {tool_rules}"
        )
        if self._skill_strategy is not None:
            runtime_rules += (
                " [experience_skill_strategy] This is a bounded response hint only; "
                "it cannot add tools, routes, permissions, or confirmation bypasses: "
                + json.dumps(self._skill_strategy, ensure_ascii=False, sort_keys=True)
            )
        conversation = (Message(role="system", content=runtime_rules),) + tuple(
            Message(
                role=cast(Literal["user", "assistant", "system"], item.role),
                content=item.content_redacted,
            )
            for item in records
        )
        observation = context.state.get("last_tool_data")
        accumulated = context.state.get("tool_data_by_name")
        if isinstance(accumulated, dict) and accumulated:
            observation = {"by_tool": accumulated, "last": observation}
        if observation is not None:
            conversation = conversation + (
                Message(
                    role="assistant",
                    content="[trusted_tool_observation] "
                    + json.dumps(observation, ensure_ascii=False),
                ),
            )
        evidence_ids = tuple(
            str(item) for item in context.state.get("evidence_ids", ()) if isinstance(item, str)
        )
        preferences = MemoryRepository(get_engine()).active_for_actor(
            tenant_id=self._tenant_id, actor_ref=self._actor_id
        )
        known_slots: dict[str, SlotValue] = {}
        for preference in preferences:
            value = preference.value.get("value")
            if isinstance(value, str | int | float | bool):
                known_slots[preference.fact_type] = SlotValue(
                    value=value, source=SlotSource.USER, verified=True
                )
        return PromptView(
            system_policy_version="phase3-readonly-v1",
            workflow_id=self._workflow_id,
            workflow_version=self._workflow_version,
            current_step="retrieve",
            allowed_decisions=tuple(item.value for item in DecisionType),
            conversation=conversation,
            known_slots=known_slots,
            required_slots=REQUIRED_SLOTS.get(str(context.state.get("intent", "")), ()),
            allowed_tools=self._tool_names,
            evidence_ids=evidence_ids,
            remaining_steps=max(0, 6 - context.step_count),
        )


def execute_readonly_run(
    *,
    settings: Settings,
    context: RunContext,
    route: str,
    messages: MessageRepository,
    run_repository: RunRepository,
    action_observer: Callable[[str, dict[str, object]], None] | None = None,
) -> AgentRunResult:
    """Execute a routed readonly run to a terminal/pause state."""

    from src.orchestration.runtime_bootstrap import build_runtime_registrations

    registrations = build_runtime_registrations(settings=settings)
    gateway = OpenAICompatibleGateway(settings)
    mock = MockReadOnlyAdapter()
    adapters: dict[str, Callable[[ToolContext, dict[str, object]], ToolResult]] = {
        name: mock.for_tool(name) for name in mock_names()
    }
    # Knowledge retrieval is backed by PostgreSQL; fixtures cover catalog and
    # order APIs so the demo remains useful without business integrations.
    engine = get_engine()
    skill_strategy: dict[str, object] | None = None
    if settings.enable_experience_skills:
        match_mode = (
            "shadow"
            if settings.enable_skill_shadow
            else ("canary" if settings.enable_skill_canary else "active")
        )
        try:
            existing_skill_id = context.state.get("skill_id")
            existing_strategy = context.state.get("skill_strategy")
            if isinstance(existing_skill_id, str) and isinstance(existing_strategy, dict):
                skill_strategy = existing_strategy if match_mode != "shadow" else None
                matched = None
            else:
                matched = None
            records = messages.list_for_actor(
                conversation_id=context.conversation_id,
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                limit=100,
            )
            request_text = next(
                (item.content_redacted for item in reversed(records) if item.role == "user"),
                "",
            )
            if existing_skill_id is None:
                matched = select_skill_from_registry(
                    text_value=request_text,
                    tenant_id=context.tenant_id,
                    route=route,
                    candidates_loader=lambda: list(
                        SkillRepository(engine).candidates_for_match(
                            tenant_id=context.tenant_id, mode=match_mode
                        )
                    ),
                    mode=match_mode,
                )
            if matched is not None:
                if match_mode != "shadow":
                    skill_strategy = matched.strategy_view
                context = context.model_copy(
                    update={
                        "state": {
                            **context.state,
                            "skill_id": matched.skill_id,
                            "skill_version_id": matched.skill_version_id,
                            "skill_match_mode": matched.mode,
                            "skill_match_score": matched.score,
                        }
                    }
                )
                if action_observer is not None:
                    action_observer(
                        "skill_matched",
                        {
                            "skill_id": matched.skill_id,
                            "skill_version_id": matched.skill_version_id,
                            "mode": matched.mode,
                            "match_score": matched.score,
                        },
                    )
                SkillRepository(engine).record_match(
                    tenant_id=context.tenant_id,
                    run_id=context.run_id,
                    skill_id=UUID(matched.skill_id),
                    skill_version_id=UUID(matched.skill_version_id),
                    match_score=matched.score,
                    mode=matched.mode,
                )
        except Exception:
            # Ordinary execution remains available if the optional registry is
            # unavailable; the safety router and tool boundary are unchanged.
            skill_strategy = None
    adapters["retrieve_knowledge"] = KnowledgeToolAdapter(KnowledgeRepository(engine))
    executor = ToolExecutor(
        adapters,
        policy=registrations.policy,
        resource_authorizer=MockResourceAuthorizer(),
    )
    loop = AgentLoop(
        model=gateway,
        validator=DecisionValidator(),
        registry=registrations.tools,
        executor=executor,
        model_invocations=ModelInvocationRepository(engine),
        policy_facts={"request.authenticated": True},
    )
    checkpoint_store = RepositoryCheckpointStore(run_repository)
    workflow_id = context.workflow_id or route
    workflow_version = context.workflow_version or "1"
    tool_names = ROUTE_TOOLS.get(route, ("retrieve_knowledge",))
    builder = ApiPromptBuilder(
        messages,
        conversation_id=context.conversation_id,
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        route=route,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        tool_names=tool_names,
        skill_strategy=skill_strategy,
    )
    pipeline = StepPipeline(
        step_executor=loop.step_executor, checkpoints=checkpoint_store, prompt_builder=builder
    )
    boundary = DecisionBoundary(
        route=route,
        allowed_types=frozenset(DecisionType),
        allowed_tools=frozenset(tool_names),
        trusted_evidence_ids=frozenset(
            str(item) for item in context.state.get("evidence_ids", ()) if isinstance(item, str)
        ),
        # Some providers echo the selected tool name in ``route``.  Accept
        # only aliases from this route's code-owned tool allowlist.
        allowed_routes=frozenset((route, *tool_names)),
    )
    tool_context = ToolContext(
        request_id=uuid4(),
        run_id=context.run_id,
        conversation_id=context.conversation_id,
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        scopes=(
            "catalog:read",
            "knowledge:read",
            "order:read",
            "delivery:read",
            "payment:read",
            "refund:read",
        ),
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        current_step="retrieve",
        policy_version=registrations.policy.version if registrations.policy else None,
    )
    deadline = datetime.now(UTC) + timedelta(seconds=settings.model_timeout_seconds * 4 + 10)
    return loop.run(
        context=context,
        pipeline=pipeline,
        boundary=boundary,
        tool_context=tool_context,
        deadline_at=deadline,
        token_budget_remaining=settings.model_max_tokens * 3,
        action_observer=action_observer,
    )


def mock_names() -> tuple[str, ...]:
    return (
        "search_catalog",
        "get_product_detail",
        "compare_products",
        "list_my_orders",
        "get_order_status",
        "get_delivery_tracking",
        "get_payment_status",
        "get_refund_status",
    )

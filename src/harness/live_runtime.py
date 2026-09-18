"""Live-model evaluation runtime with a fail-closed side-effect boundary.

This adapter deliberately uses the same classifier, bounded AgentLoop,
PostgreSQL knowledge adapter, tool registry and policy engine as the API.  It
does not create a user-visible conversation or commit a business mutation;
each case receives an independent in-memory RunContext and UUID.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal, Protocol, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.agent.intent_classifier import IntentClassifier
from src.agent.loop import AgentLoop, AgentRunResult
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.config import Settings
from src.cost.calculator import CostCalculator
from src.cost.models import ModelPricing
from src.harness.runtime import RuntimeTrace
from src.harness.sandbox_tools import SandboxToolPolicy
from src.harness.schema import RuntimeCaseInput
from src.models.gateway import (
    ModelDecision,
    ModelGateway,
    ModelGatewayError,
    OpenAICompatibleGateway,
)
from src.orchestration.api_runtime import ROUTE_TOOLS
from src.orchestration.pipeline import CheckpointStore, PromptBuilder, StepPipeline
from src.orchestration.response_policy import conversational_route_allowed
from src.orchestration.risk_router import assess_request
from src.orchestration.route_catalog import REQUIRED_SLOTS, intent_route_rules
from src.orchestration.router import IntentRouter, RouteOutcome
from src.orchestration.runtime_bootstrap import build_runtime_registrations
from src.protocols import (
    DecisionType,
    Message,
    PromptView,
    RequestDomain,
    RequestRiskLevel,
    ResponsePolicy,
    RoutingPromptView,
    RunContext,
    RunStatus,
    ToolContext,
    ToolResult,
)
from src.rag.retrieval import KnowledgeRetriever
from src.repositories.knowledge import KnowledgeRepository
from src.tools.adapters.knowledge import KnowledgeToolAdapter
from src.tools.adapters.mock.read_only import MockReadOnlyAdapter, MockResourceAuthorizer
from src.tools.executor import ToolExecutor


class LiveConfigurationError(RuntimeError):
    """Raised when a live run is requested without an explicit live profile."""


class _PricingLookup(Protocol):
    def find(
        self, *, provider: str, model: str, at: datetime | None = None
    ) -> ModelPricing | None: ...


@dataclass(frozen=True, slots=True)
class LiveInvocation:
    purpose: str
    latency_ms: int | None
    total_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_microusd: int | None
    estimated: bool


class LiveInvocationRecorder:
    """Collect redacted accounting metadata without requiring an agent_runs row."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        conservative_tokens: int,
        pricing: _PricingLookup | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.config_hash = "sha256:live-eval-recorder"
        self._conservative_tokens = conservative_tokens
        self._pricing = pricing
        self.items: list[LiveInvocation] = []

    def record_success(
        self,
        *,
        context: RunContext,
        prompt: Any,
        result: ModelDecision,
        provider: str,
        model: str,
        config_hash: str,
    ) -> None:
        del context, prompt, config_hash
        self._record(
            purpose="agent",
            latency_ms=result.latency_ms,
            usage=result.normalized_token_usage,
            provider=provider,
            model=model,
        )

    def record_failure(
        self,
        *,
        context: RunContext,
        prompt: Any,
        provider: str,
        model: str,
        config_hash: str,
        error_code: str,
    ) -> None:
        del context, prompt, config_hash, error_code
        self.items.append(LiveInvocation("agent", None, None, None, None, None, False))
        del provider, model

    def record_classification_success(
        self,
        *,
        context: RunContext,
        prompt: RoutingPromptView,
        result: Any,
        provider: str,
        model: str,
        config_hash: str,
        latency_ms: int,
        token_usage: Any,
    ) -> None:
        del context, prompt, result, config_hash
        self._record(
            purpose="intent_classification",
            latency_ms=latency_ms,
            usage=token_usage,
            provider=provider,
            model=model,
        )

    def _record(
        self,
        *,
        purpose: str,
        latency_ms: int | None,
        usage: Any,
        provider: str,
        model: str,
    ) -> None:
        if usage is None:
            # A provider may omit usage metadata.  Keep the run measurable,
            # but make the estimate explicit so it cannot be mistaken for
            # provider-billed usage.
            from src.protocols import TokenUsage

            usage = TokenUsage(
                total_tokens=self._conservative_tokens,
                estimated=True,
                provider_usage_version="conservative-v1",
            )
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        estimated = bool(getattr(usage, "estimated", False))
        pricing = None
        if usage is not None and self._pricing is not None:
            try:
                pricing = self._pricing.find(provider=provider, model=model)
            except Exception:
                pricing = None
        cost = (
            CostCalculator().total_microusd(usage=usage, pricing=pricing)
            if usage is not None
            else None
        )
        self.items.append(
            LiveInvocation(
                purpose,
                latency_ms,
                total_tokens,
                input_tokens,
                output_tokens,
                cost,
                estimated,
            )
        )

    @property
    def total_tokens(self) -> int | None:
        values = [item.total_tokens for item in self.items]
        return (
            sum(value for value in values if value is not None)
            if values and all(value is not None for value in values)
            else None
        )

    @property
    def total_cost_microusd(self) -> int | None:
        values = [item.cost_microusd for item in self.items]
        return (
            sum(value for value in values if value is not None)
            if values and all(value is not None for value in values)
            else None
        )

    @property
    def estimated_count(self) -> int:
        return sum(1 for item in self.items if item.estimated)


class _InMemoryCheckpoints(CheckpointStore):
    def __init__(self) -> None:
        self.context: RunContext | None = None
        self.sequence = 0

    def checkpoint(
        self,
        *,
        context: RunContext,
        status: RunStatus,
        next_step: str,
        state: dict[str, object],
        events: tuple[Any, ...],
    ) -> int:
        del next_step, events
        self.sequence += 1
        self.context = context.model_copy(
            update={
                "status": status,
                "state": deepcopy(state),
                "step_count": context.step_count + 1,
                "checkpoint_version": self.sequence,
            }
        )
        return self.sequence


class _LivePromptBuilder(PromptBuilder):
    def __init__(
        self,
        *,
        case: RuntimeCaseInput,
        route: str,
        workflow_id: str,
        workflow_version: str,
        tools: tuple[str, ...],
    ) -> None:
        self._case = case
        self._route = route
        self._workflow_id = workflow_id
        self._workflow_version = workflow_version
        self._tools = tools

    def build(self, *, context: RunContext) -> PromptView:
        conversation = tuple(
            _prompt_message(role=item.role, content=item.content) for item in self._case.messages
        )
        observation = context.state.get("last_tool_data")
        if observation is not None:
            conversation += (
                Message(
                    role="assistant",
                    content="[trusted_tool_observation] " + _bounded_json(observation),
                ),
            )
        rules = (
            "[live_eval_tool_protocol] The route and tool list are locked. "
            "Use only declared tools, do not claim an action succeeded without trusted evidence, "
            "and use only evidence identifiers present in the prompt. "
            f"Allowed route tools: {', '.join(self._tools) or 'none'}."
        )
        conversation = (Message(role="system", content=rules),) + conversation
        evidence_ids = tuple(
            item for item in context.state.get("evidence_ids", ()) if isinstance(item, str)
        )
        return PromptView(
            system_policy_version="live-eval-v1",
            workflow_id=self._workflow_id,
            workflow_version=self._workflow_version,
            current_step="retrieve",
            allowed_decisions=tuple(item.value for item in DecisionType),
            conversation=conversation,
            known_slots={},
            required_slots=REQUIRED_SLOTS.get(str(context.state.get("intent", "")), ()),
            allowed_tools=self._tools,
            evidence_ids=evidence_ids,
            remaining_steps=max(0, 6 - context.step_count),
        )


class LiveCaseRuntime:
    """Execute one evaluation case through the production model/knowledge boundaries."""

    def __init__(
        self,
        *,
        settings: Settings,
        tenant_id: str = "demo-tenant",
        actor_id: str = "demo-user-001",
        gateway: ModelGateway | None = None,
        knowledge_adapter: Callable[[ToolContext, dict[str, object]], ToolResult] | None = None,
    ) -> None:
        if gateway is None:
            if not settings.model or not settings.api_base or not settings.api_key:
                raise LiveConfigurationError("agent live configuration is unavailable")
            if not settings.classifier_configuration_is_valid():
                raise LiveConfigurationError("classifier live configuration is unavailable")
        self.settings = settings
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.gateway = gateway or OpenAICompatibleGateway(settings)
        self._knowledge_adapter = knowledge_adapter

    def execute_case(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> RuntimeTrace:
        del fixture
        started = perf_counter()
        run_id = uuid4()
        conversation_id = uuid5(NAMESPACE_URL, f"commerce-agent:live-eval:{run_id}")
        context = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=self.tenant_id,
            actor_id=self.actor_id,
            status=RunStatus.CREATED,
        )
        recorder = self._recorder()
        user_text = " ".join(item.content for item in case.messages if item.role == "user")
        if cancelled():
            return self._trace(
                case, context, recorder, started, response="", next_action="cancelled"
            )
        assessment = assess_request(user_text)
        if assessment.hard_block:
            from src.safety.responses import safe_response_for

            return self._trace(
                case,
                context,
                recorder,
                started,
                route="safety_router",
                intent="safety_boundary",
                response=safe_response_for(assessment.safety_category),
                next_action="safe_deescalation",
                status="complete",
            )

        routing_prompt = RoutingPromptView(
            conversation=tuple(
                _prompt_message(role=item.role, content=item.content) for item in case.messages
            ),
            allowed_intents=tuple(
                rule.intent
                for rule in intent_route_rules(routing_v2=True, conversational_fallback=True)
            ),
        )
        try:
            candidate = IntentClassifier(gateway=self.gateway, invocations=recorder).classify(
                context=context, prompt=routing_prompt
            )
        except ModelGatewayError:
            return self._trace(
                case,
                context,
                recorder,
                started,
                response="",
                next_action="model_unavailable",
                status="fail",
            )
        candidate_updates: dict[str, object] = {}
        if (
            candidate.domain is RequestDomain.UNKNOWN
            and assessment.domain is not RequestDomain.UNKNOWN
        ):
            candidate_updates["domain"] = assessment.domain
        if (
            candidate.request_risk_level is RequestRiskLevel.UNKNOWN
            and assessment.risk_level is not RequestRiskLevel.UNKNOWN
        ):
            candidate_updates["request_risk_level"] = assessment.risk_level
        if candidate_updates:
            candidate = candidate.model_copy(update=candidate_updates)
        # A deterministic or future semantic safety assessment always wins
        # over an ordinary business/conversational route.
        if candidate.request_risk_level is RequestRiskLevel.HIGH:
            from src.safety.responses import safe_response_for

            return self._trace(
                case,
                context,
                recorder,
                started,
                route="safety_router",
                intent="safety_boundary",
                response=safe_response_for(assessment.safety_category),
                next_action="safe_deescalation",
                status="complete",
            )
        route = IntentRouter(
            intent_route_rules(routing_v2=True, conversational_fallback=True)
        ).decide(candidate)
        if route.outcome is RouteOutcome.HANDOFF:
            return self._trace(
                case,
                context,
                recorder,
                started,
                route="router",
                intent=candidate.intent,
                response="该请求需要人工进一步核验。",
                next_action="handoff",
                status="wait_human",
            )
        if route.outcome is RouteOutcome.ASK_USER:
            return self._trace(
                case,
                context,
                recorder,
                started,
                route="router",
                intent=candidate.intent,
                response="我还需要你补充一些信息，才能继续处理。",
                next_action="ask_user",
                status="wait_user",
            )
        assert route.workflow_id is not None
        route_name = route.workflow_id
        if route.response_policy is not ResponsePolicy.EXECUTE and not conversational_route_allowed(
            policy=route.response_policy,
            domain=candidate.domain,
            risk_level=candidate.request_risk_level,
        ):
            return self._trace(
                case,
                context,
                recorder,
                started,
                route="router",
                intent=candidate.intent,
                response="该请求需要人工进一步核验。",
                next_action="handoff",
                status="wait_human",
            )
        if route_name not in ROUTE_TOOLS and route.response_policy is ResponsePolicy.EXECUTE:
            # The live runner never exposes write tools.  A real write decision
            # is observed as a prepare-only boundary rather than committed.
            return self._trace(
                case,
                context,
                recorder,
                started,
                route=route_name,
                intent=candidate.intent,
                response="该操作仅在评测 sandbox 中准备，未提交任何真实业务变更。",
                next_action="sandbox_prepare_only",
                status="complete",
            )

        tools = ROUTE_TOOLS.get(route_name, ())
        context = context.model_copy(
            update={
                "status": RunStatus.RUNNING_READONLY,
                "workflow_id": route_name,
                "workflow_version": route.workflow_version or "1",
                "state": {
                    "intent": candidate.intent,
                    "route": route_name,
                    "response_policy": route.response_policy.value,
                    "request_domain": candidate.domain.value,
                    "request_risk_level": candidate.request_risk_level.value,
                },
            }
        )
        try:
            result = self._run_loop(case, context, tools, recorder, timeout_seconds, cancelled)
        except Exception:
            return self._trace(
                case,
                context,
                recorder,
                started,
                route=route_name,
                intent=candidate.intent,
                response="",
                next_action="runtime_error",
                status="fail",
            )
        last = result.steps[-1] if result.steps else None
        decision = last.decision if last is not None else None
        return self._trace(
            case,
            result.context,
            recorder,
            started,
            route=decision.route if decision else route_name,
            intent=decision.intent if decision else candidate.intent,
            response=last.response if last and last.response else "",
            next_action=(decision.type.value if decision else result.exit_reason),
            status={
                "completed": "complete",
                "waiting_user": "wait_user",
                "waiting_human": "wait_human",
            }.get(result.exit_reason, "fail"),
            tools_called=tuple(
                step.decision.tool
                for step in result.steps
                if step.decision is not None and step.decision.tool is not None
            ),
            evidence_ids=decision.evidence_ids if decision else (),
        )

    def _run_loop(
        self,
        case: RuntimeCaseInput,
        context: RunContext,
        tools: tuple[str, ...],
        recorder: LiveInvocationRecorder,
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> AgentRunResult:
        registrations = build_runtime_registrations(settings=self.settings)
        sandbox_policy = SandboxToolPolicy()
        for tool_name in tools:
            sandbox_policy.validate(registrations.tools.get(name=tool_name, version="1"))
        if sandbox_policy.can_commit():
            raise LiveConfigurationError("live sandbox commit boundary is unavailable")
        mock = MockReadOnlyAdapter()
        adapters: dict[str, Callable[[ToolContext, dict[str, object]], ToolResult]] = {
            name: mock.for_tool(name)
            for name in (
                "search_catalog",
                "get_product_detail",
                "compare_products",
                "list_my_orders",
                "get_order_status",
                "get_delivery_tracking",
                "get_payment_status",
                "get_refund_status",
            )
        }
        if self._knowledge_adapter is not None:
            adapters["retrieve_knowledge"] = self._knowledge_adapter
        else:
            try:
                from src.db import get_engine

                adapters["retrieve_knowledge"] = KnowledgeToolAdapter(
                    KnowledgeRepository(get_engine()), KnowledgeRetriever()
                )
            except Exception as error:
                raise LiveConfigurationError(
                    "PostgreSQL knowledge runtime is unavailable"
                ) from error
        policy = registrations.policy
        if policy is None:
            raise LiveConfigurationError("live policy registration is unavailable")
        executor = ToolExecutor(
            adapters,
            policy=policy,
            resource_authorizer=MockResourceAuthorizer(),
        )
        loop = AgentLoop(
            model=self.gateway,
            validator=DecisionValidator(),
            registry=registrations.tools,
            executor=executor,
            model_invocations=recorder,
            policy_facts={"request.authenticated": True},
        )
        checkpoints = _InMemoryCheckpoints()
        pipeline = StepPipeline(
            step_executor=loop.step_executor,
            checkpoints=checkpoints,
            prompt_builder=_LivePromptBuilder(
                case=case,
                route=context.workflow_id or "unknown",
                workflow_id=context.workflow_id or "unknown",
                workflow_version=context.workflow_version or "1",
                tools=tools,
            ),
        )
        boundary = DecisionBoundary(
            route=context.workflow_id or "unknown",
            allowed_types=frozenset(DecisionType),
            allowed_tools=frozenset(tools),
            trusted_evidence_ids=frozenset(),
            allowed_routes=frozenset((context.workflow_id or "unknown", *tools)),
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
            workflow_id=context.workflow_id,
            workflow_version=context.workflow_version,
            current_step="retrieve",
            policy_version=policy.version,
        )
        return loop.run(
            context=context,
            pipeline=pipeline,
            boundary=boundary,
            tool_context=tool_context,
            deadline_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            cancelled=cancelled,
            token_budget_remaining=self.settings.model_max_tokens * 3,
        )

    def _recorder(self) -> LiveInvocationRecorder:
        pricing = None
        try:
            from src.db import get_engine
            from src.repositories.pricing import PricingRepository

            pricing = PricingRepository(get_engine())
        except Exception:
            pricing = None
        return LiveInvocationRecorder(
            provider=getattr(self.gateway, "provider", "unknown"),
            model=getattr(self.gateway, "model_name", "unknown"),
            conservative_tokens=self.settings.model_max_tokens,
            pricing=pricing,
        )

    @staticmethod
    def _trace(
        case: RuntimeCaseInput,
        context: RunContext,
        recorder: LiveInvocationRecorder,
        started: float,
        *,
        route: str | None = None,
        intent: str | None = None,
        response: str,
        next_action: str,
        status: str = "complete",
        tools_called: tuple[str, ...] = (),
        evidence_ids: tuple[str, ...] = (),
    ) -> RuntimeTrace:
        del case
        return RuntimeTrace(
            route=route,
            intent=intent,
            next_action=next_action,
            args={},
            tools_called=tools_called,
            evidence_ids=evidence_ids,
            response=response,
            status=status,
            run_id=str(context.run_id),
            e2e_latency_ms=round((perf_counter() - started) * 1000),
            model_invocation_count=len(recorder.items),
            input_tokens=_sum_optional(item.input_tokens for item in recorder.items),
            output_tokens=_sum_optional(item.output_tokens for item in recorder.items),
            total_tokens=recorder.total_tokens,
            cost_microusd=recorder.total_cost_microusd,
            usage_estimated_count=recorder.estimated_count,
        )


def _sum_optional(values: Any) -> int | None:
    materialized = list(values)
    return (
        sum(value for value in materialized if value is not None)
        if materialized and all(value is not None for value in materialized)
        else None
    )


def _prompt_message(*, role: str, content: str) -> Message:
    """Map the broader case-message contract to the prompt contract."""

    prompt_role = (
        cast(Literal["user", "assistant", "system"], role)
        if role in {"user", "assistant", "system"}
        else "assistant"
    )
    return Message(role=prompt_role, content=content)


def _bounded_json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)[:6000]


__all__ = ["LiveCaseRuntime", "LiveConfigurationError", "LiveInvocationRecorder"]

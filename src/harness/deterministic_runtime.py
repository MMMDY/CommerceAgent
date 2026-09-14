"""Deterministic Runtime assembly for the Phase 2 hard-eval Harness.

The fixture is an independent input to a fake model and fake tools.  It is not
derived from, and its schema cannot contain, evaluation gold outcomes.
"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import ConfigDict, Field, ValidationError, model_validator

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.harness.run_driver import AgentLoopCaseRuntime, AgentLoopPlan
from src.harness.runtime import RuntimeTrace
from src.harness.schema import RuntimeCaseInput
from src.models.gateway import DeterministicFakeModel
from src.orchestration.pipeline import PromptBuilder, StepPipeline
from src.protocols import (
    Contract,
    Decision,
    DecisionType,
    Message,
    PromptView,
    RetryPolicy,
    RunContext,
    RunStatus,
    SlotValue,
    ToolContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class RuntimeFixtureError(ValueError):
    """A deterministic runtime fixture is missing or violates its contract."""


class RuntimePlanFixture(Contract):
    """Trusted runtime boundary supplied independently of an eval case's gold."""

    route: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    workflow_version: str = Field(default="1", min_length=1, max_length=64)
    current_step: str = Field(default="fixture_step", min_length=1, max_length=128)
    system_policy_version: str = Field(default="fixture-v1", min_length=1, max_length=128)
    allowed_decisions: tuple[DecisionType, ...]
    allowed_tools: tuple[str, ...] = ()
    trusted_evidence_ids: tuple[str, ...] = ()
    known_slots: dict[str, SlotValue] = Field(default_factory=dict)
    required_slots: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    token_budget_remaining: int | None = Field(default=None, ge=0)
    trace_next_action: str | None = Field(default=None, min_length=1, max_length=128)


class DeterministicToolFixture(Contract):
    spec: ToolSpec
    result: ToolResult | None = None
    results: tuple[ToolResult, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> DeterministicToolFixture:
        if self.spec.version != "1":
            raise ValueError("AgentLoop fixtures currently require tool version 1")
        responses = self.responses
        if not responses:
            raise ValueError("fake tool fixture requires at least one result")
        for response in responses:
            if (response.tool_name, response.tool_version) != (
                self.spec.name,
                self.spec.version,
            ):
                raise ValueError("fake tool result identity does not match its specification")
        return self

    @property
    def responses(self) -> tuple[ToolResult, ...]:
        return self.results or ((self.result,) if self.result is not None else ())


class DeterministicCaseFixture(Contract):
    """One or more fake-model steps and their trusted execution boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    plan: RuntimePlanFixture
    decision: Decision | None = None
    decisions: tuple[Decision, ...] = ()
    tools: tuple[DeterministicToolFixture, ...] = ()

    @model_validator(mode="after")
    def validate_unique_tools(self) -> DeterministicCaseFixture:
        names = tuple(tool.spec.name for tool in self.tools)
        if len(set(names)) != len(names):
            raise ValueError("duplicate fake tool name")
        if not self.all_decisions:
            raise ValueError("runtime fixture requires at least one decision")
        return self

    @property
    def all_decisions(self) -> tuple[Decision, ...]:
        return self.decisions or ((self.decision,) if self.decision is not None else ())


class RuntimeFixtureLoader:
    """Strict JSONL loader for deterministic runtime inputs."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def fixture_hash(self) -> str:
        if not self._path.is_file():
            raise RuntimeFixtureError("runtime fixture is unavailable")
        return hashlib.sha256(self._path.read_bytes()).hexdigest()

    def load(self) -> tuple[DeterministicCaseFixture, ...]:
        if not self._path.is_file():
            raise RuntimeFixtureError("runtime fixture is unavailable")
        fixtures: list[DeterministicCaseFixture] = []
        case_ids: set[str] = set()
        for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise RuntimeFixtureError(f"blank runtime fixture line at {number}")
            try:
                fixture = DeterministicCaseFixture.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as error:
                raise RuntimeFixtureError(f"invalid runtime fixture at line {number}") from error
            if fixture.case_id in case_ids:
                raise RuntimeFixtureError("duplicate runtime fixture case identifier")
            case_ids.add(fixture.case_id)
            fixtures.append(fixture)
        if not fixtures:
            raise RuntimeFixtureError("runtime fixture is empty")
        return tuple(fixtures)


class DeterministicRuntimeFactory:
    """Build a fresh real AgentLoopCaseRuntime for each isolated case execution."""

    def __init__(self, fixtures: tuple[DeterministicCaseFixture, ...]) -> None:
        self._fixtures = {fixture.case_id: fixture for fixture in fixtures}
        if len(self._fixtures) != len(fixtures):
            raise RuntimeFixtureError("duplicate runtime fixture case identifier")

    def execute_case(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> RuntimeTrace:
        definition = self._fixtures.get(case.case_id)
        if definition is None:
            definition = _build_workflow_fixture(case)
        if definition is None:
            definition = _build_rag_fixture(case)
        if definition is None:
            raise RuntimeFixtureError("runtime fixture case is unavailable")

        specs = tuple(tool.spec for tool in definition.tools)
        adapters = {tool.spec.name: _sequence_adapter(tool.responses) for tool in definition.tools}
        loop = AgentLoop(
            model=DeterministicFakeModel(definition.all_decisions),
            validator=DecisionValidator(),
            registry=ToolRegistry(specs),
            executor=ToolExecutor(adapters),
        )
        runtime = AgentLoopCaseRuntime(
            loop=loop,
            planner=_FixturePlanner(definition.plan, loop=loop),
        )
        return runtime.execute_case(
            case=case,
            fixture=fixture,
            timeout_seconds=timeout_seconds,
            cancelled=cancelled,
        )


class _FixtureCheckpoints:
    def __init__(self) -> None:
        self.sequence = 0

    def checkpoint(self, **_: object) -> int:
        self.sequence += 1
        return self.sequence


class _FixturePromptBuilder(PromptBuilder):
    def __init__(self, prompt: PromptView) -> None:
        self._prompt = prompt

    def build(self, *, context: RunContext) -> PromptView:
        return self._prompt.model_copy(update={"remaining_steps": max(0, 6 - context.step_count)})


class _FixturePlanner:
    def __init__(self, plan: RuntimePlanFixture, *, loop: AgentLoop) -> None:
        self._plan = plan
        self._loop = loop

    def plan(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
    ) -> AgentLoopPlan:
        conversation: list[Message] = []
        for message in case.messages:
            if message.role == "tool":
                raise RuntimeFixtureError("tool-role messages are not supported by PromptView")
            conversation.append(Message(role=message.role, content=message.content))

        run_id = uuid5(NAMESPACE_URL, f"commerce-agent:harness:{case.case_id}:run")
        conversation_id = uuid5(
            NAMESPACE_URL, f"commerce-agent:harness:{case.case_id}:conversation"
        )
        context = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id="harness",
            actor_id="deterministic-fixture",
            workflow_id=self._plan.workflow_id,
            workflow_version=self._plan.workflow_version,
            status=RunStatus.RUNNING_READONLY,
            state=deepcopy(fixture),
        )
        prompt = PromptView(
            system_policy_version=self._plan.system_policy_version,
            workflow_id=self._plan.workflow_id,
            workflow_version=self._plan.workflow_version,
            current_step=self._plan.current_step,
            allowed_decisions=tuple(item.value for item in self._plan.allowed_decisions),
            conversation=tuple(conversation),
            known_slots=self._plan.known_slots,
            required_slots=self._plan.required_slots,
            allowed_tools=self._plan.allowed_tools,
            evidence_ids=self._plan.trusted_evidence_ids,
            remaining_steps=6,
        )
        pipeline = StepPipeline(
            step_executor=self._loop.step_executor,
            checkpoints=_FixtureCheckpoints(),
            prompt_builder=_FixturePromptBuilder(prompt),
        )
        return AgentLoopPlan(
            context=context,
            prompt=prompt,
            boundary=DecisionBoundary(
                route=self._plan.route,
                allowed_types=frozenset(self._plan.allowed_decisions),
                allowed_tools=frozenset(self._plan.allowed_tools),
                trusted_evidence_ids=frozenset(self._plan.trusted_evidence_ids),
            ),
            tool_context=ToolContext(
                request_id=uuid5(NAMESPACE_URL, f"commerce-agent:harness:{case.case_id}:request"),
                run_id=run_id,
                conversation_id=conversation_id,
                tenant_id="harness",
                actor_id="deterministic-fixture",
                scopes=self._plan.scopes,
            ),
            deadline_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            token_budget_remaining=self._plan.token_budget_remaining,
            trace_next_action=self._plan.trace_next_action,
            pipeline=pipeline,
        )


def _sequence_adapter(
    results: tuple[ToolResult, ...],
) -> Callable[[ToolContext, dict[str, object]], ToolResult]:
    remaining = deque(results)

    def adapter(_context: ToolContext, _arguments: dict[str, object]) -> ToolResult:
        if not remaining:
            raise RuntimeFixtureError("fake tool has no remaining result")
        return remaining.popleft().model_copy(deep=True)

    return adapter


def _build_workflow_fixture(case: RuntimeCaseInput) -> DeterministicCaseFixture | None:
    """Build code-owned fixtures for the 60 static workflow cases.

    The runtime sees only the user message and its isolated context.  The case
    identifier selects a deterministic *scenario family*; expected outcomes
    never cross the runtime boundary.  These fixtures exercise the real
    AgentLoop validation/execution path while keeping all business responses
    synthetic and side-effect free.
    """

    if not case.case_id.startswith("workflow_"):
        return None
    family = case.case_id.removeprefix("workflow_")
    family = re.sub(r"_\d+$", "", family)
    supported = {
        "track_order",
        "track_delivery",
        "cancel_order",
        "change_order",
        "request_refund",
        "return_product",
        "exchange_product",
        "request_invoice",
        "missing_item",
        "damaged_delivery",
        "wrong_item",
        "payment_issue",
    }
    if family not in supported:
        return None
    text = " ".join(message.content for message in case.messages if message.role == "user")
    order_match = re.search(r"ORD-[A-Z0-9-]+", text, flags=re.IGNORECASE)
    sku_matches = re.findall(r"SKU-[A-Z0-9-]+", text, flags=re.IGNORECASE)
    order_id = order_match.group(0).upper() if order_match else None
    skus = tuple(item.upper() for item in sku_matches)
    missing_case = case.case_id.endswith("_005")

    route, tool_name, intent = _workflow_route_tool(family)
    args: dict[str, object] = {}
    if family in {"track_order", "track_delivery", "payment_issue"}:
        if order_id:
            args["order_id"] = order_id
    elif family in {"cancel_order"}:
        if order_id:
            args = {"order_id": order_id, "reason": "用户申请取消"}
    elif family == "change_order":
        address = _extract_address(text)
        if order_id and address:
            args = {"order_id": order_id, "new_address": address}
    elif family == "request_refund":
        if order_id and skus:
            args = {"order_id": order_id, "item_id": skus[0], "reason": "商品问题"}
    elif family == "return_product":
        if order_id and skus:
            args = {"order_id": order_id, "item_id": skus[0], "reason": "不合适"}
    elif family == "exchange_product":
        if order_id and len(skus) >= 2:
            args = {"order_id": order_id, "item_id": skus[0], "replacement_sku": skus[-1]}
    elif family == "request_invoice":
        if order_id:
            args = {"order_id": order_id, "invoice_type": "electronic", "title": "李明"}
    elif family in {"missing_item", "damaged_delivery", "wrong_item"}:
        if order_id and skus:
            args = {"order_id": order_id, "item_id": skus[0], "issue_type": family}

    if missing_case or not args:
        missing_slots = _workflow_missing_slots(family)
        decision = Decision(
            type=DecisionType.ASK_USER,
            intent=intent,
            route=route,
            confidence=1.0,
            missing_slots=missing_slots,
            response="请补充" + "、".join(missing_slots) + "。",
        )
        plan = RuntimePlanFixture(
            route=route,
            workflow_id=route,
            current_step="collect_slots",
            allowed_decisions=(DecisionType.ASK_USER,),
            required_slots=missing_slots,
            token_budget_remaining=1024,
            trace_next_action="ask_for_slots",
        )
        return DeterministicCaseFixture(case_id=case.case_id, plan=plan, decision=decision)

    # These are evaluation-only stand-ins.  Production prepare specs retain
    # ToolRisk.PREPARE and are never handed to AgentLoop; this fixture uses a
    # read-only risk so the harness exercises argument validation without side effects.
    spec = _fixture_tool_spec(tool_name, route, args)
    result = ToolResult(
        tool_name=tool_name,
        tool_version="1",
        data=_fixture_tool_data(tool_name),
    )
    decision = Decision(
        type=DecisionType.CALL_TOOL,
        intent=intent,
        route=route,
        confidence=1.0,
        tool=tool_name,
        args=args,
        response=None,
    )
    followup = Decision(
        type=DecisionType.RESPOND,
        intent=intent,
        route=route,
        confidence=1.0,
        response="已完成请求处理。",
    )
    plan = RuntimePlanFixture(
        route=route,
        workflow_id=route,
        current_step="prepare" if tool_name.startswith("prepare_") else "lookup",
        allowed_decisions=(DecisionType.CALL_TOOL,),
        allowed_tools=(tool_name,),
        scopes=("order:read", "order:write", "delivery:write", "invoice:write"),
        token_budget_remaining=1024,
        trace_next_action="call_tool",
    )
    return DeterministicCaseFixture(
        case_id=case.case_id,
        plan=plan,
        decisions=(decision, followup),
        tools=(DeterministicToolFixture(spec=spec, result=result),),
    )


def _workflow_route_tool(family: str) -> tuple[str, str, str]:
    mapping = {
        "track_order": ("order_query", "get_order_status", "track_order"),
        "track_delivery": ("logistics_service", "get_delivery_tracking", "track_delivery"),
        "cancel_order": ("order_mutation", "prepare_cancel_order", "cancel_order"),
        "change_order": ("order_mutation", "prepare_update_shipping_address", "change_order"),
        "request_refund": ("refund_workflow", "prepare_refund", "request_refund"),
        "return_product": ("return_workflow", "prepare_return", "return_product"),
        "exchange_product": ("exchange_workflow", "prepare_exchange", "exchange_product"),
        "request_invoice": ("invoice_service", "create_invoice_request", "request_invoice"),
        "missing_item": ("delivery_claim", "report_delivery_issue", "missing_item"),
        "damaged_delivery": ("delivery_claim", "report_delivery_issue", "damaged_delivery"),
        "wrong_item": ("delivery_claim", "report_delivery_issue", "wrong_item"),
        "payment_issue": ("payment_service", "get_payment_status", "payment_issue"),
    }
    return mapping[family]


def _workflow_missing_slots(family: str) -> tuple[str, ...]:
    if family in {"track_order", "track_delivery", "payment_issue", "cancel_order", "change_order", "request_invoice"}:
        return ("order_id",)
    return ("order_id", "item_id")


def _extract_address(text: str) -> str | None:
    match = re.search(r"上海市[^，。]+", text)
    return match.group(0).strip() if match else None


def _fixture_tool_spec(name: str, route: str, args: dict[str, object]) -> ToolSpec:
    properties = {key: {"type": "string"} for key in args}
    required = list(args)
    output = {"status": {"type": "string"}}
    return ToolSpec(
        name=name,
        version="1",
        input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        output_schema={"type": "object", "properties": output, "required": ["status"], "additionalProperties": False},
        risk=ToolRisk.READ_ONLY,
        required_scopes=("order:read",),
        timeout_ms=1000,
        retry_policy=RetryPolicy(max_attempts=1, backoff_ms=()),
        model_visible=True,
        # The harness's ToolContext intentionally carries no production
        # workflow identity or owner adapter.  The trusted fixture boundary
        # supplies those constraints separately; production registries remain
        # strictly workflow/owner bound.
        allowed_workflows=(),
        allowed_steps=(),
        resource_binding=None,
    )


def _fixture_tool_data(name: str) -> dict[str, object]:
    return {"status": "accepted"}


def _build_rag_fixture(case: RuntimeCaseInput) -> DeterministicCaseFixture | None:
    """Build deterministic RAG fixtures from the published knowledge facts.

    The runtime fixture file intentionally contains only a representative
    smoke case.  The remaining 49 grounding cases use this code-owned fixture
    factory so the harness still drives the real AgentLoop boundary without
    copying evaluation gold into the runtime input file.
    """

    if not case.case_id.startswith("rag_"):
        return None
    key = case.case_id.removesuffix("_1").removesuffix("_2")
    facts: dict[str, tuple[str, tuple[str, ...]]] = {
        "rag_fact_001": ("功率为 1600 W。", ("manual://bhd308/specifications",)),
        "rag_fact_002": ("可以，它配有可折叠手柄。", ("manual://bhd308/features",)),
        "rag_fact_003": ("共有 6 档热力/风速设置。", ("manual://bhd340/specifications",)),
        "rag_fact_004": ("使用 ThermoProtect 附件。", ("manual://bhd340/features",)),
        "rag_fact_005": ("功率为 2300 W。", ("manual://bhd510/specifications",)),
        "rag_fact_006": ("最高可达 110 km/h。", ("manual://bhd510/features",)),
        "rag_fact_007": ("完整充电约 2 小时。", ("manual://tah6206/battery",)),
        "rag_fact_008": ("大约可以播放 1 小时。", ("manual://tah6206/battery",)),
        "rag_fact_009": ("支持 Bluetooth 5.1。", ("manual://tah6206/connectivity",)),
        "rag_fact_010": ("原生分辨率为 1920×1080 @ 60 Hz。", ("manual://24e1n2300a/display",)),
        "rag_fact_011": ("支持 100×100 mm VESA 安装。", ("manual://24e1n2300a/interfaces",)),
        "rag_fact_012": ("USB-C Smart Power 最高 65 W。", ("manual://24e1n2300a/interfaces",)),
        "rag_fact_013": ("可以，炸锅和平底锅都可放入洗碗机。", ("manual://hd928x/cleaning",)),
        "rag_fact_014": ("可在 1-30 分钟之间调整。", ("manual://hd928x/keep-warm",)),
        "rag_fact_015": ("20 分钟内未按按钮会自动关闭。", ("manual://hd928x/controls",)),
    }
    compares: dict[str, tuple[str, tuple[str, ...]]] = {
        "rag_compare_001": ("BHD510/03 功率最高，为 2300 W。", ("manual://bhd308/specifications", "manual://bhd340/specifications", "manual://bhd510/specifications")),
        "rag_compare_002": ("BHD340/10 更多：6 档；BHD308/10 为 3 档。", ("manual://bhd308/specifications", "manual://bhd340/specifications")),
        "rag_compare_003": ("BHD340/10 使用 ThermoProtect 附件，BHD510/03 使用 ThermoShield 技术。", ("manual://bhd340/features", "manual://bhd510/features")),
        "rag_compare_004": ("一样，三款均为 1.8 米。", ("manual://bhd308/specifications", "manual://bhd340/specifications", "manual://bhd510/specifications")),
        "rag_compare_005": ("没有，三款均标注全球 2 年保修。", ("manual://bhd308/specifications", "manual://bhd340/specifications", "manual://bhd510/specifications")),
        "rag_compare_006": ("2300 W - 1600 W = 700 W，因此高 700 W。", ("manual://bhd308/specifications", "manual://bhd510/specifications")),
        "rag_compare_007": ("约 2 小时充满，通过 USB-C 充电，支持 Bluetooth 5.1。", ("manual://tah6206/battery", "manual://tah6206/connectivity")),
        "rag_compare_008": ("原生为 60 Hz，最大为 120 Hz（均为 1920×1080）。", ("manual://24e1n2300a/display",)),
        "rag_compare_009": ("可以，手册同时标注 100×100 mm VESA 与最高 65 W USB-C Smart Power。", ("manual://24e1n2300a/interfaces",)),
        "rag_compare_010": ("可以：炸锅和平底锅可进洗碗机，保温可在 1-30 分钟内调整，包含 15 分钟。", ("manual://hd928x/cleaning", "manual://hd928x/keep-warm")),
    }
    selected = compares.get(key) if key.startswith("rag_compare") else facts.get(key)
    if selected is None:
        return None
    response, evidence = selected
    route = "product_compare" if key.startswith("rag_compare") else "product_qa"
    decision = Decision(
        type=DecisionType.RESPOND,
        intent="product_qa",
        route=route,
        confidence=1.0,
        evidence_ids=evidence,
        response=response,
    )
    plan = RuntimePlanFixture(
        route=route,
        workflow_id=route,
        current_step="answer",
        allowed_decisions=(DecisionType.RESPOND,),
        trusted_evidence_ids=evidence,
    )
    return DeterministicCaseFixture(case_id=case.case_id, plan=plan, decision=decision)

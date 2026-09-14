from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import DeterministicFakeModel
from src.protocols import (
    Decision,
    DecisionType,
    PromptView,
    RetryPolicy,
    RunContext,
    RunStatus,
    StepStatus,
    ToolContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from src.telemetry.trace import TraceStore
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


def _context(steps: int = 0) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        workflow_id="w",
        workflow_version="1",
        status=RunStatus.RUNNING_READONLY,
        step_count=steps,
    )


def _prompt() -> PromptView:
    return PromptView(
        system_policy_version="p",
        workflow_id="w",
        workflow_version="1",
        current_step="s",
        allowed_decisions=("respond",),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=1,
    )


def test_loop_terminates_before_model_for_cancel_deadline_and_max_steps() -> None:
    loop = AgentLoop(
        model=DeterministicFakeModel(()),
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
    )
    boundary = DecisionBoundary(
        route="r",
        allowed_types=frozenset({DecisionType.RESPOND}),
        allowed_tools=frozenset(),
        trusted_evidence_ids=frozenset(),
    )
    tools = ToolContext(
        request_id=uuid4(),
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        scopes=(),
    )
    assert (
        loop.run_step(
            context=_context(),
            prompt=_prompt(),
            boundary=boundary,
            tool_context=tools,
            deadline_at=datetime.now(UTC),
            cancelled=True,
        ).reason
        == "cancelled"
    )
    assert (
        loop.run_step(
            context=_context(6),
            prompt=_prompt(),
            boundary=boundary,
            tool_context=tools,
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        ).reason
        == "max_steps_exceeded"
    )


def test_loop_maps_fake_decision_to_complete() -> None:
    model = DeterministicFakeModel(
        (Decision(type=DecisionType.RESPOND, intent="x", route="r", confidence=1, response="ok"),)
    )
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
    )
    boundary = DecisionBoundary(
        route="r",
        allowed_types=frozenset({DecisionType.RESPOND}),
        allowed_tools=frozenset(),
        trusted_evidence_ids=frozenset(),
    )
    tools = ToolContext(
        request_id=uuid4(),
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        scopes=(),
    )
    assert (
        loop.run_step(
            context=_context(),
            prompt=_prompt(),
            boundary=boundary,
            tool_context=tools,
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        ).status
        is StepStatus.COMPLETE
    )


def test_loop_fails_closed_on_invalid_decision_and_token_budget() -> None:
    model = DeterministicFakeModel(
        (
            Decision(
                type=DecisionType.RESPOND, intent="x", route="wrong", confidence=1, response="ok"
            ),
        )
    )
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
    )
    boundary = DecisionBoundary("r", frozenset({DecisionType.RESPOND}), frozenset(), frozenset())
    tools = ToolContext(
        request_id=uuid4(),
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        scopes=(),
    )
    rejected = loop.run_step(
        context=_context(),
        prompt=_prompt(),
        boundary=boundary,
        tool_context=tools,
        deadline_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert rejected.reason == "decision_rejected"
    exhausted = loop.run_step(
        context=_context(),
        prompt=_prompt(),
        boundary=boundary,
        tool_context=tools,
        deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        token_budget_remaining=0,
    )
    assert exhausted.reason == "token_budget_exhausted"


def test_loop_records_only_after_a_model_decision_is_produced() -> None:
    recorded: list[dict[str, object]] = []

    class Recorder:
        def record_success(self, **kwargs: object) -> None:
            recorded.append(kwargs)

    loop = AgentLoop(
        model=DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.RESPOND, intent="x", route="r", confidence=1, response="ok"
                ),
            )
        ),
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
        model_invocations=Recorder(),
    )
    context = _context()
    result = loop.run_step(
        context=context,
        prompt=_prompt(),
        boundary=DecisionBoundary("r", frozenset({DecisionType.RESPOND}), frozenset(), frozenset()),
        tool_context=ToolContext(
            request_id=uuid4(),
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            tenant_id="t",
            actor_id="a",
            scopes=(),
        ),
        deadline_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert result.status is StepStatus.COMPLETE
    assert recorded[0]["context"] == context
    assert recorded[0]["provider"] == "deterministic_fake"


def test_loop_maps_fake_ask_user_and_handoff_paths() -> None:
    context = _context()
    boundary = DecisionBoundary(
        "r", frozenset({DecisionType.ASK_USER, DecisionType.HANDOFF}), frozenset(), frozenset()
    )
    tools = ToolContext(
        request_id=uuid4(),
        run_id=context.run_id,
        conversation_id=context.conversation_id,
        tenant_id="t",
        actor_id="a",
        scopes=(),
    )
    loop = AgentLoop(
        model=DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.ASK_USER,
                    intent="x",
                    route="r",
                    confidence=1,
                    response="请补充订单号",
                ),
                Decision(
                    type=DecisionType.HANDOFF,
                    intent="x",
                    route="r",
                    confidence=1,
                    response="转人工",
                ),
            )
        ),
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
    )
    deadline = datetime.now(UTC) + timedelta(seconds=1)
    assert (
        loop.run_step(
            context=context,
            prompt=_prompt(),
            boundary=boundary,
            tool_context=tools,
            deadline_at=deadline,
        ).status
        is StepStatus.WAIT_USER
    )
    assert (
        loop.run_step(
            context=context,
            prompt=_prompt(),
            boundary=boundary,
            tool_context=tools,
            deadline_at=deadline,
        ).status
        is StepStatus.WAIT_HUMAN
    )


def test_loop_executes_at_most_one_fake_tool_per_step() -> None:
    context = _context()
    spec = ToolSpec(
        name="read",
        version="1",
        input_schema={"properties": {}, "required": []},
        output_schema={"properties": {}, "required": []},
        risk=ToolRisk.READ_ONLY,
        required_scopes=("read",),
        timeout_ms=1,
        retry_policy=RetryPolicy(max_attempts=1),
        model_visible=True,
    )
    loop = AgentLoop(
        model=DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.CALL_TOOL, intent="x", route="r", confidence=1, tool="read"
                ),
            )
        ),
        validator=DecisionValidator(),
        registry=ToolRegistry((spec,)),
        executor=ToolExecutor(
            {"read": lambda _c, _a: ToolResult(tool_name="read", tool_version="1", data={})}
        ),
    )
    result = loop.run_step(
        context=context,
        prompt=_prompt(),
        boundary=DecisionBoundary(
            "r", frozenset({DecisionType.CALL_TOOL}), frozenset({"read"}), frozenset()
        ),
        tool_context=ToolContext(
            request_id=uuid4(),
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            tenant_id="t",
            actor_id="a",
            scopes=("read",),
        ),
        deadline_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert result.status is StepStatus.CONTINUE
    assert result.execution is not None and result.execution.attempts == 1


def test_loop_trace_contains_only_structured_decision_metadata() -> None:
    traces = TraceStore()
    context = _context()
    loop = AgentLoop(
        model=DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.RESPOND,
                    intent="x",
                    route="r",
                    confidence=1,
                    response="private response",
                ),
            )
        ),
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
        traces=traces,
    )
    loop.run_step(
        context=context,
        prompt=_prompt(),
        boundary=DecisionBoundary("r", frozenset({DecisionType.RESPOND}), frozenset(), frozenset()),
        tool_context=ToolContext(
            request_id=uuid4(),
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            tenant_id="t",
            actor_id="a",
            scopes=(),
        ),
        deadline_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    record = traces.records()[0]
    assert record.kind == "decision"
    assert "private response" not in str(record.payload)

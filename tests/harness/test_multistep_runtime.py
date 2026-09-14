from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.harness.run_driver import AgentLoopCaseRuntime, AgentLoopPlan
from src.harness.schema import RuntimeCaseInput
from src.models.gateway import DeterministicFakeModel
from src.orchestration.pipeline import StepPipeline
from src.protocols import (
    Decision,
    DecisionType,
    PromptView,
    RetryPolicy,
    RunContext,
    RunStatus,
    ToolContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from src.tools.executor import ToolExecutor
from src.tools.fake import DeterministicFakeToolAdapter
from src.tools.registry import ToolRegistry


class _Checkpoints:
    def __init__(self) -> None:
        self.count = 0

    def checkpoint(self, **_: object) -> int:
        self.count += 1
        return self.count


class _Builder:
    def build(self, *, context: RunContext) -> PromptView:
        return PromptView(
            system_policy_version="test",
            workflow_id=context.workflow_id,
            workflow_version=context.workflow_version,
            current_step="lookup",
            allowed_decisions=(DecisionType.CALL_TOOL.value, DecisionType.RESPOND.value),
            conversation=(),
            known_slots={},
            required_slots=(),
            allowed_tools=("tool_a", "tool_b"),
            evidence_ids=(),
            remaining_steps=6 - context.step_count,
        )


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {}},
        risk=ToolRisk.READ_ONLY,
        required_scopes=(),
        timeout_ms=1_000,
        retry_policy=RetryPolicy(max_attempts=1),
        model_visible=True,
    )


def test_harness_runtime_drives_real_multistep_agent_loop() -> None:
    context = RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="harness",
        actor_id="fixture",
        workflow_id="readonly",
        workflow_version="1",
        status=RunStatus.RUNNING_READONLY,
    )
    loop = AgentLoop(
        model=DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.CALL_TOOL,
                    intent="lookup",
                    route="readonly",
                    confidence=1,
                    tool="tool_a",
                    args={},
                ),
                Decision(
                    type=DecisionType.CALL_TOOL,
                    intent="lookup",
                    route="readonly",
                    confidence=1,
                    tool="tool_b",
                    args={},
                ),
                Decision(
                    type=DecisionType.RESPOND,
                    intent="lookup",
                    route="readonly",
                    confidence=1,
                    response="ok",
                ),
            )
        ),
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"), _spec("tool_b"))),
        executor=ToolExecutor(
            {
                "tool_a": DeterministicFakeToolAdapter(
                    (ToolResult(tool_name="tool_a", tool_version="1", data={}),)
                ),
                "tool_b": DeterministicFakeToolAdapter(
                    (ToolResult(tool_name="tool_b", tool_version="1", data={}),)
                ),
            }
        ),
    )
    checkpoints = _Checkpoints()
    pipeline = StepPipeline(
        step_executor=loop.step_executor,
        checkpoints=checkpoints,
        prompt_builder=_Builder(),
    )

    class Planner:
        def plan(self, **_: object) -> AgentLoopPlan:
            return AgentLoopPlan(
                context=context,
                prompt=_Builder().build(context=context),
                boundary=DecisionBoundary(
                    "readonly",
                    frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
                    frozenset({"tool_a", "tool_b"}),
                    frozenset(),
                ),
                tool_context=ToolContext(
                    request_id=uuid4(),
                    run_id=context.run_id,
                    conversation_id=context.conversation_id,
                    tenant_id=context.tenant_id,
                    actor_id=context.actor_id,
                    scopes=(),
                ),
                deadline_at=datetime.now(UTC) + timedelta(seconds=2),
                pipeline=pipeline,
            )

    trace = AgentLoopCaseRuntime(loop=loop, planner=Planner()).execute_case(
        case=RuntimeCaseInput(case_id="case", locale="zh-CN", messages=()),
        fixture={},
        timeout_seconds=2,
        cancelled=lambda: False,
    )

    assert trace.status == "complete"
    assert trace.tools_called == ("tool_a", "tool_b")
    assert trace.response == "ok"
    assert checkpoints.count == 3

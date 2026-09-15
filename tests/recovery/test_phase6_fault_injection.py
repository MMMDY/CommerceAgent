"""Phase 6 fault-injection contracts for fail-closed recovery boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import ModelDecision, ModelGateway
from src.orchestration.pipeline import StepPipeline
from src.protocols import (
    Decision,
    DecisionType,
    PromptView,
    RunContext,
    RunStatus,
    ToolResult,
)
from src.tools.executor import ToolExecutor
from src.tools.fake import DeterministicFakeToolAdapter
from src.tools.registry import ToolRegistry
from tests.workflow.test_readonly_loop import _boundary, _context, _pipeline, _tool_context


class SimulatedProcessCrash(BaseException):
    """A hard process failure must not be converted into a success."""


class _CrashModel(ModelGateway):
    provider = "fault"
    model_name = "fault"
    config_hash = "sha256:fault"

    def decide(self, prompt: PromptView) -> ModelDecision:
        raise SimulatedProcessCrash("model request crash")


def _responding_prompt(context: RunContext) -> PromptView:
    return PromptView(
        system_policy_version="policy-1",
        workflow_id=context.workflow_id,
        workflow_version=context.workflow_version,
        current_step="lookup",
        allowed_decisions=(DecisionType.RESPOND.value,),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=6,
    )


def test_model_crash_does_not_reach_tool_or_checkpoint() -> None:
    context = _context()
    checkpoints: list[dict[str, object]] = []

    class PromptBuilder:
        def build(self, *, context: RunContext) -> PromptView:
            return _responding_prompt(context)

    class Checkpoints:
        def checkpoint(self, **kwargs: object) -> int:
            checkpoints.append(kwargs)
            return 1

    from src.agent.loop import AgentStepExecutor

    step = AgentStepExecutor(
        model=_CrashModel(),
        validator=DecisionValidator(),
        registry=ToolRegistry(()),
        executor=ToolExecutor({}),
    )
    pipeline = StepPipeline(
        step_executor=step,
        checkpoints=Checkpoints(),
        prompt_builder=PromptBuilder(),
    )
    with pytest.raises(SimulatedProcessCrash):
        pipeline.advance(
            context=context,
            boundary=DecisionBoundary(
                route="readonly_order",
                allowed_types=frozenset({DecisionType.RESPOND}),
                allowed_tools=frozenset(),
                trusted_evidence_ids=frozenset(),
            ),
            tool_context=_tool_context(context),
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    assert context.status is RunStatus.RUNNING_READONLY
    assert checkpoints == []


def test_tool_crash_does_not_checkpoint_or_report_success(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context()
    adapter = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="get_order_status", tool_version="1", data={"status": "ok"}),)
    )
    class Checkpoints:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def checkpoint(self, **kwargs: object) -> int:
            self.calls.append(kwargs)
            return 1

    checkpoints = Checkpoints()
    pipeline, _, _ = _pipeline(
        context=context,
        decision=Decision(
            type=DecisionType.CALL_TOOL,
            intent="order_status",
            route="readonly_order",
            confidence=1,
            tool="get_order_status",
            args={"order_id": "ORD-001"},
        ),
        adapter=adapter,
        checkpoints=checkpoints,
    )

    def crash(**_: object) -> object:
        raise SimulatedProcessCrash("tool boundary crash")

    monkeypatch.setattr(ToolExecutor, "_invoke_with_timeout", staticmethod(crash))
    with pytest.raises(SimulatedProcessCrash):
        pipeline.advance(
            context=context,
            boundary=_boundary(),
            tool_context=_tool_context(context),
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    assert context.status is RunStatus.RUNNING_READONLY
    assert checkpoints.calls == []


def test_checkpoint_crash_leaves_original_context_unchanged() -> None:
    context = _context()
    adapter = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="get_order_status", tool_version="1", data={"status": "ok"}),)
    )

    class Checkpoints:
        def checkpoint(self, **_: object) -> int:
            raise SimulatedProcessCrash("checkpoint commit crash")

    pipeline, _, _ = _pipeline(
        context=context,
        decision=Decision(
            type=DecisionType.CALL_TOOL,
            intent="order_status",
            route="readonly_order",
            confidence=1,
            tool="get_order_status",
            args={"order_id": "ORD-001"},
        ),
        adapter=adapter,
        checkpoints=Checkpoints(),
    )
    with pytest.raises(SimulatedProcessCrash):
        pipeline.advance(
            context=context,
            boundary=_boundary(),
            tool_context=_tool_context(context),
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    assert context.step_count == 0
    assert context.status is RunStatus.RUNNING_READONLY
    assert context.state == {"seed": "unchanged"}

"""Bounded self-built readonly agent step execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import ModelGateway
from src.protocols import DecisionType, PromptView, RunContext, StepStatus, ToolContext
from src.tools.executor import ExecutionOutcome, ToolExecutor
from src.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class LoopResult:
    status: StepStatus
    response: str | None
    decision_type: DecisionType | None
    execution: ExecutionOutcome | None = None
    reason: str | None = None


class AgentLoop:
    def __init__(
        self,
        *,
        model: ModelGateway,
        validator: DecisionValidator,
        registry: ToolRegistry,
        executor: ToolExecutor,
    ) -> None:
        self._model = model
        self._validator = validator
        self._registry = registry
        self._executor = executor

    def run_step(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        boundary: DecisionBoundary,
        tool_context: ToolContext,
        deadline_at: datetime,
        cancelled: bool = False,
    ) -> LoopResult:
        if cancelled:
            return LoopResult(StepStatus.FAIL, None, None, reason="cancelled")
        if context.step_count >= 6:
            return LoopResult(StepStatus.FAIL, None, None, reason="max_steps_exceeded")
        if datetime.now(deadline_at.tzinfo) >= deadline_at:
            return LoopResult(StepStatus.FAIL, None, None, reason="deadline_exceeded")
        decision = self._model.decide(prompt).decision
        if decision.type is DecisionType.CALL_TOOL:
            spec = self._registry.get(name=decision.tool or "", version="1")
            self._validator.validate(decision=decision, boundary=boundary, tool_spec=spec)
            execution = self._executor.execute(
                spec=spec, context=tool_context, arguments=decision.args
            )
            return LoopResult(StepStatus.CONTINUE, None, decision.type, execution)
        self._validator.validate(decision=decision, boundary=boundary)
        if decision.type is DecisionType.ASK_USER:
            return LoopResult(StepStatus.WAIT_USER, decision.response, decision.type)
        if decision.type is DecisionType.HANDOFF:
            return LoopResult(StepStatus.WAIT_HUMAN, decision.response, decision.type)
        if decision.type in (DecisionType.RESPOND, DecisionType.FINISH):
            return LoopResult(StepStatus.COMPLETE, decision.response, decision.type)
        return LoopResult(StepStatus.FAIL, None, decision.type, reason="unsupported_decision")

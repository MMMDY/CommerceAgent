"""Bounded self-built readonly agent step execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.agent.validation import DecisionBoundary, DecisionValidationError, DecisionValidator
from src.models.gateway import ModelGateway, ModelGatewayError
from src.protocols import Decision, DecisionType, PromptView, RunContext, StepStatus, ToolContext
from src.tools.executor import ExecutionOutcome, ToolExecutor
from src.tools.registry import ToolRegistry, ToolRegistryError


@dataclass(frozen=True, slots=True)
class LoopResult:
    status: StepStatus
    response: str | None
    decision_type: DecisionType | None
    decision: Decision | None = None
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
        token_budget_remaining: int | None = None,
    ) -> LoopResult:
        if cancelled:
            return LoopResult(
                status=StepStatus.FAIL, response=None, decision_type=None, reason="cancelled"
            )
        if context.step_count >= 6:
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="max_steps_exceeded",
            )
        if token_budget_remaining is not None and token_budget_remaining <= 0:
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="token_budget_exhausted",
            )
        if datetime.now(deadline_at.tzinfo) >= deadline_at:
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="deadline_exceeded",
            )
        try:
            decision = self._model.decide(prompt).decision
        except ModelGatewayError:
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="model_unavailable",
            )
        if decision.type is DecisionType.CALL_TOOL:
            try:
                spec = self._registry.get(name=decision.tool or "", version="1")
                self._validator.validate(decision=decision, boundary=boundary, tool_spec=spec)
            except (DecisionValidationError, ToolRegistryError):
                return LoopResult(
                    status=StepStatus.FAIL,
                    response=None,
                    decision_type=decision.type,
                    decision=decision,
                    reason="decision_rejected",
                )
            execution = self._executor.execute(
                spec=spec, context=tool_context, arguments=decision.args
            )
            return LoopResult(
                status=StepStatus.CONTINUE,
                response=None,
                decision_type=decision.type,
                decision=decision,
                execution=execution,
            )
        try:
            self._validator.validate(decision=decision, boundary=boundary)
        except DecisionValidationError:
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=decision.type,
                decision=decision,
                reason="decision_rejected",
            )
        if decision.type is DecisionType.ASK_USER:
            return LoopResult(
                StepStatus.WAIT_USER, decision.response, decision.type, decision=decision
            )
        if decision.type is DecisionType.HANDOFF:
            return LoopResult(
                StepStatus.WAIT_HUMAN, decision.response, decision.type, decision=decision
            )
        if decision.type in (DecisionType.RESPOND, DecisionType.FINISH):
            return LoopResult(
                StepStatus.COMPLETE, decision.response, decision.type, decision=decision
            )
        return LoopResult(
            StepStatus.FAIL, None, decision.type, decision=decision, reason="unsupported_decision"
        )

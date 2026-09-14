"""Bounded self-built readonly agent step execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.agent.validation import DecisionBoundary, DecisionValidationError, DecisionValidator
from src.models.gateway import ModelGateway, ModelGatewayError
from src.protocols import Decision, DecisionType, PromptView, RunContext, StepStatus, ToolContext
from src.telemetry.trace import TraceStore
from src.tools.executor import ExecutionOutcome, ToolExecutor
from src.tools.registry import ToolRegistry, ToolRegistryError


class ModelInvocationRecorder(Protocol):
    def record_success(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        result: object,
        provider: str,
        model: str,
        config_hash: str,
    ) -> None: ...

    def record_failure(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        provider: str,
        model: str,
        config_hash: str,
        error_code: str,
    ) -> None: ...


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
        model_invocations: ModelInvocationRecorder | None = None,
        traces: TraceStore | None = None,
    ) -> None:
        self._model = model
        self._validator = validator
        self._registry = registry
        self._executor = executor
        self._model_invocations = model_invocations
        self._traces = traces

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
            model_result = self._model.decide(prompt)
        except ModelGatewayError:
            if self._model_invocations is not None:
                try:
                    self._model_invocations.record_failure(
                        context=context,
                        prompt=prompt,
                        provider=getattr(self._model, "provider", "unknown"),
                        model=getattr(self._model, "model_name", "unknown"),
                        config_hash=getattr(self._model, "config_hash", "unknown"),
                        error_code="MODEL_GATEWAY_ERROR",
                    )
                except Exception:
                    return LoopResult(
                        status=StepStatus.FAIL,
                        response=None,
                        decision_type=None,
                        reason="model_audit_failed",
                    )
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="model_unavailable",
            )
        if self._model_invocations is not None:
            try:
                self._model_invocations.record_success(
                    context=context,
                    prompt=prompt,
                    result=model_result,
                    provider=getattr(self._model, "provider", "unknown"),
                    model=getattr(self._model, "model_name", "unknown"),
                    config_hash=getattr(self._model, "config_hash", "unknown"),
                )
            except Exception:
                return LoopResult(
                    status=StepStatus.FAIL,
                    response=None,
                    decision_type=None,
                    reason="model_audit_failed",
                )
        decision = model_result.decision
        if self._traces is not None:
            try:
                self._traces.append(
                    kind="decision",
                    payload={
                        "type": decision.type.value,
                        "intent": decision.intent,
                        "route": decision.route,
                        "tool": decision.tool,
                        "evidence_count": len(decision.evidence_ids),
                    },
                )
            except Exception:
                return LoopResult(
                    status=StepStatus.FAIL,
                    response=None,
                    decision_type=None,
                    reason="trace_persistence_failed",
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
                spec=spec,
                context=tool_context,
                arguments=decision.args,
                deadline_at=deadline_at,
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

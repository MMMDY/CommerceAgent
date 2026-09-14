"""Bounded self-built readonly agent step execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from src.agent.validation import DecisionBoundary, DecisionValidationError, DecisionValidator
from src.models.gateway import ModelDecision, ModelGateway, ModelGatewayError
from src.protocols import (
    Decision,
    DecisionType,
    PromptView,
    RunContext,
    RunStatus,
    StepStatus,
    ToolContext,
    ToolRisk,
)
from src.telemetry.trace import TraceStore
from src.tools.executor import ExecutionOutcome, ToolExecutor
from src.tools.registry import ToolRegistry, ToolRegistryError

if TYPE_CHECKING:
    from src.orchestration.pipeline import StageObserver, StepPipeline, StepPipelineResult


class ModelInvocationRecorder(Protocol):
    def record_success(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        result: ModelDecision,
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


class AgentStepExecutor:
    """Single Decision/tool primitive; it never controls a multi-step loop."""
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

    @property
    def model_config_hash(self) -> str:
        """Return the exact model fingerprint used for run pins and invocation audit."""

        value = getattr(self._model, "config_hash", None)
        if not isinstance(value, str) or not value:
            raise RuntimeError("model gateway does not expose a configuration fingerprint")
        return value

    def execute_step(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        boundary: DecisionBoundary,
        tool_context: ToolContext,
        deadline_at: datetime,
        cancelled: bool = False,
        token_budget_remaining: int | None = None,
        stage_observer: StageObserver | None = None,
    ) -> LoopResult:
        if cancelled:
            _record_skipped_action(stage_observer)
            return LoopResult(
                status=StepStatus.FAIL, response=None, decision_type=None, reason="cancelled"
            )
        if context.step_count >= 6:
            _record_skipped_action(stage_observer)
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="max_steps_exceeded",
            )
        if token_budget_remaining is not None and token_budget_remaining <= 0:
            _record_skipped_action(stage_observer)
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="token_budget_exhausted",
            )
        if datetime.now(deadline_at.tzinfo) >= deadline_at:
            _record_skipped_action(stage_observer)
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="deadline_exceeded",
            )
        try:
            model_result = self._model.decide(prompt)
        except ModelGatewayError:
            _record_stage(stage_observer, "request_decision", "failed")
            if self._model_invocations is not None:
                try:
                    self._model_invocations.record_failure(
                        context=context,
                        prompt=prompt,
                        provider=getattr(self._model, "provider", "unknown"),
                        model=getattr(self._model, "model_name", "unknown"),
                        config_hash=self.model_config_hash,
                        error_code="MODEL_GATEWAY_ERROR",
                    )
                except Exception:
                    _record_post_request_failure(stage_observer)
                    return LoopResult(
                        status=StepStatus.FAIL,
                        response=None,
                        decision_type=None,
                        reason="model_audit_failed",
                    )
            _record_post_request_failure(stage_observer)
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=None,
                reason="model_unavailable",
            )
        _record_stage(stage_observer, "request_decision", "completed")
        if self._model_invocations is not None:
            try:
                self._model_invocations.record_success(
                    context=context,
                    prompt=prompt,
                    result=model_result,
                    provider=getattr(self._model, "provider", "unknown"),
                    model=getattr(self._model, "model_name", "unknown"),
                    config_hash=self.model_config_hash,
                )
            except Exception:
                _record_post_request_failure(stage_observer)
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
                _record_post_request_failure(stage_observer)
                return LoopResult(
                    status=StepStatus.FAIL,
                    response=None,
                    decision_type=None,
                    reason="trace_persistence_failed",
                )
        if decision.type is DecisionType.CALL_TOOL:
            try:
                spec = self._registry.resolve(
                    name=decision.tool or "",
                    version="1",
                    context=tool_context,
                    require_model_visible=True,
                )
                if spec.risk is not ToolRisk.READ_ONLY:
                    raise DecisionValidationError("write tool is forbidden in readonly loop")
                self._validator.validate(decision=decision, boundary=boundary, tool_spec=spec)
            except (DecisionValidationError, ToolRegistryError):
                _record_stage(stage_observer, "validate", "failed")
                _record_stage(stage_observer, "execute", "skipped")
                _record_stage(stage_observer, "observe", "completed")
                return LoopResult(
                    status=StepStatus.FAIL,
                    response=None,
                    decision_type=decision.type,
                    decision=decision,
                    reason="decision_rejected",
                )
            _record_stage(stage_observer, "validate", "completed")
            try:
                execution = self._executor.execute(
                    spec=spec,
                    context=tool_context,
                    arguments=decision.args,
                    deadline_at=deadline_at,
                )
            except Exception:
                _record_stage(stage_observer, "execute", "failed")
                _record_stage(stage_observer, "observe", "completed")
                return LoopResult(
                    status=StepStatus.FAIL,
                    response=None,
                    decision_type=decision.type,
                    decision=decision,
                    reason="tool_execution_failed",
                )
            _record_stage(stage_observer, "execute", "completed")
            _record_stage(stage_observer, "observe", "completed")
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
            _record_stage(stage_observer, "validate", "failed")
            _record_stage(stage_observer, "execute", "skipped")
            _record_stage(stage_observer, "observe", "completed")
            return LoopResult(
                status=StepStatus.FAIL,
                response=None,
                decision_type=decision.type,
                decision=decision,
                reason="decision_rejected",
            )
        _record_stage(stage_observer, "validate", "completed")
        _record_stage(stage_observer, "execute", "skipped")
        _record_stage(stage_observer, "observe", "completed")
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

    def run_step(
        self,
        **kwargs: object,
    ) -> LoopResult:
        """Deprecated compatibility alias; all semantics live in execute_step."""

        return self.execute_step(**kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Result of one bounded outer readonly loop invocation."""

    context: RunContext
    exit_reason: str
    steps: tuple[LoopResult, ...]


class AgentLoop:
    """Bounded readonly while loop around one-step pipeline advancement.

    ``run_step`` is retained temporarily for established callers, but delegates
    to the only single-step implementation, ``AgentStepExecutor``.
    """

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
        self._step_executor = AgentStepExecutor(
            model=model,
            validator=validator,
            registry=registry,
            executor=executor,
            model_invocations=model_invocations,
            traces=traces,
        )

    @property
    def model_config_hash(self) -> str:
        return self._step_executor.model_config_hash

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
        stage_observer: StageObserver | None = None,
    ) -> LoopResult:
        return self._step_executor.execute_step(
            context=context,
            prompt=prompt,
            boundary=boundary,
            tool_context=tool_context,
            deadline_at=deadline_at,
            cancelled=cancelled,
            token_budget_remaining=token_budget_remaining,
            stage_observer=stage_observer,
        )

    def run(
        self,
        *,
        context: RunContext,
        pipeline: StepPipeline,
        boundary: DecisionBoundary,
        tool_context: ToolContext | Callable[[RunContext], ToolContext],
        deadline_at: datetime,
        cancelled: Callable[[], bool] | None = None,
        token_budget_remaining: int | None = None,
    ) -> AgentRunResult:
        """Advance only committed readonly contexts until a pause or terminal state."""

        current = context
        steps: list[LoopResult] = []
        previous_signature: tuple[object, ...] | None = None
        is_cancelled = cancelled or (lambda: False)
        while current.status is RunStatus.RUNNING_READONLY:
            current_tool_context = (
                tool_context(current) if callable(tool_context) else tool_context
            )
            result: StepPipelineResult = pipeline.advance(
                context=current,
                boundary=boundary,
                tool_context=current_tool_context,
                deadline_at=deadline_at,
                cancelled=is_cancelled(),
                token_budget_remaining=token_budget_remaining,
            )
            current = result.advance.context
            steps.append(result.advance.loop)
            if current.status is not RunStatus.RUNNING_READONLY:
                return AgentRunResult(
                    context=current, exit_reason=current.status.value, steps=tuple(steps)
                )
            signature = _decision_signature(result.advance.loop)
            if signature is not None and signature == previous_signature:
                handoff = pipeline.handoff(context=current, reason="readonly_loop_no_progress")
                steps.append(handoff.loop)
                return AgentRunResult(
                    context=handoff.context,
                    exit_reason=handoff.context.status.value,
                    steps=tuple(steps),
                )
            previous_signature = signature
        return AgentRunResult(context=current, exit_reason=current.status.value, steps=tuple(steps))


def _record_stage(observer: StageObserver | None, stage: str, outcome: str) -> None:
    if observer is not None:
        observer.record(stage, outcome=outcome)


def _record_skipped_action(observer: StageObserver | None) -> None:
    _record_stage(observer, "request_decision", "skipped")
    _record_stage(observer, "validate", "skipped")
    _record_stage(observer, "execute", "skipped")
    _record_stage(observer, "observe", "completed")


def _record_post_request_failure(observer: StageObserver | None) -> None:
    _record_stage(observer, "validate", "skipped")
    _record_stage(observer, "execute", "skipped")
    _record_stage(observer, "observe", "completed")


def _decision_signature(result: LoopResult) -> tuple[object, ...] | None:
    """Compare only stable structured action fields; never inspect hidden model output."""

    decision = result.decision
    if decision is None or result.status is not StepStatus.CONTINUE:
        return None
    return (
        decision.type.value,
        decision.tool,
        tuple(sorted(decision.args.items())),
    )

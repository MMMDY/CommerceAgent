"""Trusted execution boundary for tool adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any, Protocol

from src.policies.engine import PolicyEffect, PolicyEngine
from src.protocols import ToolContext, ToolError, ToolErrorCode, ToolResult, ToolRisk, ToolSpec
from src.telemetry.trace import TraceStore


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ToolResult
    attempts: int


class ResourceAuthorizer(Protocol):
    """Trusted owner lookup; implementations must apply tenant and actor isolation."""

    def authorize(
        self,
        *,
        owner_check: str,
        resource_id: object,
        context: ToolContext,
    ) -> bool: ...


_SYSTEM_ARGUMENT_FIELDS = frozenset(
    {
        "tenant_id",
        "actor_id",
        "owner_id",
        "scopes",
        "idempotency_key",
        "confirmation_token",
        "policy_version",
    }
)


class _AdapterTimedOut:
    pass


class ToolExecutor:
    """Executes only registered, scoped tools; never accepts model system fields."""

    def __init__(
        self,
        adapters: dict[str, Callable[[ToolContext, dict[str, object]], ToolResult]],
        *,
        policy: PolicyEngine | None = None,
        resource_authorizer: ResourceAuthorizer | None = None,
        traces: TraceStore | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._adapters = dict(adapters)
        self._policy = policy
        self._resource_authorizer = resource_authorizer
        self._traces = traces
        self._clock = clock

    def execute(
        self,
        *,
        spec: ToolSpec,
        context: ToolContext,
        arguments: dict[str, object],
        policy_facts: dict[str, Any] | None = None,
        deadline_at: datetime | None = None,
    ) -> ExecutionOutcome:
        if not self._valid_object(arguments, spec.input_schema):
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.INVALID_ARGUMENT, False), 0)
            )
        if set(arguments).intersection(_SYSTEM_ARGUMENT_FIELDS):
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.INVALID_ARGUMENT, False), 0)
            )
        if not self._valid_runtime_binding(spec=spec, context=context):
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.PERMISSION_DENIED, False), 0)
            )
        if deadline_at is not None and datetime.now(deadline_at.tzinfo) >= deadline_at:
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.UPSTREAM_TIMEOUT, False), 0)
            )
        if not set(spec.required_scopes).issubset(context.scopes):
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.PERMISSION_DENIED, False), 0)
            )
        if spec.resource_binding is not None:
            resource_id = arguments.get(spec.resource_binding.argument)
            if resource_id is None or self._resource_authorizer is None:
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.RESOURCE_NOT_FOUND, False), 0
                    ),
                )
            try:
                authorized = self._resource_authorizer.authorize(
                    owner_check=spec.resource_binding.owner_check,
                    resource_id=resource_id,
                    context=context,
                )
            except Exception:
                authorized = False
            if authorized is not True:
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.RESOURCE_NOT_FOUND, False), 0
                    ),
                )
        if self._policy is not None:
            if context.policy_version != self._policy.version or policy_facts is None:
                return self._record(
                    spec, ExecutionOutcome(self._error(spec, ToolErrorCode.POLICY_DENIED, False), 0)
                )
            try:
                decision = self._policy.evaluate(action=spec.name, facts=policy_facts)
            except ValueError:
                return self._record(
                    spec, ExecutionOutcome(self._error(spec, ToolErrorCode.POLICY_DENIED, False), 0)
                )
            if decision.effect is not PolicyEffect.ALLOW:
                return self._record(
                    spec, ExecutionOutcome(self._error(spec, ToolErrorCode.POLICY_DENIED, False), 0)
                )
        adapter = self._adapters.get(spec.name)
        if adapter is None:
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), 0)
            )
        attempts = 0
        max_attempts = spec.retry_policy.max_attempts if spec.risk is ToolRisk.READ_ONLY else 1
        while attempts < max_attempts:
            if deadline_at is not None and datetime.now(deadline_at.tzinfo) >= deadline_at:
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.UPSTREAM_TIMEOUT, False), attempts
                    ),
                )
            attempts += 1
            started = self._clock()
            call_timeout = spec.timeout_ms / 1000
            if deadline_at is not None:
                call_timeout = min(
                    call_timeout,
                    max(0.0, (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds()),
                )
            call_result = self._invoke_with_timeout(
                adapter=adapter,
                context=context,
                arguments=arguments,
                timeout_seconds=call_timeout,
            )
            if isinstance(call_result, _AdapterTimedOut):
                code = (
                    ToolErrorCode.UPSTREAM_TIMEOUT
                    if spec.risk is ToolRisk.READ_ONLY
                    else ToolErrorCode.STATUS_UNKNOWN
                )
                result = self._error(spec, code, retryable=spec.risk is ToolRisk.READ_ONLY)
            elif isinstance(call_result, Exception):
                code = (
                    ToolErrorCode.INTERNAL_ERROR
                    if spec.risk is ToolRisk.READ_ONLY
                    else ToolErrorCode.STATUS_UNKNOWN
                )
                result = self._error(spec, code, retryable=False)
            elif not isinstance(call_result, ToolResult):
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), attempts
                    ),
                )
            else:
                result = call_result
            if (self._clock() - started) * 1000 > spec.timeout_ms:
                code = (
                    ToolErrorCode.UPSTREAM_TIMEOUT
                    if spec.risk is ToolRisk.READ_ONLY
                    else ToolErrorCode.STATUS_UNKNOWN
                )
                result = self._error(spec, code, retryable=spec.risk is ToolRisk.READ_ONLY)
            if result.tool_name != spec.name or result.tool_version != spec.version:
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), attempts
                    ),
                )
            if (result.data is None) == (result.error is None):
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), attempts
                    ),
                )
            if result.error is None and not self._valid_object(result.data, spec.output_schema):
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), attempts
                    ),
                )
            if (
                spec.risk is not ToolRisk.READ_ONLY
                and result.error is not None
                and result.error.code is ToolErrorCode.UPSTREAM_TIMEOUT
            ):
                result = self._error(spec, ToolErrorCode.STATUS_UNKNOWN, False)
            if (
                result.error is None
                or not result.error.retryable
                or result.error.code is ToolErrorCode.STATUS_UNKNOWN
            ):
                return self._record(spec, ExecutionOutcome(result, attempts))
        return self._record(spec, ExecutionOutcome(result, attempts))

    @staticmethod
    def _invoke_with_timeout(
        *,
        adapter: Callable[[ToolContext, dict[str, object]], ToolResult],
        context: ToolContext,
        arguments: dict[str, object],
        timeout_seconds: float,
    ) -> ToolResult | Exception | _AdapterTimedOut:
        """Bound a synchronous adapter without letting a stuck worker block process exit.

        Python cannot safely stop a running thread. The worker is therefore daemonized;
        callers regain control at the deadline and write risks are reported as unknown.
        Production adapters must still apply I/O-level timeouts to release their resources.
        """

        if timeout_seconds <= 0:
            return _AdapterTimedOut()
        result_queue: Queue[ToolResult | Exception] = Queue(maxsize=1)

        def call() -> None:
            try:
                result_queue.put(adapter(context, dict(arguments)))
            except Exception as error:
                result_queue.put(error)

        Thread(target=call, name=f"tool-{adapter!s}", daemon=True).start()
        try:
            return result_queue.get(timeout=timeout_seconds)
        except Empty:
            return _AdapterTimedOut()

    @staticmethod
    def _valid_runtime_binding(*, spec: ToolSpec, context: ToolContext) -> bool:
        if spec.allowed_workflows:
            workflow = (
                f"{context.workflow_id}@{context.workflow_version}"
                if context.workflow_id is not None and context.workflow_version is not None
                else None
            )
            if workflow not in spec.allowed_workflows:
                return False
        return not spec.allowed_steps or context.current_step in spec.allowed_steps

    def _record(self, spec: ToolSpec, outcome: ExecutionOutcome) -> ExecutionOutcome:
        """Append non-sensitive execution metadata without affecting the tool outcome.

        Arguments, adapter data, error messages, execution context, and policy facts can
        contain customer PII or trusted system values.  They are deliberately excluded
        before passing the observation to ``TraceStore``.
        """

        if self._traces is None:
            return outcome
        error = outcome.result.error
        payload: dict[str, object] = {
            "tool_name": spec.name,
            "tool_version": spec.version,
            "risk": spec.risk.value,
            "attempts": outcome.attempts,
            "outcome": "succeeded" if error is None else "failed",
        }
        if error is not None:
            payload["error_code"] = error.code.value
            payload["retryable"] = error.retryable
        try:
            self._traces.append(kind="tool_observed", payload=payload)
        except Exception:
            # Observability must not alter the trusted execution boundary.
            pass
        return outcome

    @staticmethod
    def _error(spec: ToolSpec, code: ToolErrorCode, retryable: bool) -> ToolResult:
        return ToolResult(
            tool_name=spec.name,
            tool_version=spec.version,
            error=ToolError(code=code, retryable=retryable, message="tool execution denied"),
        )

    @staticmethod
    def _valid_object(data: dict[str, object] | None, schema: dict[str, object]) -> bool:
        if data is None:
            return False
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            return False
        if any(not isinstance(name, str) or name not in data for name in required):
            return False
        if schema.get("additionalProperties") is False and set(data).difference(properties):
            return False
        for name, value in data.items():
            definition = properties.get(name)
            if not isinstance(definition, dict):
                continue
            expected = definition.get("type")
            if expected == "string" and not isinstance(value, str):
                return False
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                return False
            if expected == "boolean" and not isinstance(value, bool):
                return False
            if expected == "number" and (
                not isinstance(value, int | float) or isinstance(value, bool)
            ):
                return False
            if expected == "array" and not isinstance(value, list):
                return False
            if expected == "object" and not isinstance(value, dict):
                return False
        return True

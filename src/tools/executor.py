"""Trusted execution boundary for tool adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Any

from src.policies.engine import PolicyEffect, PolicyEngine
from src.protocols import ToolContext, ToolError, ToolErrorCode, ToolResult, ToolRisk, ToolSpec
from src.telemetry.trace import TraceStore


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ToolResult
    attempts: int


class ToolExecutor:
    """Executes only registered, scoped tools; never accepts model system fields."""

    def __init__(
        self,
        adapters: dict[str, Callable[[ToolContext, dict[str, object]], ToolResult]],
        *,
        policy: PolicyEngine | None = None,
        traces: TraceStore | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._adapters = dict(adapters)
        self._policy = policy
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
        if deadline_at is not None and datetime.now(deadline_at.tzinfo) >= deadline_at:
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.UPSTREAM_TIMEOUT, False), 0)
            )
        if not set(spec.required_scopes).issubset(context.scopes):
            return self._record(
                spec, ExecutionOutcome(self._error(spec, ToolErrorCode.PERMISSION_DENIED, False), 0)
            )
        if self._policy is not None:
            if policy_facts is None:
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
            try:
                result = adapter(context, arguments)
            except Exception:
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), attempts
                    ),
                )
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
            if result.error is None and not self._valid_output(result.data, spec.output_schema):
                return self._record(
                    spec,
                    ExecutionOutcome(
                        self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), attempts
                    ),
                )
            if (
                result.error is None
                or not result.error.retryable
                or result.error.code is ToolErrorCode.STATUS_UNKNOWN
            ):
                return self._record(spec, ExecutionOutcome(result, attempts))
        return self._record(spec, ExecutionOutcome(result, attempts))

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
    def _valid_output(data: dict[str, object] | None, schema: dict[str, object]) -> bool:
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
        return True

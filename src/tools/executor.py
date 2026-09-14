"""Trusted execution boundary for tool adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.protocols import ToolContext, ToolError, ToolErrorCode, ToolResult, ToolRisk, ToolSpec


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ToolResult
    attempts: int


class ToolExecutor:
    """Executes only registered, scoped tools; never accepts model system fields."""

    def __init__(
        self, adapters: dict[str, Callable[[ToolContext, dict[str, object]], ToolResult]]
    ) -> None:
        self._adapters = dict(adapters)

    def execute(
        self, *, spec: ToolSpec, context: ToolContext, arguments: dict[str, object]
    ) -> ExecutionOutcome:
        if not set(spec.required_scopes).issubset(context.scopes):
            return ExecutionOutcome(self._error(spec, ToolErrorCode.PERMISSION_DENIED, False), 0)
        adapter = self._adapters.get(spec.name)
        if adapter is None:
            return ExecutionOutcome(self._error(spec, ToolErrorCode.INTERNAL_ERROR, False), 0)
        attempts = 0
        max_attempts = spec.retry_policy.max_attempts if spec.risk is ToolRisk.READ_ONLY else 1
        while attempts < max_attempts:
            attempts += 1
            result = adapter(context, arguments)
            if (
                result.error is None
                or not result.error.retryable
                or result.error.code is ToolErrorCode.STATUS_UNKNOWN
            ):
                return ExecutionOutcome(result, attempts)
        return ExecutionOutcome(result, attempts)

    @staticmethod
    def _error(spec: ToolSpec, code: ToolErrorCode, retryable: bool) -> ToolResult:
        return ToolResult(
            tool_name=spec.name,
            tool_version=spec.version,
            error=ToolError(code=code, retryable=retryable, message="tool execution denied"),
        )

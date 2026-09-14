"""Deterministic fake tool adapters for runtime and harness tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from src.protocols import ToolContext, ToolResult


class DeterministicFakeToolAdapter:
    """Returns queued outcomes in call order and fails closed when exhausted."""

    def __init__(self, outcomes: Iterable[ToolResult]) -> None:
        self._outcomes = deque(outcomes)
        self.calls: list[tuple[ToolContext, dict[str, object]]] = []

    def __call__(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((context, dict(arguments)))
        if not self._outcomes:
            raise RuntimeError("fake tool outcome queue is exhausted")
        return self._outcomes.popleft()

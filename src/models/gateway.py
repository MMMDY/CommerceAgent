"""Narrow interface separating decision production from the agent loop."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from src.protocols import Decision, PromptView


class ModelGatewayError(RuntimeError):
    """A model provider failed without exposing credentials or raw payloads."""


@dataclass(frozen=True, slots=True)
class ModelDecision:
    decision: Decision
    latency_ms: int
    repaired: bool = False


class ModelGateway:
    def decide(self, prompt: PromptView) -> ModelDecision:
        raise NotImplementedError


class DeterministicFakeModel(ModelGateway):
    """FIFO decision source used to make loop paths fully reproducible."""

    def __init__(self, decisions: Sequence[Decision]) -> None:
        self._decisions = deque(decisions)
        self.prompts: list[PromptView] = []

    def decide(self, prompt: PromptView) -> ModelDecision:
        started = perf_counter()
        self.prompts.append(prompt)
        if not self._decisions:
            raise ModelGatewayError("fake model has no remaining decision")
        return ModelDecision(
            decision=self._decisions.popleft(),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
        )

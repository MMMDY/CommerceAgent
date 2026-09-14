"""Intent classification profile that reuses the configured Agent model."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Protocol

from src.models.gateway import ModelGatewayError
from src.protocols import IntentClassification, RoutingPromptView


class IntentClassifierGateway(Protocol):
    def classify(self, prompt: RoutingPromptView) -> IntentClassification: ...


class DeterministicFakeIntentClassifier:
    """FIFO classifier fixture for route and fail-closed tests."""

    provider = "deterministic_fake"
    model_name = "deterministic_fake"
    config_hash = "sha256:deterministic_fake_classifier"

    def __init__(self, classifications: Sequence[IntentClassification]) -> None:
        self._classifications = deque(classifications)
        self.prompts: list[RoutingPromptView] = []

    def classify(self, prompt: RoutingPromptView) -> IntentClassification:
        self.prompts.append(prompt)
        if not self._classifications:
            raise ModelGatewayError("fake intent classifier has no remaining result")
        return self._classifications.popleft()

"""Intent classification profile that reuses the configured Agent model."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from time import perf_counter
from typing import Protocol

from src.models.gateway import ClassificationResult, ModelGatewayError
from src.protocols import IntentClassification, RoutingPromptView, RunContext, TokenUsage


class IntentClassifierGateway(Protocol):
    def classify(
        self, prompt: RoutingPromptView
    ) -> IntentClassification | ClassificationResult: ...


class ClassificationInvocationRecorder(Protocol):
    def record_classification_success(
        self,
        *,
        context: RunContext,
        prompt: RoutingPromptView,
        result: IntentClassification,
        provider: str,
        model: str,
        config_hash: str,
        latency_ms: int,
        token_usage: TokenUsage | None,
    ) -> None: ...


class IntentClassifier:
    """Classify through the shared gateway and emit redacted invocation metadata."""

    def __init__(
        self,
        *,
        gateway: IntentClassifierGateway,
        invocations: ClassificationInvocationRecorder | None = None,
    ) -> None:
        self._gateway = gateway
        self._invocations = invocations

    def classify(
        self, *, context: RunContext, prompt: RoutingPromptView
    ) -> IntentClassification:
        started = perf_counter()
        raw_result = self._gateway.classify(prompt)
        if isinstance(raw_result, ClassificationResult):
            result = raw_result.classification
            latency_ms = raw_result.latency_ms
            token_usage = raw_result.token_usage
        else:
            result = raw_result
            latency_ms = max(0, round((perf_counter() - started) * 1000))
            token_usage = None
        if self._invocations is not None:
            self._invocations.record_classification_success(
                context=context,
                prompt=prompt,
                result=result,
                provider=getattr(self._gateway, "provider", "unknown"),
                model=getattr(self._gateway, "model_name", "unknown"),
                config_hash=getattr(
                    self._gateway,
                    "classifier_config_hash",
                    getattr(self._gateway, "config_hash", "unknown"),
                ),
                latency_ms=latency_ms,
                token_usage=token_usage,
            )
        return result


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

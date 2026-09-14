"""Narrow interface separating decision production from the agent loop."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

import httpx

from src.config import Settings
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
        self.provider = "deterministic_fake"
        self.model_name = "deterministic_fake"
        self.config_hash = "sha256:deterministic_fake"

    def decide(self, prompt: PromptView) -> ModelDecision:
        started = perf_counter()
        self.prompts.append(prompt)
        if not self._decisions:
            raise ModelGatewayError("fake model has no remaining decision")
        return ModelDecision(
            decision=self._decisions.popleft(),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
        )


class OpenAICompatibleGateway(ModelGateway):
    """Minimal OpenAI-compatible client with one format-repair attempt."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.model or not settings.api_base or not settings.api_key:
            raise ModelGatewayError("model configuration is unavailable")
        self._model = settings.model
        self._base_url = settings.api_base.rstrip("/")
        self._api_key = settings.api_key.get_secret_value()
        self._timeout = settings.model_timeout_seconds
        self._max_tokens = settings.model_max_tokens
        self._retry_attempts = settings.model_retry_attempts
        self._client = client or httpx.Client(timeout=self._timeout)
        self.provider = "openai_compatible"
        self.model_name = self._model
        fingerprint = json.dumps(
            {
                "api_base": self._base_url,
                "model": self._model,
                "max_tokens": self._max_tokens,
                "timeout_seconds": self._timeout,
                "retry_attempts": self._retry_attempts,
                "temperature": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.config_hash = f"sha256:{sha256(fingerprint.encode()).hexdigest()}"

    def decide(self, prompt: PromptView) -> ModelDecision:
        try:
            return self._request(prompt, repair=False)
        except (ValueError, KeyError, TypeError):
            try:
                return self._request(prompt, repair=True)
            except (ValueError, KeyError, TypeError) as error:
                raise ModelGatewayError("model decision is invalid after one repair") from error
            except httpx.HTTPError as error:
                raise ModelGatewayError("model provider request failed") from error
        except httpx.HTTPError as error:
            raise ModelGatewayError("model provider request failed") from error

    def _request(self, prompt: PromptView, *, repair: bool) -> ModelDecision:
        started = perf_counter()
        instruction = "Return only a JSON object matching the Decision schema."
        if repair:
            instruction += " Repair the prior format failure; do not add prose."
        payload = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": prompt.model_dump_json()},
            ],
        }
        response = self._post(payload)
        content = response.json()["choices"][0]["message"]["content"]
        return ModelDecision(
            decision=self._parse_decision(content, prompt),
            latency_ms=round((perf_counter() - started) * 1000),
            repaired=repair,
        )

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        for attempt in range(self._retry_attempts):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 == self._retry_attempts:
                    raise
            except httpx.HTTPStatusError as error:
                if error.response.status_code < 500 or attempt + 1 == self._retry_attempts:
                    raise
        raise RuntimeError("unreachable retry state")

    @staticmethod
    def _parse_decision(content: str, prompt: PromptView) -> Decision:
        content = content.strip()
        if content.startswith("```json") and content.endswith("```"):
            content = content[7:-3].strip()
        elif content.startswith("```") and content.endswith("```"):
            content = content[3:-3].strip()
        try:
            return Decision.model_validate_json(content)
        except ValueError as strict_error:
            raw = json.loads(content)
            legacy_type = raw.get("decision") if isinstance(raw, dict) else None
            rationale = raw.get("rationale") if isinstance(raw, dict) else None
            supported = {"respond", "ask_user", "handoff", "finish"}
            if legacy_type not in supported or not isinstance(rationale, str):
                raise strict_error
            return Decision(
                type=legacy_type,
                intent=prompt.workflow_id,
                route=prompt.workflow_id,
                confidence=0,
                response=rationale,
            )

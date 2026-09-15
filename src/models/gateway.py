"""Narrow interface separating decision production from the agent loop."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

import httpx

from src.config import Settings
from src.protocols import Decision, IntentClassification, PromptView, RoutingPromptView


class ModelGatewayError(RuntimeError):
    """A model provider failed without exposing credentials or raw payloads."""


@dataclass(frozen=True, slots=True)
class ModelDecision:
    decision: Decision
    latency_ms: int
    repaired: bool = False
    usage_tokens: int | None = None


class ModelGateway:
    def decide(self, prompt: PromptView) -> ModelDecision:
        raise NotImplementedError

    def classify(self, prompt: RoutingPromptView) -> IntentClassification:
        raise NotImplementedError

    def conservative_decision_token_charge(self) -> int:
        """Bound an invocation when a provider omits usage accounting."""

        return 2048


class DeterministicFakeModel(ModelGateway):
    """FIFO decision source used to make loop paths fully reproducible."""

    def __init__(
        self, decisions: Sequence[Decision], *, usage_tokens: Sequence[int | None] = ()
    ) -> None:
        self._decisions = deque(decisions)
        self._usage_tokens = deque(usage_tokens)
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
            usage_tokens=self._usage_tokens.popleft() if self._usage_tokens else None,
        )

    def conservative_decision_token_charge(self) -> int:
        return 1


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
        if not settings.classifier_configuration_is_valid():
            raise ModelGatewayError("classifier configuration is unavailable")
        self._classifier_model = settings.classifier_model or ""
        self._classifier_base_url = (settings.classifier_api_base or "").rstrip("/")
        self._classifier_api_key = (
            settings.classifier_api_key.get_secret_value() if settings.classifier_api_key else ""
        )
        self._classifier_temperature = settings.classifier_temperature
        self._classifier_max_tokens = settings.classifier_max_tokens
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
        classifier_fingerprint = json.dumps(
            {
                "api_base": self._classifier_base_url,
                "model": self._classifier_model,
                "max_tokens": self._classifier_max_tokens,
                "timeout_seconds": self._timeout,
                "retry_attempts": self._retry_attempts,
                "temperature": self._classifier_temperature,
                "purpose": "intent_classification",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.classifier_config_hash = (
            f"sha256:{sha256(classifier_fingerprint.encode()).hexdigest()}"
        )

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

    def classify(self, prompt: RoutingPromptView) -> IntentClassification:
        instruction = (
            "Return exactly one JSON object and no prose or markdown. "
            "Required fields: intent, risk_hint, route_hint, confidence, required_slots. "
            "risk_hint must be read_only, write, or unknown; confidence must be 0 through 1. "
            "Never return execution_mode, workflow_id, tool calls, identities, scopes, tokens, "
            "or policy values."
        )
        last_error: Exception | None = None
        for repair in (False, True):
            payload = {
                "model": self._classifier_model,
                "temperature": self._classifier_temperature,
                # Reasoning-capable providers can consume the whole initial
                # budget before emitting the small JSON object.  The repair
                # request gets the largest configured-safe budget so an empty
                # first response does not become a false handoff.
                "max_tokens": (
                    self._classifier_max_tokens
                    if not repair
                    else max(self._classifier_max_tokens, 2048)
                ),
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": instruction
                        + (" Output valid JSON only; do not include reasoning." if repair else ""),
                    },
                    {"role": "user", "content": prompt.model_dump_json()},
                ],
            }
            try:
                response = self._post_to(
                    base_url=self._classifier_base_url,
                    api_key=self._classifier_api_key,
                    payload=payload,
                )
                content = response.json()["choices"][0]["message"]["content"]
                return IntentClassification.model_validate_json(content.strip())
            except (KeyError, TypeError, ValueError, httpx.HTTPError) as error:
                last_error = error
        raise ModelGatewayError("intent classification is invalid or unavailable") from last_error

    def conservative_decision_token_charge(self) -> int:
        return self._max_tokens

    def _request(self, prompt: PromptView, *, repair: bool) -> ModelDecision:
        started = perf_counter()
        allowed_types = json.dumps(prompt.allowed_decisions, ensure_ascii=False)
        allowed_tools = json.dumps(prompt.allowed_tools, ensure_ascii=False)
        allowed_evidence_ids = json.dumps(prompt.evidence_ids, ensure_ascii=False)
        instruction = (
            "Return exactly one JSON object and no prose or markdown. "
            "Required fields: type, intent, route, confidence. "
            f"route must equal the locked workflow route '{prompt.workflow_id}'. "
            "Optional fields: missing_slots, tool, args, evidence_ids, response, handoff_reason. "
            f"type must be one of {allowed_types}; tool must be null or one of {allowed_tools}; "
            "confidence must be a number from 0 through 1; args must be one JSON object. "
            f"evidence_ids must be a subset of exactly {allowed_evidence_ids}; never invent or "
            "copy identifiers that are not listed there. "
            "Never include tenant_id, actor_id, owner_id, scopes, idempotency_key, "
            "confirmation_token, or policy_version in args."
        )
        if repair:
            instruction += " This is the single format-repair attempt; output valid JSON only."
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
        usage = response.json().get("usage")
        usage_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        if not isinstance(usage_tokens, int) or usage_tokens < 0:
            usage_tokens = None
        return ModelDecision(
            decision=self._parse_decision(content, prompt),
            latency_ms=round((perf_counter() - started) * 1000),
            repaired=repair,
            usage_tokens=usage_tokens,
        )

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        return self._post_to(base_url=self._base_url, api_key=self._api_key, payload=payload)

    def _post_to(
        self, *, base_url: str, api_key: str, payload: Mapping[str, object]
    ) -> httpx.Response:
        for attempt in range(self._retry_attempts):
            try:
                response = self._client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
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

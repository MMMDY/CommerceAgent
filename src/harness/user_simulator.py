"""Fail-closed user simulator interfaces and a deterministic pilot simulator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

import httpx

from src.guardrails.trust import sanitize
from src.harness.multiturn_schema import ScenarioSpec, UserAction


class SimulatorError(ValueError):
    """The simulator produced an action outside the scenario contract."""


@dataclass(frozen=True, slots=True)
class UserSimulatorConfig:
    provider: str = "deterministic_rule"
    model: str = "rule-v1"
    config_hash: str = "sha256:deterministic_user_simulator_v1"
    prompt_hash: str = "sha256:deterministic_user_simulator_prompt_v1"

    def metadata(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "config_hash": self.config_hash,
            "prompt_hash": self.prompt_hash,
        }


class OpenAICompatibleUserSimulatorProvider:
    """Independent, schema-constrained provider for real simulator runs.

    The provider receives only the public scenario boundary, action history,
    and the visible agent response.  Evaluator-only reference solutions and
    provenance are excluded before the request is serialized.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_tokens: int = 512,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip() or not api_key.strip() or not model.strip():
            raise ValueError("simulator provider configuration is incomplete")
        if timeout_seconds <= 0 or max_tokens < 64:
            raise ValueError("simulator provider limits are invalid")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(timeout=timeout_seconds)
        fingerprint = json.dumps(
            {
                "base_url": self._base_url,
                "model": model,
                "timeout_seconds": timeout_seconds,
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "purpose": "user_simulator",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.config = UserSimulatorConfig(
            provider="openai_compatible",
            model=model,
            config_hash=f"sha256:{sha256(fingerprint.encode()).hexdigest()}",
            prompt_hash=f"sha256:{sha256(_SYSTEM_PROMPT.encode()).hexdigest()}",
        )

    def __call__(
        self,
        *,
        scenario: ScenarioSpec,
        history: tuple[UserAction, ...],
        agent_response: str,
        pending_intents: tuple[str, ...],
    ) -> UserAction | Mapping[str, object] | str:
        payload = {
            "locale": scenario.locale,
            "domain": scenario.domain,
            "intent_agenda": [item.model_dump(mode="json") for item in scenario.intent_agenda],
            "behavior_facts": scenario.behavior_facts,
            "emotion_trajectory": list(scenario.emotion_trajectory),
            "profile": scenario.profile.model_dump(mode="json") if scenario.profile else None,
            "history": [item.model_dump(mode="json") for item in history],
            "agent_response": agent_response,
            "pending_intents": list(pending_intents),
        }
        request = {
            "model": self._model,
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        sanitize(payload), ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=request,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("simulator response content is not text")
            return content
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise SimulatorError("simulator_provider_unavailable") from error


_SYSTEM_PROMPT = """You are a constrained commerce user simulator.
Return exactly one JSON object matching UserAction: action, message,
target_intents, revealed_facts, emotion, should_continue, reason_code.
Generate only the user's next action. Never answer the user's task, reveal a
gold answer, invent facts, call tools, mutate data, or mention hidden
evaluation fields. Use only behavior_facts and profile facts. Keep one main
intent per turn. Use a terminal action only when the conversation is complete,
the user abandons it, or no safe progress is possible.
"""


class UserActionProvider(Protocol):
    def __call__(
        self,
        *,
        scenario: ScenarioSpec,
        history: tuple[UserAction, ...],
        agent_response: str,
        pending_intents: tuple[str, ...],
    ) -> UserAction | Mapping[str, object] | str: ...


class UserSimulator:
    """Validate provider output and enforce the simulator's information boundary."""

    def __init__(self, provider: UserActionProvider, config: UserSimulatorConfig | None = None) -> None:
        self._provider = provider
        self.config = config or UserSimulatorConfig()

    def next_action(
        self,
        *,
        scenario: ScenarioSpec,
        history: tuple[UserAction, ...],
        agent_response: str = "",
        pending_intents: tuple[str, ...] = (),
    ) -> UserAction:
        raw = self._provider(
            scenario=scenario,
            history=history,
            agent_response=agent_response,
            pending_intents=pending_intents,
        )
        action = parse_user_action(raw)
        validate_user_action(action, scenario=scenario)
        return action


class RuleUserSimulator:
    """A deterministic simulator for pilot/calibration runs.

    It only sees allowed facts and the public agent response.  In particular,
    it never accepts a reference solution or a hidden evaluation label as an
    input parameter.
    """

    def __call__(
        self,
        *,
        scenario: ScenarioSpec,
        history: tuple[UserAction, ...],
        agent_response: str,
        pending_intents: tuple[str, ...],
    ) -> UserAction:
        profile = scenario.profile
        emotion = profile.user_traits.emotion if profile else "neutral"
        if not history:
            message = scenario.initial_messages[0].content if scenario.initial_messages else (
                profile.semantic_anchor.core_request if profile else "我想咨询一个问题。"
            )
            return UserAction(
                action="initial_request",
                message=message,
                target_intents=(scenario.key_intents[0],),
                emotion=emotion,
                reason_code="initial_request",
            )
        if not pending_intents:
            return UserAction(
                action="finish",
                message="好的，明白了，谢谢。",
                emotion=emotion,
                should_continue=False,
                reason_code="all_key_intents_addressed",
            )
        if _is_unhelpful(agent_response) and len(history) >= (profile.conversation_policy.escalates_after_unhelpful_turns if profile else 2):
            return UserAction(
                action="abandon",
                message="这次先算了，我暂时不继续了。",
                target_intents=(pending_intents[0],),
                emotion="impatient",
                should_continue=False,
                reason_code="agent_no_progress",
            )
        reveal = _next_revealed_fact(scenario, history)
        if reveal is not None:
            value = scenario.behavior_facts.get(reveal)
            suffix = f"是{value}" if value is not None and not isinstance(value, (dict, list)) else ""
            return UserAction(
                action="provide_fact",
                message=f"补充一下，{reveal}{suffix}。",
                target_intents=(pending_intents[0],),
                revealed_facts=(reveal,),
                emotion=emotion,
                reason_code="agent_requested_or_needed_fact",
            )
        return UserAction(
            action="ask_followup",
            message=f"那请继续说明一下{pending_intents[0]}。",
            target_intents=(pending_intents[0],),
            emotion=emotion,
            reason_code="key_intent_not_addressed",
        )


def parse_user_action(raw: UserAction | Mapping[str, object] | str) -> UserAction:
    try:
        if isinstance(raw, UserAction):
            return raw
        if isinstance(raw, str):
            value = json.loads(raw)
        else:
            value = dict(raw)
        if not isinstance(value, dict):
            raise TypeError("action must be a JSON object")
        return UserAction.model_validate(value)
    except Exception as error:
        raise SimulatorError("invalid_user_action") from error


def validate_user_action(action: UserAction, *, scenario: ScenarioSpec) -> None:
    agenda = set(item.intent for item in scenario.intent_agenda)
    if not set(action.target_intents).issubset(agenda):
        raise SimulatorError("user_action_intent_outside_agenda")
    allowed_facts = set(scenario.behavior_facts)
    profile_facts = set(scenario.profile.conversation_policy.reveal_on_clarification) if scenario.profile else set()
    if not set(action.revealed_facts).issubset(allowed_facts | profile_facts):
        raise SimulatorError("user_action_fact_outside_behavior_facts")
    if action.action in {"initial_request", "provide_fact", "ask_followup", "clarify_intent"} and not action.should_continue:
        raise SimulatorError("non_terminal_action_must_continue")
    if action.action in {"abandon", "finish"} and action.should_continue:
        raise SimulatorError("terminal_action_must_stop")
    hidden_text = _hidden_evaluation_text(scenario)
    if any(value and value in action.message for value in hidden_text):
        raise SimulatorError("user_action_leaks_hidden_solution")


def _hidden_evaluation_text(scenario: ScenarioSpec) -> tuple[str, ...]:
    values: list[str] = []
    for key, value in scenario.reference_solution.items():
        # Required facts can be independently expressed by the user. Protect
        # answer-like text without rejecting ordinary intent wording.
        if key in {"gold_response", "expected_answer", "forbidden_claims"}:
            if isinstance(value, list):
                values.extend(str(item) for item in value if len(str(item)) >= 4)
            elif isinstance(value, str) and len(value) >= 4:
                values.append(value)
    return tuple(values)


def _same_action(left: UserAction, right: UserAction) -> bool:
    return left.action == right.action and left.message == right.message and left.target_intents == right.target_intents


def _is_unhelpful(response: str) -> bool:
    return not response.strip() or response.strip() in {"无法处理。", "我不知道。"}


def _next_revealed_fact(scenario: ScenarioSpec, history: tuple[UserAction, ...]) -> str | None:
    candidates = (
        scenario.profile.conversation_policy.reveal_on_clarification
        if scenario.profile
        else tuple(scenario.behavior_facts)
    )
    already = {fact for action in history for fact in action.revealed_facts}
    for fact in candidates:
        if fact not in already:
            return fact
    return None


__all__ = [
    "OpenAICompatibleUserSimulatorProvider",
    "RuleUserSimulator",
    "SimulatorError",
    "UserActionProvider",
    "UserSimulatorConfig",
    "UserSimulator",
    "parse_user_action",
    "validate_user_action",
]

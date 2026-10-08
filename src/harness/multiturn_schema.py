"""Contracts for constrained multi-turn evaluation.

The scenario contract deliberately contains evaluator-only fields.  Callers
must construct ``RuntimeCaseInput`` from the emitted user messages instead of
passing a ``ScenarioSpec`` to an agent runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from src.harness.schema import EvalMessage, NormalizedTrace
from src.protocols import Contract


IntentPriority = Literal["key", "minor"]
IntentStateValue = Literal["NOT_RAISED", "RAISED", "ADDRESSED", "VERIFIED"]
UserActionType = Literal[
    "initial_request",
    "provide_fact",
    "ask_followup",
    "clarify_intent",
    "resist",
    "confirm",
    "abandon",
    "finish",
]


class AgendaItem(Contract):
    intent: str = Field(min_length=1, max_length=128)
    priority: IntentPriority = "key"
    required: bool = True


class LongTailSeed(Contract):
    seed_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    raw_user_text: str = Field(min_length=1, max_length=8000)
    source: str = Field(min_length=1, max_length=128)
    domain_hint: str | None = Field(default=None, max_length=128)
    known_labels: tuple[str, ...] = ()
    context: dict[str, Any] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)
    review_status: Literal["candidate", "approved", "rejected"] = "candidate"


class SemanticAnchor(Contract):
    core_request: str = Field(min_length=1, max_length=1000)
    preserve_terms: tuple[str, ...] = ()
    allowed_intent_hypotheses: tuple[str, ...] = ()
    forbidden_intent_inventions: tuple[str, ...] = ()


class UserTraits(Contract):
    expression_style: str = Field(min_length=1, max_length=128)
    emotion: str = Field(min_length=1, max_length=64)
    cooperation: Literal["low", "medium", "high"] = "medium"
    patience: Literal["low", "medium", "high"] = "medium"
    domain_familiarity: str = "unknown"


class ConversationPolicy(Contract):
    initial_information_completeness: Literal["low", "partial", "complete"] = "low"
    reveal_on_clarification: tuple[str, ...] = ()
    accepts_clarifying_question: bool = True
    escalates_after_unhelpful_turns: int = Field(default=2, ge=1, le=8)


class SimulatedUserProfile(Contract):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,191}$")
    seed_id: str = Field(min_length=1, max_length=128)
    semantic_anchor: SemanticAnchor
    user_traits: UserTraits
    conversation_policy: ConversationPolicy
    variant_type: str = Field(min_length=1, max_length=128)
    generator: str = Field(min_length=1, max_length=128)
    prompt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    review_status: Literal["candidate", "approved", "rejected"] = "candidate"


class ScenarioTermination(Contract):
    max_turns: int = Field(default=8, ge=1, le=32)
    required_key_intents_addressed: bool = True
    allow_abandonment: bool = True


class ScenarioSpec(Contract):
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,191}$")
    locale: Literal["zh-CN"] = "zh-CN"
    domain: str = Field(min_length=1, max_length=128)
    intent_agenda: tuple[AgendaItem, ...] = Field(min_length=1, max_length=32)
    behavior_facts: dict[str, Any] = Field(default_factory=dict)
    emotion_trajectory: tuple[str, ...] = ()
    reference_solution: dict[str, Any] = Field(default_factory=dict)
    termination: ScenarioTermination = ScenarioTermination()
    profile: SimulatedUserProfile | None = None
    initial_messages: tuple[EvalMessage, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_agenda(self) -> ScenarioSpec:
        intents = [item.intent for item in self.intent_agenda]
        if len(set(intents)) != len(intents):
            raise ValueError("scenario agenda contains duplicate intents")
        if not any(item.priority == "key" for item in self.intent_agenda):
            raise ValueError("scenario requires at least one key intent")
        return self

    @property
    def key_intents(self) -> tuple[str, ...]:
        return tuple(item.intent for item in self.intent_agenda if item.priority == "key")


class UserAction(Contract):
    action: UserActionType
    message: str = Field(min_length=1, max_length=8000)
    target_intents: tuple[str, ...] = ()
    revealed_facts: tuple[str, ...] = ()
    emotion: str = Field(default="neutral", min_length=1, max_length=64)
    should_continue: bool = True
    reason_code: str = Field(min_length=1, max_length=128)


class IntentTransition(Contract):
    intent: str
    from_state: IntentStateValue
    to_state: IntentStateValue
    turn_id: int = Field(ge=1)
    evidence: tuple[str, ...] = ()


class TurnTrace(Contract):
    scenario_id: str
    dialogue_id: str
    turn_id: int = Field(ge=1)
    user_action: UserAction
    agent_trace: NormalizedTrace
    raised_intents: tuple[str, ...] = ()
    addressed_intents: tuple[str, ...] = ()
    intent_states: dict[str, IntentStateValue] = Field(default_factory=dict)
    transitions: tuple[IntentTransition, ...] = ()
    verifier_pass: bool | None = None
    version_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FeedbackSignal(Contract):
    signal_id: str
    scenario_id: str
    category: Literal["knowledge_gap", "capability_limit", "evaluation_noise", "simulator_error", "agent_error"]
    code: str
    severity: Literal["info", "warning", "critical"] = "warning"
    turn_ids: tuple[int, ...] = ()
    evidence: tuple[str, ...] = ()
    reusable: bool = True


class MultiTurnReport(Contract):
    scenario_id: str
    dialogue_id: str
    status: Literal["completed", "abandoned", "incomplete"]
    termination_reason: str
    turns: tuple[TurnTrace, ...] = ()
    intent_coverage: float = Field(ge=0, le=1)
    agenda_progress: float = Field(ge=0, le=1)
    exposed_intent_accuracy: float | None = Field(default=None, ge=0, le=1)
    task_success: bool | None = None
    evaluation_noise: bool = False
    feedback: tuple[FeedbackSignal, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgendaItem",
    "ConversationPolicy",
    "FeedbackSignal",
    "IntentTransition",
    "LongTailSeed",
    "MultiTurnReport",
    "ScenarioSpec",
    "ScenarioTermination",
    "SemanticAnchor",
    "SimulatedUserProfile",
    "TurnTrace",
    "UserAction",
    "UserTraits",
]

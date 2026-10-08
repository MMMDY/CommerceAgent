"""Intent state machine used by the multi-turn evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.harness.multiturn_schema import IntentStateValue, IntentTransition


class IntentStateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IntentState:
    intent: str
    state: IntentStateValue = "NOT_RAISED"


class IntentStateMachine:
    """Track only evidence-backed transitions for a fixed scenario agenda."""

    def __init__(self, intents: tuple[str, ...]) -> None:
        if not intents or len(set(intents)) != len(intents):
            raise IntentStateError("intent agenda must be non-empty and unique")
        self._states = {intent: "NOT_RAISED" for intent in intents}
        self._history: list[IntentTransition] = []

    @property
    def states(self) -> dict[str, IntentStateValue]:
        return dict(self._states)

    @property
    def history(self) -> tuple[IntentTransition, ...]:
        return tuple(self._history)

    def raise_intents(
        self, intents: tuple[str, ...] | list[str], *, turn_id: int, evidence: tuple[str, ...] = ()
    ) -> tuple[IntentTransition, ...]:
        transitions: list[IntentTransition] = []
        for intent in intents:
            self._require_intent(intent)
            current = self._states[intent]
            if current == "NOT_RAISED":
                transitions.append(self._transition(intent, "RAISED", turn_id, evidence))
        return tuple(transitions)

    def address_intents(
        self, intents: tuple[str, ...] | list[str], *, turn_id: int, evidence: tuple[str, ...] = ()
    ) -> tuple[IntentTransition, ...]:
        transitions: list[IntentTransition] = []
        for intent in intents:
            self._require_intent(intent)
            current = self._states[intent]
            if current == "NOT_RAISED":
                raise IntentStateError("unraised intent cannot become addressed")
            if current == "RAISED":
                transitions.append(self._transition(intent, "ADDRESSED", turn_id, evidence))
        return tuple(transitions)

    def verify_intents(
        self, intents: tuple[str, ...] | list[str], *, turn_id: int, evidence: tuple[str, ...] = ()
    ) -> tuple[IntentTransition, ...]:
        transitions: list[IntentTransition] = []
        for intent in intents:
            self._require_intent(intent)
            current = self._states[intent]
            if current == "NOT_RAISED":
                raise IntentStateError("unraised intent cannot become verified")
            if current == "RAISED":
                raise IntentStateError("intent must be addressed before verified")
            if current == "ADDRESSED":
                transitions.append(self._transition(intent, "VERIFIED", turn_id, evidence))
        return tuple(transitions)

    def raised(self) -> tuple[str, ...]:
        return tuple(intent for intent, state in self._states.items() if state != "NOT_RAISED")

    def addressed(self) -> tuple[str, ...]:
        return tuple(
            intent for intent, state in self._states.items() if state in {"ADDRESSED", "VERIFIED"}
        )

    def all_addressed(self, intents: tuple[str, ...] | None = None) -> bool:
        selected = intents or tuple(self._states)
        return all(self._states[intent] in {"ADDRESSED", "VERIFIED"} for intent in selected)

    def _transition(
        self,
        intent: str,
        to_state: IntentStateValue,
        turn_id: int,
        evidence: tuple[str, ...],
    ) -> IntentTransition:
        from_state = self._states[intent]
        transition = IntentTransition(
            intent=intent,
            from_state=from_state,
            to_state=to_state,
            turn_id=turn_id,
            evidence=evidence,
        )
        self._states[intent] = to_state
        self._history.append(transition)
        return transition

    def _require_intent(self, intent: str) -> None:
        if intent not in self._states:
            raise IntentStateError(f"intent is outside scenario agenda: {intent}")


__all__ = ["IntentState", "IntentStateError", "IntentStateMachine"]

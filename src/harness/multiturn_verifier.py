"""Independent verifier for simulator-side and agent-side multi-turn metrics."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid5, NAMESPACE_URL

from src.harness.multiturn_schema import (
    FeedbackSignal,
    MultiTurnReport,
    ScenarioSpec,
    TurnTrace,
    UserAction,
)
from src.harness.schema import NormalizedTrace


class MultiTurnVerifier:
    def verify(
        self,
        *,
        scenario: ScenarioSpec,
        dialogue_id: str,
        turns: Iterable[TurnTrace],
        termination_reason: str,
        status: str,
    ) -> MultiTurnReport:
        turn_list = tuple(turns)
        raised = {intent for turn in turn_list for intent in turn.raised_intents}
        addressed = {intent for turn in turn_list for intent in turn.addressed_intents}
        key = set(scenario.key_intents)
        coverage = len(raised & key) / len(key) if key else 1.0
        progress = len(addressed & raised) / len(raised) if raised else 0.0
        exposed = self._exposed_accuracy(scenario, turn_list, raised)
        noise = not key.issubset(raised)
        feedback = list(self._feedback(scenario, turn_list, noise=noise, termination_reason=termination_reason))
        task_success = (
            status == "completed"
            and not noise
            and key.issubset(addressed)
            and not any(turn.agent_trace.status == "fail" for turn in turn_list)
            and not any(signal.category == "agent_error" for signal in feedback)
        )
        return MultiTurnReport(
            scenario_id=scenario.scenario_id,
            dialogue_id=dialogue_id,
            status=status,  # type: ignore[arg-type]
            termination_reason=termination_reason,
            turns=turn_list,
            intent_coverage=round(coverage, 4),
            agenda_progress=round(progress, 4),
            exposed_intent_accuracy=exposed,
            task_success=task_success if status != "incomplete" else None,
            evaluation_noise=noise,
            feedback=tuple(feedback),
            metadata={
                "key_intents": sorted(key),
                "raised_key_intents": sorted(raised & key),
                "addressed_key_intents": sorted(addressed & key),
            },
        )

    def addressed_intents(self, *, action: UserAction, trace: NormalizedTrace) -> tuple[str, ...]:
        if action.action in {"abandon", "finish"}:
            return ()
        if trace.status != "complete" or not trace.response.strip():
            return ()
        if trace.next_action in {"ask_user", "ask_for_slots", "handoff", "wait_human", "fail"}:
            return ()
        return tuple(
            intent for intent in action.target_intents if trace.intent == intent or trace.next_action in {"safe_deescalation", "refuse"}
        )

    def _exposed_accuracy(
        self, scenario: ScenarioSpec, turns: tuple[TurnTrace, ...], raised: set[str]
    ) -> float | None:
        if not raised:
            return None
        correct = 0
        for intent in raised:
            if any(intent in turn.addressed_intents for turn in turns):
                correct += 1
        return round(correct / len(raised), 4)

    def _feedback(
        self,
        scenario: ScenarioSpec,
        turns: tuple[TurnTrace, ...],
        *,
        noise: bool,
        termination_reason: str,
    ) -> tuple[FeedbackSignal, ...]:
        signals: list[FeedbackSignal] = []
        if noise:
            signals.append(self._signal(scenario, "evaluation_noise", "simulator_intent_not_raised", "warning", turns))
        for turn in turns:
            if turn.agent_trace.status == "fail":
                signals.append(self._signal(scenario, "agent_error", "runtime_failure", "critical", (turn,)))
            elif turn.user_action.action in {"ask_followup", "provide_fact"} and not turn.addressed_intents:
                signals.append(self._signal(scenario, "agent_error", "intent_not_addressed", "warning", (turn,)))
            elif turn.agent_trace.next_action in {"handoff", "wait_human"}:
                signals.append(self._signal(scenario, "capability_limit", "human_handoff", "warning", (turn,)))
        if termination_reason == "max_turns_reached":
            signals.append(self._signal(scenario, "agent_error", "max_turns_reached", "warning", turns))
        return tuple(signals)

    def _signal(
        self,
        scenario: ScenarioSpec,
        category: str,
        code: str,
        severity: str,
        turns: Iterable[TurnTrace],
    ) -> FeedbackSignal:
        ids = tuple(turn.turn_id for turn in turns)
        return FeedbackSignal(
            signal_id=str(uuid5(NAMESPACE_URL, f"{scenario.scenario_id}:{category}:{code}:{ids}")),
            scenario_id=scenario.scenario_id,
            category=category,  # type: ignore[arg-type]
            code=code,
            severity=severity,  # type: ignore[arg-type]
            turn_ids=ids,
            evidence=tuple(
                evidence
                for turn in turns
                for evidence in (turn.agent_trace.evidence_ids + (f"response:turn_{turn.turn_id}",))
            ),
        )


__all__ = ["MultiTurnVerifier"]

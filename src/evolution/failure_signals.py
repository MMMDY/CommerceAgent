"""Convert observable outcomes into bounded failure signals."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass

from src.evolution.contracts import FailureSignal


@dataclass(frozen=True, slots=True)
class SignalObservation:
    signal: FailureSignal
    severity: str
    source: str
    reason_code: str


def signals_for_run(
    *,
    status: str,
    terminal_reason: str | None = None,
    eval_failed: bool = False,
    human_rejected: bool = False,
) -> tuple[SignalObservation, ...]:
    reason = (terminal_reason or "UNKNOWN").upper()[:64]
    observations: list[SignalObservation] = []
    if status == "failed":
        observations.append(SignalObservation(FailureSignal.RUN_FAILED, "p1", "runtime", reason))
    if status == "waiting_human":
        observations.append(SignalObservation(FailureSignal.HUMAN_HANDOFF, "p1", "runtime", reason))
    if status == "expired":
        observations.append(SignalObservation(FailureSignal.EXPIRED, "p1", "runtime", reason))
    if "LOW_CLASSIFICATION_CONFIDENCE" in reason:
        observations.append(SignalObservation(FailureSignal.LOW_CONFIDENCE, "p2", "router", reason))
    if "COST" in reason:
        observations.append(SignalObservation(FailureSignal.COST_EXCEEDED, "p1", "budget", reason))
    if eval_failed:
        observations.append(SignalObservation(FailureSignal.EVAL_FAIL, "p1", "evaluation", reason))
    if human_rejected:
        observations.append(
            SignalObservation(FailureSignal.HUMAN_REJECTED, "p1", "human_review", reason)
        )
    return tuple(observations)


def signals_for_evaluation(
    *,
    eval_failed: bool,
    cost_microusd: int | None = None,
    cost_budget_microusd: int | None = None,
    failure_reason: str = "EVALUATION_FAILED",
) -> tuple[SignalObservation, ...]:
    """Convert one evaluation attempt into bounded failure observations.

    A missing cost or budget is deliberately not treated as zero.  This keeps
    cost-based learning fail-closed when pricing or the evaluation budget is
    unavailable.  ``failure_reason`` is expected to be a short, non-sensitive
    evaluator code, never a case prompt or model response.
    """

    reason = (failure_reason or "EVALUATION_FAILED").upper()[:64]
    observations: list[SignalObservation] = []
    if eval_failed:
        observations.append(
            SignalObservation(FailureSignal.EVAL_FAIL, "p1", "evaluation", reason)
        )
    if (
        cost_microusd is not None
        and cost_budget_microusd is not None
        and cost_budget_microusd >= 0
        and cost_microusd > cost_budget_microusd
    ):
        observations.append(
            SignalObservation(
                FailureSignal.COST_EXCEEDED,
                "p1",
                "budget",
                "EVAL_CASE_COST_EXCEEDED",
            )
        )
    return tuple(observations)


__all__ = ["SignalObservation", "signals_for_evaluation", "signals_for_run"]

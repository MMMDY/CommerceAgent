from src.evolution.contracts import FailureSignal
from src.evolution.failure_signals import signals_for_evaluation, signals_for_run


def test_run_outcome_projects_terminal_and_derived_signals() -> None:
    signals = signals_for_run(
        status="failed",
        terminal_reason="LOW_CLASSIFICATION_CONFIDENCE_COST_EXCEEDED",
        eval_failed=True,
        human_rejected=True,
    )

    assert tuple(item.signal for item in signals) == (
        FailureSignal.RUN_FAILED,
        FailureSignal.LOW_CONFIDENCE,
        FailureSignal.COST_EXCEEDED,
        FailureSignal.EVAL_FAIL,
        FailureSignal.HUMAN_REJECTED,
    )


def test_waiting_human_and_expired_are_distinct_observations() -> None:
    assert signals_for_run(status="waiting_human")[0].signal is FailureSignal.HUMAN_HANDOFF
    assert signals_for_run(status="expired")[0].signal is FailureSignal.EXPIRED


def test_evaluation_signals_require_an_explicit_complete_cost_budget() -> None:
    signals = signals_for_evaluation(
        eval_failed=True,
        cost_microusd=101,
        cost_budget_microusd=100,
        failure_reason="JUDGE_FAIL",
    )
    assert tuple(item.signal for item in signals) == (
        FailureSignal.EVAL_FAIL,
        FailureSignal.COST_EXCEEDED,
    )
    assert signals_for_evaluation(
        eval_failed=False,
        cost_microusd=None,
        cost_budget_microusd=100,
    ) == ()
    assert signals_for_evaluation(
        eval_failed=False,
        cost_microusd=101,
        cost_budget_microusd=None,
    ) == ()

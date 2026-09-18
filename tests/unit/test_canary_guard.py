from src.release.canary_guard import CanaryMetrics, evaluate_canary


def test_canary_stops_on_safety_and_regression() -> None:
    decision = evaluate_canary(
        CanaryMetrics(
            p0_events=1,
            quality_gate_pass=True,
            safety_gate_pass=True,
            terminal_response_coverage=1,
            p95_e2e_ms=1_160,
            baseline_p95_e2e_ms=1_000,
            p99_e2e_ms=1_000,
            baseline_p99_e2e_ms=1_000,
            p95_cost_microusd=1_101,
            baseline_p95_cost_microusd=1_000,
        )
    )
    assert decision.stop
    assert "p0_safety_event" in decision.reasons
    assert "p95_e2e_above_15_percent" in decision.reasons
    assert "p95_cost_above_10_percent" in decision.reasons


def test_canary_is_not_green_when_coverage_is_unknown() -> None:
    decision = evaluate_canary(CanaryMetrics())
    assert decision.stop
    assert "terminal_response_coverage_below_100_percent" in decision.reasons


def test_canary_stops_on_skill_scope_or_target_slice_regression() -> None:
    decision = evaluate_canary(
        CanaryMetrics(
            quality_gate_pass=True,
            safety_gate_pass=True,
            terminal_response_coverage=1,
            skill_scope_violation=True,
            target_slice_quality_delta=-0.1,
        )
    )

    assert decision.stop
    assert "skill_scope_violation" in decision.reasons
    assert "skill_target_slice_quality_regression" in decision.reasons

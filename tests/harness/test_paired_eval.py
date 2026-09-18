from src.harness.paired_eval import compare_reports


def _report(*, quality: bool, safety: bool = True, latency: float = 100, cost: float = 100):
    return {
        "status": "completed",
        "results": [
            {
                "case_id": "case_a",
                "track": "long_tail_response_v1",
                "final_pass": quality,
                "hard_pass": True,
            },
            {
                "case_id": "case_s",
                "track": "safety_response_v2",
                "final_pass": safety,
                "hard_pass": safety,
            },
        ],
        "performance_stats": {
            "overall": {
                "e2e_latency_ms": {"p95": latency},
                "agent_cost_microusd": {"p95": cost},
            }
        },
    }


def test_paired_eval_requires_quality_gain_without_safety_or_cost_regression() -> None:
    result = compare_reports(
        _report(quality=False),
        _report(quality=True, latency=110, cost=105),
    )

    assert result.gate_pass is True
    assert result.quality_delta == 0.5
    assert result.safety_delta == 0.0


def test_paired_eval_fails_closed_on_safety_regression() -> None:
    result = compare_reports(_report(quality=False), _report(quality=True, safety=False))

    assert result.gate_pass is False
    assert "safety_regressed" in result.reasons


def test_paired_eval_does_not_treat_missing_cost_as_zero() -> None:
    after = _report(quality=True)
    after["performance_stats"]["overall"]["agent_cost_microusd"] = {"p95": None}

    result = compare_reports(_report(quality=False), after)

    assert result.gate_pass is False
    assert "cost_metric_unavailable" in result.reasons

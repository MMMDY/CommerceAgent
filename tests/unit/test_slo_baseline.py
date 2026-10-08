from datetime import UTC, datetime, timedelta

import pytest

from src.release.slo_baseline import (
    BaselineSample,
    BaselineValidationError,
    freeze_baseline,
)


def _samples() -> list[BaselineSample]:
    start = datetime(2026, 9, 7, 0, tzinfo=UTC)  # Monday
    return [
        BaselineSample(
            occurred_at=start + timedelta(hours=hour),
            e2e_latency_ms=100 + hour,
            cost_microusd=200 + hour,
            low_risk_handoff_rate=0.02,
            terminal_response_coverage=1.0,
        )
        for hour in range(0, 24 * 8 + 1, 2)
    ]


def test_freeze_requires_weekday_and_weekend_and_emits_absolute_slos() -> None:
    baseline = freeze_baseline(_samples(), timezone="UTC", minimum_samples=10)

    assert baseline.observed_hours == 192.0
    assert baseline.distinct_dates == 9
    assert baseline.weekday_samples > 0
    assert baseline.weekend_samples > 0
    assert baseline.baseline_p95_e2e_ms > baseline.baseline_p50_e2e_ms
    assert baseline.baseline_p95_cost_microusd > 200
    assert baseline.baseline_terminal_response_coverage == 1.0


def test_freeze_rejects_short_or_missing_metric_evidence() -> None:
    with pytest.raises(BaselineValidationError, match="168_hours"):
        freeze_baseline(_samples()[:20], timezone="UTC", minimum_samples=1)

    incomplete = [
        BaselineSample(
            occurred_at=item.occurred_at,
            e2e_latency_ms=None,
            cost_microusd=item.cost_microusd,
            low_risk_handoff_rate=item.low_risk_handoff_rate,
        )
        for item in _samples()
    ]
    with pytest.raises(BaselineValidationError, match="e2e_latency_ms"):
        freeze_baseline(incomplete, timezone="UTC", minimum_samples=1)

    incomplete_coverage = [
        BaselineSample(
            occurred_at=item.occurred_at,
            e2e_latency_ms=item.e2e_latency_ms,
            cost_microusd=item.cost_microusd,
            low_risk_handoff_rate=item.low_risk_handoff_rate,
            terminal_response_coverage=None,
        )
        for item in _samples()
    ]
    with pytest.raises(BaselineValidationError, match="terminal_response_coverage"):
        freeze_baseline(incomplete_coverage, timezone="UTC", minimum_samples=1)


def test_freeze_rejects_naive_timestamps_and_invalid_rates() -> None:
    rows = _samples()
    rows[0] = BaselineSample(
        occurred_at=rows[0].occurred_at.replace(tzinfo=None),
        e2e_latency_ms=1,
        cost_microusd=1,
        low_risk_handoff_rate=0,
    )
    with pytest.raises(BaselineValidationError, match="timezone_aware"):
        freeze_baseline(rows, timezone="UTC", minimum_samples=1)

    with pytest.raises(BaselineValidationError, match="between_0_and_1"):
        freeze_baseline(
            [
                BaselineSample(
                    occurred_at=item.occurred_at,
                    e2e_latency_ms=item.e2e_latency_ms,
                    cost_microusd=item.cost_microusd,
                    low_risk_handoff_rate=1.1,
                )
                for item in _samples()
            ],
            timezone="UTC",
            minimum_samples=1,
        )

"""Fail-closed seven-day baseline validation and SLO freezing.

This module only freezes an absolute baseline after the input evidence spans
at least seven days and contains both weekday and weekend observations.  It
does not manufacture missing metrics or treat a sparse one-day fixture as a
production baseline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import fmean
from zoneinfo import ZoneInfo


class BaselineValidationError(ValueError):
    """Raised when the evidence is insufficient to freeze an absolute SLO."""


@dataclass(frozen=True, slots=True)
class BaselineSample:
    occurred_at: datetime
    e2e_latency_ms: float | None
    cost_microusd: float | None
    low_risk_handoff_rate: float | None
    terminal_response_coverage: float | None = None


@dataclass(frozen=True, slots=True)
class FrozenSLOBaseline:
    timezone: str
    window_start: str
    window_end: str
    observed_hours: float
    distinct_dates: int
    weekday_samples: int
    weekend_samples: int
    sample_count: int
    latency_sample_count: int
    cost_sample_count: int
    handoff_sample_count: int
    terminal_coverage_sample_count: int
    baseline_p50_e2e_ms: float
    baseline_p95_e2e_ms: float
    baseline_p99_e2e_ms: float
    baseline_p95_cost_microusd: float
    baseline_low_risk_handoff_rate: float
    baseline_terminal_response_coverage: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def freeze_baseline(
    samples: Iterable[BaselineSample],
    *,
    timezone: str = "Asia/Shanghai",
    minimum_samples: int = 100,
) -> FrozenSLOBaseline:
    """Validate and aggregate a seven-day evidence window.

    The window is measured from the earliest to latest observed timestamp.
    A baseline must span at least 168 hours, touch at least seven local dates,
    and contain both weekday and weekend observations.  Required metrics must
    have at least ``minimum_samples`` values; missing values are never treated
    as zero or as a passing measurement.
    """

    if minimum_samples < 1:
        raise ValueError("minimum_samples_must_be_positive")
    zone = ZoneInfo(timezone)
    rows = tuple(_normalize_sample(sample, zone) for sample in samples)
    if not rows:
        raise BaselineValidationError("no_baseline_samples")

    start = min(row.occurred_at for row in rows)
    end = max(row.occurred_at for row in rows)
    observed_hours = (end - start).total_seconds() / 3600
    local_dates = {row.occurred_at.date() for row in rows}
    weekday_samples = sum(row.occurred_at.weekday() < 5 for row in rows)
    weekend_samples = len(rows) - weekday_samples
    if observed_hours < 7 * 24:
        raise BaselineValidationError("baseline_window_must_cover_at_least_168_hours")
    if len(local_dates) < 7:
        raise BaselineValidationError("baseline_must_cover_at_least_7_local_dates")
    if weekday_samples == 0 or weekend_samples == 0:
        raise BaselineValidationError("baseline_must_include_weekday_and_weekend")

    latency = _required_values(rows, "e2e_latency_ms", minimum_samples)
    cost = _required_values(rows, "cost_microusd", minimum_samples)
    handoff = _required_values(rows, "low_risk_handoff_rate", minimum_samples)
    coverage = _required_values(rows, "terminal_response_coverage", minimum_samples)
    return FrozenSLOBaseline(
        timezone=timezone,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        observed_hours=round(observed_hours, 3),
        distinct_dates=len(local_dates),
        weekday_samples=weekday_samples,
        weekend_samples=weekend_samples,
        sample_count=len(rows),
        latency_sample_count=len(latency),
        cost_sample_count=len(cost),
        handoff_sample_count=len(handoff),
        terminal_coverage_sample_count=len(coverage),
        baseline_p50_e2e_ms=round(_quantile(latency, 0.50), 3),
        baseline_p95_e2e_ms=round(_quantile(latency, 0.95), 3),
        baseline_p99_e2e_ms=round(_quantile(latency, 0.99), 3),
        baseline_p95_cost_microusd=round(_quantile(cost, 0.95), 3),
        baseline_low_risk_handoff_rate=round(fmean(handoff), 6),
        baseline_terminal_response_coverage=round(fmean(coverage), 6),
    )


def _normalize_sample(sample: BaselineSample, zone: ZoneInfo) -> BaselineSample:
    occurred_at = sample.occurred_at
    if occurred_at.tzinfo is None:
        raise BaselineValidationError("baseline_timestamp_must_be_timezone_aware")
    return BaselineSample(
        occurred_at=occurred_at.astimezone(zone),
        e2e_latency_ms=_non_negative(sample.e2e_latency_ms, "e2e_latency_ms"),
        cost_microusd=_non_negative(sample.cost_microusd, "cost_microusd"),
        low_risk_handoff_rate=_bounded(sample.low_risk_handoff_rate, "low_risk_handoff_rate"),
        terminal_response_coverage=_bounded(
            sample.terminal_response_coverage, "terminal_response_coverage"
        ),
    )


def _required_values(
    rows: tuple[BaselineSample, ...], field: str, minimum_samples: int
) -> tuple[float, ...]:
    values = tuple(
        float(value)
        for row in rows
        if (value := getattr(row, field)) is not None
    )
    if len(values) < minimum_samples:
        raise BaselineValidationError(
            f"insufficient_{field}_samples:{len(values)}<{minimum_samples}"
        )
    return values


def _non_negative(value: float | None, field: str) -> float | None:
    if value is not None and value < 0:
        raise BaselineValidationError(f"{field}_must_be_non_negative")
    return value


def _bounded(value: float | None, field: str) -> float | None:
    if value is not None and not 0 <= value <= 1:
        raise BaselineValidationError(f"{field}_must_be_between_0_and_1")
    return value


def _quantile(values: tuple[float, ...], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise BaselineValidationError("cannot_quantile_empty_values")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


__all__ = [
    "BaselineSample",
    "BaselineValidationError",
    "FrozenSLOBaseline",
    "freeze_baseline",
]

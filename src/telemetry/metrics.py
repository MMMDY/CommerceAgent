"""Bounded in-process counters and histograms for operational diagnostics."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from threading import Lock


class Metrics:
    _MAX_SAMPLES = 4096

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._samples: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        if not name or amount < 0:
            raise ValueError("invalid metric increment")
        with self._lock:
            self._counts[name] += amount

    def observe(self, name: str, value: float) -> None:
        """Record a bounded observation without accepting high-cardinality labels."""

        if not name or not isinstance(value, int | float) or not isfinite(value) or value < 0:
            raise ValueError("invalid metric observation")
        with self._lock:
            samples = self._samples[name]
            samples.append(float(value))
            if len(samples) > self._MAX_SAMPLES:
                del samples[: len(samples) - self._MAX_SAMPLES]

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            histograms = {
                name: _distribution(values) for name, values in self._samples.items()
            }
            return {"counters": dict(self._counts), "histograms": histograms}


def _distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50": round(_percentile(ordered, 0.50), 4),
        "p95": round(_percentile(ordered, 0.95), 4),
        "p99": round(_percentile(ordered, 0.99), 4),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


__all__ = ["Metrics"]

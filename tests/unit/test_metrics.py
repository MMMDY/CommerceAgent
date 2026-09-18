from src.telemetry.metrics import Metrics


def test_metrics_snapshot_contains_bounded_percentiles() -> None:
    metrics = Metrics()
    metrics.increment("requests")
    for value in (10, 20, 30, 40, 50):
        metrics.observe("request_latency_ms", value)

    snapshot = metrics.snapshot()

    assert snapshot["counters"] == {"requests": 1}
    histogram = snapshot["histograms"]["request_latency_ms"]
    assert histogram["count"] == 5
    assert histogram["p50"] == 30.0
    assert histogram["p95"] == 48.0
    assert histogram["p99"] == 49.6


def test_metrics_rejects_invalid_observations() -> None:
    metrics = Metrics()
    try:
        metrics.observe("latency", -1)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("negative observations must be rejected")

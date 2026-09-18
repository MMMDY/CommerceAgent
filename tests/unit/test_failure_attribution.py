from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import SecretStr

from src.config import Settings
from src.evolution.contracts import FailureCaseView
from src.evolution.failure_attribution import FailureAttributionService


class FakeRuns:
    def __init__(self, events: list[Any] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error

    def replay_events(self, **_kwargs: object) -> list[Any]:
        if self.error:
            raise self.error
        return self.events


class FakeFailures:
    def __init__(self) -> None:
        self.failure = FailureCaseView(
            failure_id=uuid4(),
            tenant_id="tenant-a",
            signal="run_failed",
            severity="p1",
            source="runtime",
            run_id=uuid4(),
            trace_refs=(),
            status="open",
            cluster_key="cluster",
            summary_redacted="run_failed: MODEL_TIMEOUT",
            source_count=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.recorded: list[dict[str, object]] = []
        self.attributions: list[dict[str, object]] = []

    def record_signal(self, **kwargs: object) -> FailureCaseView:
        self.recorded.append(kwargs)
        return self.failure

    def add_attribution(self, **kwargs: object) -> UUID:
        self.attributions.append(kwargs)
        return uuid4()

    def get(self, **_kwargs: object) -> FailureCaseView:
        return self.failure


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_failure_attribution=True,
        judge_model="judge-v1",
        judge_api_base="http://judge.invalid",
        judge_api_key=SecretStr("test-key"),
    )


def test_missing_event_evidence_disables_llm_and_keeps_deterministic_projection() -> None:
    failures = FakeFailures()
    called = False

    def analyzer_factory(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("LLM attribution must be disabled without event evidence")

    service = FailureAttributionService(
        None,  # type: ignore[arg-type]
        settings=_settings(),
        failures=failures,  # type: ignore[arg-type]
        runs=FakeRuns(error=RuntimeError("event store unavailable")),  # type: ignore[arg-type]
        analyzer_factory=analyzer_factory,  # type: ignore[arg-type]
    )

    service.record_run_signal(
        tenant_id="tenant-a",
        run_id=failures.failure.run_id,  # type: ignore[arg-type]
        signal="run_failed",
        source="runtime",
        reason="MODEL_TIMEOUT card 4111 1111 1111 1111",
    )

    assert called is False
    assert failures.attributions[0]["llm_category"] is None
    assert failures.attributions[0]["review_status"] == "pending"
    assert failures.attributions[0]["evidence_refs"] == ()
    assert "4111" not in str(failures.recorded[0]["summary_redacted"])
    assert str(failures.recorded[0]["cluster_key"]).startswith("cluster:")


def test_llm_attribution_is_evidence_bounded_and_stays_pending() -> None:
    class Event:
        event_id = uuid4()

        class EventPayload:
            event_type = type("EventType", (), {"value": "model_request_failed"})

        event = EventPayload()

    failures = FakeFailures()
    event_id = str(Event.event_id)
    runs = FakeRuns(events=[Event()])

    def analyzer_factory(*_args: object, **_kwargs: object) -> object:
        from src.evolution.attribution_llm import AttributionAnalyzer, AttributionModelConfig

        return AttributionAnalyzer(
            AttributionModelConfig("judge-v1", "http://judge.invalid", "secret"),
            request=lambda _input: {
                "category": "model_error",
                "confidence": 0.9,
                "evidence_event_ids": [event_id],
                "rationale": "事件证据支持模型失败",
            },
        )

    service = FailureAttributionService(
        None,  # type: ignore[arg-type]
        settings=_settings(),
        failures=failures,  # type: ignore[arg-type]
        runs=runs,  # type: ignore[arg-type]
        analyzer_factory=analyzer_factory,  # type: ignore[arg-type]
    )
    service.record_run_signal(
        tenant_id="tenant-a",
        run_id=failures.failure.run_id,  # type: ignore[arg-type]
        signal="run_failed",
        source="runtime",
        reason="MODEL_TIMEOUT",
    )

    attribution = failures.attributions[0]
    assert attribution["llm_category"] == "model_error"
    assert attribution["evidence_refs"] == (event_id,)
    assert attribution["review_status"] == "pending"


def test_evaluation_failure_and_cost_signals_share_the_redacted_pending_pool() -> None:
    failures = FakeFailures()
    service = FailureAttributionService(
        None,  # type: ignore[arg-type]
        settings=_settings(),
        failures=failures,  # type: ignore[arg-type]
        runs=FakeRuns(error=RuntimeError("no runtime events for eval case")),  # type: ignore[arg-type]
    )

    results = service.record_evaluation_outcome(
        tenant_id="tenant-a",
        eval_run_id=uuid4(),
        case_id="case_safe_001",
        track="long_tail_response_v1",
        eval_failed=True,
        cost_microusd=101,
        cost_budget_microusd=100,
        failure_reason="JUDGE_FAIL",
    )

    assert len(results) == 2
    assert {item["signal"] for item in failures.recorded} == {"eval_fail", "cost_exceeded"}
    assert all(
        "case_safe_001" not in str(item["summary_redacted"])
        for item in failures.recorded
    )
    assert all(item["review_status"] == "pending" for item in failures.attributions)

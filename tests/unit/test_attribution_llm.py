from src.evolution.attribution_llm import AttributionAnalyzer, AttributionModelConfig


def test_attribution_requires_real_event_evidence() -> None:
    analyzer = AttributionAnalyzer(
        AttributionModelConfig("judge", "http://unused", "secret"),
        request=lambda _input: {
            "category": "intent_error",
            "confidence": 0.95,
            "evidence_event_ids": ["event-1"],
            "rationale": "分类事件支持该结论",
        },
    )

    result = analyzer.analyze(
        signal="low_confidence",
        summary_redacted="分类未确定",
        deterministic_category="intent_error",
        event_facts=[{"event_id": "event-1", "type": "model_request_failed"}],
        allowed_event_ids={"event-1"},
    )

    assert result is not None
    assert result.category.value == "intent_error"


def test_attribution_with_unknown_evidence_fails_closed() -> None:
    analyzer = AttributionAnalyzer(
        AttributionModelConfig("judge", "http://unused", "secret"),
        request=lambda _input: {
            "category": "model_error",
            "confidence": 0.99,
            "evidence_event_ids": ["not-real"],
        },
    )

    assert analyzer.analyze(
        signal="run_failed",
        summary_redacted="模型失败",
        deterministic_category="model_error",
        event_facts=[{"event_id": "event-1", "type": "model_request_failed"}],
        allowed_event_ids={"event-1"},
    ) is None


def test_attribution_without_event_evidence_fails_closed() -> None:
    analyzer = AttributionAnalyzer(
        AttributionModelConfig("judge", "http://unused", "secret"),
        request=lambda _input: {
            "category": "model_error",
            "confidence": 0.99,
            "evidence_event_ids": [],
        },
    )

    assert analyzer.analyze(
        signal="run_failed",
        summary_redacted="模型失败",
        deterministic_category="model_error",
        event_facts=[{"event_id": "event-1", "type": "model_request_failed"}],
        allowed_event_ids={"event-1"},
    ) is None

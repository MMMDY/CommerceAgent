from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.protocols import DomainEvent, EventType
from src.repositories.run_observability import ModelInvocationView, ToolInvocationView
from src.repositories.runs import ReplayedRunEvent, RunSnapshot
from src.telemetry.run_insight import build_run_visualization


def test_visualization_exposes_aggregates_without_prompt_payloads() -> None:
    accepted = datetime(2026, 9, 17, 10, tzinfo=UTC)
    run_id = uuid4()
    model = ModelInvocationView(
        model_call_id=uuid4(),
        step_id="answer",
        purpose="agent",
        provider="provider",
        model="model",
        status="succeeded",
        error_code=None,
        latency_ms=120,
        first_token_latency_ms=None,
        input_tokens=100,
        output_tokens=20,
        cached_input_tokens=10,
        reasoning_tokens=None,
        total_tokens=120,
        usage_estimated=False,
        provider_usage_version="openai-compatible-v1",
        pricing_version_id=uuid4(),
        cost_microusd=9,
        started_at=accepted + timedelta(milliseconds=20),
        finished_at=accepted + timedelta(milliseconds=140),
    )
    tool = ToolInvocationView(
        tool_call_id=uuid4(),
        step_id="lookup",
        tool_name="get_order_status",
        tool_version="1.0",
        risk_level="read_only",
        status="succeeded",
        attempt_no=1,
        error_code=None,
        latency_ms=30,
        started_at=accepted + timedelta(milliseconds=150),
        finished_at=accepted + timedelta(milliseconds=180),
    )
    result = build_run_visualization(
        snapshot=RunSnapshot(
            run_id=run_id,
            tenant_id="tenant",
            status="completed",
            current_step="terminal",
            row_version=3,
            last_checkpoint_seq=4,
            accepted_at=accepted,
            dispatch_started_at=accepted + timedelta(milliseconds=10),
            terminal_at=accepted + timedelta(milliseconds=190),
            response_published_at=accepted + timedelta(milliseconds=200),
            total_cost_microusd=9,
        ),
        events=(),
        model_invocations=(model,),
        tool_invocations=(tool,),
        checkpoint={
            "state": {
                "intent": "track_order",
                "route": "order_readonly",
                "prompt": "must never be exposed",
                "chain_of_thought": "must never be exposed",
            }
        },
        evidence_count=1,
    )

    assert result["decision"] == {
        "intent": "track_order",
        "route": "order_readonly",
    }
    assert result["summary"] == {
        "event_count": 0,
        "evidence_count": 1,
        "model_invocation_count": 1,
        "tool_invocation_count": 1,
        "total_tokens": 120,
        "token_usage_complete": True,
        "usage_estimated_count": 0,
        "total_cost_microusd": 9,
        "pricing_complete": True,
    }
    assert {item["id"]: item["duration_ms"] for item in result["timings"]} == {
        "queue": 10,
        "routing": None,
        "model": 120,
        "rag": None,
        "tool": 30,
        "publish": 10,
        "e2e": 200,
    }
    rendered = str(result)
    assert "must never be exposed" not in rendered
    assert "chain_of_thought" not in rendered


def test_internal_event_path_is_whitelisted() -> None:
    now = datetime.now(UTC)
    run_id = uuid4()
    event = ReplayedRunEvent(
        event_id=uuid4(),
        run_id=run_id,
        sequence=1,
        step_id="route",
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=now,
        payload_hash="sha256:" + "a" * 64,
        event=DomainEvent(
            event_type=EventType.SAFETY_ROUTED,
            payload={
                "risk_level": "high",
                "reason_code": "sensitive_request",
                "prompt": "hidden",
                "tool_args": {"secret": "hidden"},
            },
        ),
    )
    result = build_run_visualization(
        snapshot=RunSnapshot(
            run_id=run_id,
            tenant_id="tenant",
            status="failed",
            current_step="terminal",
            row_version=1,
            last_checkpoint_seq=1,
        ),
        events=(event,),
        model_invocations=(),
        tool_invocations=(),
        checkpoint=None,
        evidence_count=0,
        include_event_path=True,
    )
    path = result["event_path"]
    assert path[0]["payload"] == {
        "risk_level": "high",
        "reason_code": "sensitive_request",
    }
    assert "prompt" not in str(path)
    assert "tool_args" not in str(path)


def test_visualization_marks_partial_usage_and_pricing_unknown() -> None:
    now = datetime.now(UTC)
    invocation = ModelInvocationView(
        model_call_id=uuid4(),
        step_id="route",
        purpose="intent_classification",
        provider="provider",
        model="model",
        status="succeeded",
        error_code=None,
        latency_ms=None,
        first_token_latency_ms=None,
        input_tokens=None,
        output_tokens=None,
        cached_input_tokens=None,
        reasoning_tokens=None,
        total_tokens=None,
        usage_estimated=False,
        provider_usage_version=None,
        pricing_version_id=None,
        cost_microusd=None,
        started_at=now,
        finished_at=now,
    )
    result = build_run_visualization(
        snapshot=RunSnapshot(
            run_id=uuid4(),
            tenant_id="tenant",
            status="routing",
            current_step="route",
            row_version=1,
            last_checkpoint_seq=1,
        ),
        events=(),
        model_invocations=(invocation,),
        tool_invocations=(),
        checkpoint=None,
        evidence_count=0,
    )

    assert result["summary"]["total_tokens"] is None
    assert result["summary"]["token_usage_complete"] is False
    assert result["summary"]["total_cost_microusd"] is None
    assert result["summary"]["pricing_complete"] is False


def test_visualization_separates_rag_latency_from_business_tools() -> None:
    started = datetime(2026, 9, 17, 10, tzinfo=UTC)
    rag = ToolInvocationView(
        tool_call_id=uuid4(),
        step_id="retrieve",
        tool_name="retrieve_knowledge",
        tool_version="1.0",
        risk_level="read_only",
        status="succeeded",
        attempt_no=1,
        error_code=None,
        latency_ms=45,
        started_at=started,
        finished_at=started + timedelta(milliseconds=45),
    )
    business = ToolInvocationView(
        tool_call_id=uuid4(),
        step_id="lookup",
        tool_name="get_order_status",
        tool_version="1.0",
        risk_level="read_only",
        status="succeeded",
        attempt_no=1,
        error_code=None,
        latency_ms=25,
        started_at=started + timedelta(milliseconds=50),
        finished_at=started + timedelta(milliseconds=75),
    )
    result = build_run_visualization(
        snapshot=RunSnapshot(
            run_id=uuid4(),
            tenant_id="tenant",
            status="completed",
            current_step="terminal",
            row_version=1,
            last_checkpoint_seq=1,
        ),
        events=(),
        model_invocations=(),
        tool_invocations=(rag, business),
        checkpoint=None,
        evidence_count=1,
    )

    timings = {item["id"]: item for item in result["timings"]}
    assert timings["rag"] == {
        "id": "rag",
        "label": "RAG 检索",
        "duration_ms": 45,
        "state": "measured",
    }
    assert timings["tool"]["duration_ms"] == 25

"""Build browser-safe Run visualization data from durable metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.repositories.run_observability import ModelInvocationView, ToolInvocationView
from src.repositories.runs import ReplayedRunEvent, RunSnapshot

_TERMINAL = {"completed", "failed", "cancelled", "expired"}
_EXECUTING = {"running_readonly", "running_workflow", "committing", "verifying"}
_WAITING = {"waiting_user", "waiting_confirmation", "waiting_human"}


def build_run_visualization(
    *,
    snapshot: RunSnapshot,
    events: tuple[ReplayedRunEvent, ...],
    model_invocations: tuple[ModelInvocationView, ...],
    tool_invocations: tuple[ToolInvocationView, ...],
    checkpoint: dict[str, Any] | None,
    evidence_count: int,
    include_event_path: bool = False,
) -> dict[str, object]:
    """Return only decisions and aggregate evidence safe for an owner UI."""

    status = snapshot.status
    published = snapshot.response_published_at is not None
    has_execution = bool(model_invocations or tool_invocations)
    state = checkpoint.get("state", {}) if isinstance(checkpoint, dict) else {}
    safe_state = state if isinstance(state, dict) else {}
    request_risk_level = safe_state.get("request_risk_level")
    safety_state = "warning" if request_risk_level in {"high", "medium"} else "completed"
    nodes = [
        _node("intake", "受理请求", "消息与 Run 已持久化", "completed"),
        _node("safety", "Safety Router", "先于业务编排检查内容与账户风险", safety_state),
        _node(
            "routing",
            "意图、风险与路由",
            "识别请求边界并选择受控路径",
            (
                "active"
                if status == "routing"
                else ("pending" if status == "created" else "completed")
            ),
        ),
        _node(
            "execution",
            "Agent 编排执行",
            "模型、RAG 与工具按策略协作",
            _execution_state(status=status, has_execution=has_execution),
        ),
        _node(
            "guard",
            "安全校验与确认",
            "校验结果，必要时等待用户或真人",
            _guard_state(status),
        ),
        _node(
            "publish",
            "发布回复",
            "向用户发布可见结果并保留审计证据",
            "completed"
            if published
            else (
                "failed"
                if status == "failed"
                else ("active" if status in _TERMINAL else "pending")
            ),
        ),
    ]
    decision = {
        name: value
        for name in (
            "intent",
            "route",
            "risk_hint",
            "request_domain",
            "request_risk_level",
            "response_policy",
        )
        if isinstance((value := safe_state.get(name)), str) and len(value) <= 128
    }
    routing_event = next(
        (
            item.event.payload
            for item in reversed(events)
            if item.event.event_type.value == "model_request_succeeded"
            and item.event.payload.get("purpose") in {"routing", "intent_classification"}
        ),
        {},
    )
    confidence = routing_event.get("confidence")
    if isinstance(confidence, int | float) and 0 <= confidence <= 1:
        decision["classification_confidence"] = f"{confidence:.4f}"
    for source_key in ("domain_confidence", "risk_confidence"):
        value = routing_event.get(source_key)
        if isinstance(value, int | float) and 0 <= value <= 1:
            decision[source_key] = f"{value:.4f}"
    calibration_version = routing_event.get("confidence_calibration_version")
    if isinstance(calibration_version, str) and len(calibration_version) <= 64:
        decision["confidence_calibration_version"] = calibration_version
    alternatives = routing_event.get("alternative_count")
    if isinstance(alternatives, int) and 0 <= alternatives <= 32:
        decision["alternative_count"] = str(alternatives)
    invocations = [_model_view(item) for item in model_invocations]
    tools = [_tool_view(item) for item in tool_invocations]
    costs = [item.cost_microusd for item in model_invocations]
    total_tokens = [item.total_tokens for item in model_invocations]
    result: dict[str, object] = {
        "schema_version": "1.0",
        "run_id": str(snapshot.run_id),
        "status": status,
        "current_step": snapshot.current_step,
        "nodes": nodes,
        "edges": [
            {"source": nodes[index]["id"], "target": nodes[index + 1]["id"]}
            for index in range(len(nodes) - 1)
        ],
        "decision": decision,
        "summary": {
            "event_count": len(events),
            "evidence_count": evidence_count,
            "model_invocation_count": len(model_invocations),
            "tool_invocation_count": len(tool_invocations),
            "total_tokens": _complete_sum(total_tokens),
            "token_usage_complete": bool(total_tokens)
            and all(value is not None for value in total_tokens),
            "usage_estimated_count": sum(item.usage_estimated for item in model_invocations),
            "total_cost_microusd": _complete_sum(costs),
            "pricing_complete": bool(costs) and all(value is not None for value in costs),
        },
        "timings": _timings(snapshot, model_invocations, tool_invocations, evidence_count),
        "model_invocations": invocations,
        "tool_invocations": tools,
    }
    if include_event_path:
        result["event_path"] = [_safe_event(item) for item in events]
    return result


def _node(node_id: str, label: str, description: str, state: str) -> dict[str, str]:
    return {"id": node_id, "label": label, "description": description, "state": state}


_SAFE_EVENT_KEYS = frozenset(
    {
        "purpose",
        "outcome",
        "status",
        "error_code",
        "reason_code",
        "disposition",
        "risk_level",
        "domain",
        "category",
        "intent",
        "request_domain",
        "request_risk_level",
        "response_policy",
        "execution_mode",
        "current_router",
        "shadow_router",
        "current_outcome",
        "current_reason_code",
        "current_intent",
        "current_response_policy",
        "shadow_outcome",
        "shadow_reason_code",
        "shadow_intent",
        "shadow_response_policy",
        "different",
        "shadow_is_observation_only",
        "alternative_count",
        "confidence",
        "domain_confidence",
        "risk_confidence",
        "confidence_calibration_version",
        "tool",
        "attempt_no",
        "character_count",
        "retryable",
        "fallback_used",
        "mode",
        "selected_version",
        "traffic_percent",
        "bucket",
    }
)


def _safe_event(item: Any) -> dict[str, object]:
    payload = item.event.payload
    return {
        "event_id": item.event_id,
        "sequence": item.sequence,
        "event_type": item.event.event_type.value,
        "step_id": item.step_id,
        "occurred_at": item.occurred_at.isoformat(),
        "payload": {key: payload[key] for key in _SAFE_EVENT_KEYS if key in payload},
    }


def _execution_state(*, status: str, has_execution: bool) -> str:
    if status in _EXECUTING:
        return "active"
    if status in _WAITING or status in _TERMINAL:
        return "completed" if has_execution else "not_applicable"
    return "pending"


def _guard_state(status: str) -> str:
    if status in _WAITING:
        return "warning"
    if status in {"committing", "verifying"}:
        return "active"
    if status == "failed":
        return "failed"
    if status in _TERMINAL:
        return "completed"
    return "pending"


def _model_view(item: ModelInvocationView) -> dict[str, object]:
    return {
        "id": str(item.model_call_id),
        "step_id": item.step_id,
        "purpose": item.purpose,
        "provider": item.provider,
        "model": item.model,
        "status": item.status,
        "error_code": item.error_code,
        "latency_ms": item.latency_ms,
        "first_token_latency_ms": item.first_token_latency_ms,
        "token_usage": {
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "cached_input_tokens": item.cached_input_tokens,
            "reasoning_tokens": item.reasoning_tokens,
            "total_tokens": item.total_tokens,
            "estimated": item.usage_estimated,
        },
        "cost_microusd": item.cost_microusd,
        "priced": item.pricing_version_id is not None and item.cost_microusd is not None,
        "started_at": item.started_at.isoformat(),
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


def _tool_view(item: ToolInvocationView) -> dict[str, object]:
    return {
        "id": str(item.tool_call_id),
        "step_id": item.step_id,
        "tool_name": item.tool_name,
        "tool_version": item.tool_version,
        "risk_level": item.risk_level,
        "status": item.status,
        "attempt_no": item.attempt_no,
        "error_code": item.error_code,
        "latency_ms": item.latency_ms,
        "started_at": item.started_at.isoformat(),
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


def _timings(
    snapshot: RunSnapshot,
    models: tuple[ModelInvocationView, ...],
    tools: tuple[ToolInvocationView, ...],
    evidence_count: int,
) -> list[dict[str, object]]:
    routing = tuple(item for item in models if item.purpose == "intent_classification")
    agent = tuple(item for item in models if item.purpose != "intent_classification")
    rag_tools = tuple(
        item for item in tools if item.tool_name in {"retrieve_knowledge", "search_knowledge"}
    )
    business_tools = tuple(item for item in tools if item not in rag_tools)
    return [
        _timing("queue", "排队", _elapsed(snapshot.accepted_at, snapshot.dispatch_started_at)),
        _timing("routing", "意图与路由", _duration_sum(routing), applicable=bool(routing)),
        _timing("model", "Agent 模型", _duration_sum(agent), applicable=bool(agent)),
        _timing(
            "rag",
            "RAG 检索",
            _duration_sum(rag_tools),
            applicable=bool(rag_tools) or evidence_count > 0,
        ),
        _timing(
            "tool",
            "工具调用",
            _duration_sum(business_tools),
            applicable=bool(business_tools),
        ),
        _timing(
            "publish",
            "结果发布",
            _elapsed(snapshot.terminal_at, snapshot.response_published_at),
        ),
        _timing(
            "e2e",
            "端到端",
            _elapsed(snapshot.accepted_at, snapshot.response_published_at),
        ),
    ]


def _timing(
    stage_id: str, label: str, duration_ms: int | None, *, applicable: bool = True
) -> dict[str, object]:
    state = (
        "measured"
        if duration_ms is not None
        else ("unavailable" if applicable else "not_applicable")
    )
    return {"id": stage_id, "label": label, "duration_ms": duration_ms, "state": state}


def _elapsed(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    return round((end - start).total_seconds() * 1000)


def _duration_sum(
    items: tuple[ModelInvocationView, ...] | tuple[ToolInvocationView, ...],
) -> int | None:
    if not items or any(item.latency_ms is None for item in items):
        return None
    return sum(item.latency_ms or 0 for item in items)


def _complete_sum(values: list[int | None]) -> int | None:
    if not values or any(value is None for value in values):
        return None
    return sum(value or 0 for value in values)


__all__ = ["build_run_visualization"]

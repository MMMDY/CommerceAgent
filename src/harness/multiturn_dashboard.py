"""Browser-safe projections for persisted multi-turn evaluation reports.

Multi-turn reports are generated outside the primary evaluation report tree.
This module keeps the API contract allowlisted so evaluator-only scenario
fields cannot accidentally become browser-visible when the report schema
grows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.telemetry.trace import _sanitize

_SUMMARY_FIELDS = (
    "schema_version",
    "dataset_id",
    "dataset_version",
    "runtime",
    "status",
    "release_gate",
    "gate_status",
    "scenario_count",
    "dialogue_count",
    "completed_count",
    "incomplete_count",
    "evaluation_noise_count",
    "intent_coverage",
    "agenda_progress",
    "exposed_intent_accuracy",
    "task_success_rate",
    "termination_reasons",
    "feedback_categories",
    "judge",
    "human_review",
)

_HUMAN_REVIEW_FIELDS = (
    "status",
    "selected_count",
    "unique_selected_count",
    "reviewed_count",
    "minimum_count",
    "missing_label_count",
    "extra_label_count",
    "gate_pass",
)


def build_multiturn_summary(report: Mapping[str, Any], *, report_id: str) -> dict[str, Any]:
    """Return aggregate fields only; no scenario or evaluator-only data."""

    result: dict[str, Any] = {"report_id": report_id}
    for field in _SUMMARY_FIELDS:
        if field in report:
            result[field] = _sanitize(report[field])
    return result


def build_multiturn_review_status(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project only aggregate human-review state for browser consumers."""

    source: Mapping[str, Any] = value or {}
    nested = source.get("stats")
    if isinstance(nested, Mapping):
        source = nested
    result = {
        field: _sanitize(source[field])
        for field in _HUMAN_REVIEW_FIELDS
        if field in source
    }
    if "status" not in result:
        result["status"] = "incomplete"
    result.setdefault("reviewed_count", 0)
    return result


def build_multiturn_dashboard(report: Mapping[str, Any], *, report_id: str) -> dict[str, Any]:
    """Return summary plus compact per-dialogue rows for dashboard lists."""

    summary = build_multiturn_summary(report, report_id=report_id)
    rows = report.get("reports")
    summary["dialogues"] = [
        _dialogue_projection(item)
        for item in rows
        if isinstance(item, Mapping)
    ] if isinstance(rows, list) else []
    summary["dto"] = "multiturn_dashboard"
    summary["schema_version"] = "1.0"
    return summary


def build_multiturn_report_detail(report: Mapping[str, Any], *, report_id: str) -> dict[str, Any]:
    """Return a safe report detail projection without raw hidden fields."""

    result = build_multiturn_summary(report, report_id=report_id)
    rows = report.get("reports")
    result["reports"] = [
        _dialogue_projection(item)
        for item in rows
        if isinstance(item, Mapping)
    ] if isinstance(rows, list) else []
    result["dto"] = "multiturn_report"
    result["schema_version"] = "1.0"
    return result


def build_multiturn_trace(
    report: Mapping[str, Any], *, report_id: str, scenario_id: str
) -> dict[str, Any]:
    """Return one dialogue with safe turn-level observability."""

    rows = report.get("reports")
    if not isinstance(rows, list):
        raise KeyError(scenario_id)
    matches = [
        item for item in rows
        if isinstance(item, Mapping) and item.get("scenario_id") == scenario_id
    ]
    if not matches:
        raise KeyError(scenario_id)
    if len(matches) > 1:
        raise ValueError("scenario_id is not unique")
    item = matches[0]
    result = _dialogue_projection(item, include_turns=True)
    result["report_id"] = report_id
    result["dto"] = "multiturn_trace"
    result["schema_version"] = "1.0"
    return result


def _dialogue_projection(item: Mapping[str, Any], *, include_turns: bool = False) -> dict[str, Any]:
    fields = (
        "scenario_id",
        "dialogue_id",
        "status",
        "termination_reason",
        "intent_coverage",
        "agenda_progress",
        "exposed_intent_accuracy",
        "task_success",
        "evaluation_noise",
    )
    result = {field: _sanitize(item[field]) for field in fields if field in item}

    metadata = item.get("metadata")
    if isinstance(metadata, Mapping):
        result["intent_summary"] = {
            key: _sanitize(metadata[key])
            for key in ("key_intents", "raised_key_intents", "addressed_key_intents")
            if key in metadata
        }

    feedback = item.get("feedback")
    result["feedback"] = [
        _feedback_projection(signal)
        for signal in feedback
        if isinstance(signal, Mapping)
    ] if isinstance(feedback, list) else []
    judge = item.get("judge")
    if isinstance(judge, Mapping):
        result["judge"] = {
            field: _sanitize(judge[field])
            for field in (
                "rubric_id",
                "dimension_scores",
                "weighted_score",
                "judge_pass",
                "error_code",
                "model",
                "input_hash",
                "latency_ms",
                "usage_tokens",
                "evidence",
            )
            if field in judge
        }
    if include_turns:
        turns = item.get("turns")
        result["turns"] = [
            _turn_projection(turn)
            for turn in turns
            if isinstance(turn, Mapping)
        ] if isinstance(turns, list) else []
    return result


def _feedback_projection(signal: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "signal_id", "scenario_id", "category", "code", "severity", "turn_ids",
        "evidence", "reusable",
    )
    return {field: _sanitize(signal[field]) for field in fields if field in signal}


def _turn_projection(turn: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        field: _sanitize(turn[field])
        for field in (
            "scenario_id",
            "dialogue_id",
            "turn_id",
            "raised_intents",
            "addressed_intents",
            "intent_states",
            "transitions",
            "verifier_pass",
            "version_hash",
        )
        if field in turn
    }
    action = turn.get("user_action")
    if isinstance(action, Mapping):
        result["user_action"] = {
            field: _sanitize(action[field])
            for field in (
                "action",
                "message",
                "target_intents",
                "revealed_facts",
                "emotion",
                "should_continue",
                "reason_code",
            )
            if field in action
        }
    trace = turn.get("agent_trace")
    if isinstance(trace, Mapping):
        # Keep response observability while excluding arguments, slots and
        # memory payloads that may contain evaluator or customer data.
        result["agent_trace"] = {
            field: _sanitize(trace[field])
            for field in (
                "run_id",
                "route",
                "intent",
                "next_action",
                "tools_called",
                "evidence_ids",
                "response",
                "status",
                "turn_id",
                "dialogue_id",
                "retrieved_evidence_ids",
                "workflow_steps",
                "termination_reason",
            )
            if field in trace
        }
    return result


__all__ = [
    "build_multiturn_dashboard",
    "build_multiturn_report_detail",
    "build_multiturn_review_status",
    "build_multiturn_summary",
    "build_multiturn_trace",
]

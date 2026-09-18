"""Deterministic attribution taxonomy; it has precedence over LLM guesses."""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Iterable

from src.evolution.contracts import AttributionCategory


def deterministic_category(*, reason_code: str | None, event_types: Iterable[str] = ()) -> AttributionCategory:
    reason = (reason_code or "").upper()
    events = {str(item) for item in event_types}
    if "SAFETY" in reason or "INJECTION" in reason or "CREDENTIAL" in reason:
        return AttributionCategory.SAFETY_ERROR
    if "TOOL" in reason or "MUTATION" in reason or any(item.startswith("tool_") for item in events):
        return AttributionCategory.TOOL_ERROR
    if "RETRIEV" in reason or "EVIDENCE" in reason:
        return AttributionCategory.RETRIEVAL_ERROR
    if "CONFIDENCE" in reason or "INTENT" in reason or "ROUTE" in reason:
        return AttributionCategory.INTENT_ERROR
    if "POLICY" in reason or "CONFIRM" in reason:
        return AttributionCategory.POLICY_ERROR
    if "MODEL" in reason or "CLASSIFIER" in reason:
        return AttributionCategory.MODEL_ERROR
    if "RESPONSE" in reason or "PUBLISH" in reason or any(
        item in {"assistant_response", "terminal_response_publish_failed"}
        for item in events
    ):
        return AttributionCategory.RESPONSE_ERROR
    return AttributionCategory.UNKNOWN


__all__ = ["deterministic_category"]

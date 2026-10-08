"""Registered evaluation tracks shared by loaders, hard gates, and reports."""

from __future__ import annotations

TRACK_CATALOG: dict[str, dict[str, str]] = {
    "intent_route": {"rubric": "none", "dataset_kind": "core"},
    "tool_workflow": {"rubric": "workflow_response_v1", "dataset_kind": "core"},
    "rag_grounding": {"rubric": "rag_grounding_v1", "dataset_kind": "core"},
    "scripted_clarification": {"rubric": "clarification_v1", "dataset_kind": "core"},
    "guardrail_handoff": {"rubric": "guardrail_response_v1", "dataset_kind": "core"},
    "long_tail_response_v1": {"rubric": "long_tail_response_v1", "dataset_kind": "synthetic"},
    "safety_response_v2": {"rubric": "safety_response_v2", "dataset_kind": "synthetic"},
    "multiturn_feedback_v1": {"rubric": "multiturn_response_v1", "dataset_kind": "multiturn"},
    "catalog_selection_v1": {"rubric": "catalog_selection_v1", "dataset_kind": "catalog"},
    "catalog_response_v1": {"rubric": "catalog_response_v1", "dataset_kind": "catalog"},
    "catalog_safety_v1": {"rubric": "catalog_safety_v1", "dataset_kind": "catalog"},
    "catalog_multiturn_v1": {"rubric": "catalog_multiturn_v1", "dataset_kind": "catalog"},
}


def is_registered_track(track: str) -> bool:
    return track in TRACK_CATALOG


__all__ = ["TRACK_CATALOG", "is_registered_track"]

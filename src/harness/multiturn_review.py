"""Fail-closed human review queue for multi-turn trajectory sampling."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator

from src.protocols import Contract
from src.telemetry.trace import _sanitize


class HumanTrajectoryReview(Contract):
    """Independent human label for one sampled dialogue."""

    scenario_id: str
    source: Literal["human_review"]
    reviewer_id: str
    reviewed_at: datetime
    rubric_version: str
    gold_response_leakage: Literal["none", "suspected", "confirmed"]
    semantic_fidelity: Literal["pass", "fail", "unclear"]
    simulator_action_validity: Literal["pass", "fail", "unclear"]
    notes: str
    label_hash: str

    @field_validator("reviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return value

    @field_validator("reviewer_id", "rubric_version", "notes", "label_hash")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review metadata must not be empty")
        return value


def load_multiturn_review_labels(path: Path | str) -> dict[str, HumanTrajectoryReview]:
    """Load non-empty, unique human labels from JSONL."""

    labels: dict[str, HumanTrajectoryReview] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        label = HumanTrajectoryReview.model_validate_json(line)
        if label.scenario_id in labels:
            raise ValueError(f"duplicate trajectory review: {label.scenario_id}")
        labels[label.scenario_id] = label
    if not labels:
        raise ValueError("trajectory review label set is empty")
    return labels


def reviewed_multiturn_stats(
    rows: Iterable[Mapping[str, Any]],
    labels: Mapping[str, HumanTrajectoryReview | Mapping[str, Any]],
    *,
    minimum_count: int = 20,
) -> dict[str, Any]:
    """Aggregate human labels without inferring missing labels."""

    if minimum_count < 1:
        raise ValueError("minimum_count must be positive")
    selected = [row for row in rows if isinstance(row, Mapping) and row.get("scenario_id")]
    selected_ids = [str(row["scenario_id"]) for row in selected]
    duplicate_ids = sorted(
        scenario_id
        for scenario_id in set(selected_ids)
        if selected_ids.count(scenario_id) > 1
    )
    normalized: dict[str, HumanTrajectoryReview] = {}
    for scenario_id, value in labels.items():
        label = (
            value
            if isinstance(value, HumanTrajectoryReview)
            else HumanTrajectoryReview.model_validate(value)
        )
        if label.scenario_id != str(scenario_id):
            raise ValueError("trajectory review key must match scenario_id")
        normalized[str(scenario_id)] = label
    selected_id_set = set(selected_ids)
    missing = sorted(selected_id_set - normalized.keys())
    extra = sorted(normalized.keys() - selected_id_set)
    reviewed = [
        normalized[scenario_id] for scenario_id in selected_id_set if scenario_id in normalized
    ]
    complete = (
        len(selected) >= minimum_count
        and len(selected_id_set) >= minimum_count
        and not duplicate_ids
        and not missing
        and not extra
    )
    return {
        "status": "complete" if complete else "incomplete",
        "selected_count": len(selected),
        "unique_selected_count": len(selected_id_set),
        "reviewed_count": len(reviewed),
        "minimum_count": minimum_count,
        "duplicate_scenario_ids": duplicate_ids,
        "missing_label_count": len(missing),
        "missing_scenario_ids": missing,
        "extra_label_count": len(extra),
        "extra_scenario_ids": extra,
        "gold_response_leakage_count": sum(
            label.gold_response_leakage != "none" for label in reviewed
        )
        if complete
        else None,
        "semantic_fidelity_pass_count": sum(
            label.semantic_fidelity == "pass" for label in reviewed
        )
        if complete
        else None,
        "simulator_action_validity_pass_count": sum(
            label.simulator_action_validity == "pass" for label in reviewed
        )
        if complete
        else None,
        "gate_pass": (
            all(
                label.gold_response_leakage == "none"
                and label.semantic_fidelity == "pass"
                and label.simulator_action_validity == "pass"
                for label in reviewed
            )
            if complete
            else None
        ),
    }


def build_multiturn_review_queue(
    report: Mapping[str, Any],
    *,
    sample_size: int = 20,
) -> dict[str, Any]:
    """Build a stable queue that contains dialogue evidence but no gold fields."""

    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    rows = report.get("reports")
    if not isinstance(rows, list):
        raise ValueError("multi-turn report has no reports list")
    candidates = [row for row in rows if isinstance(row, Mapping)]
    selected = _stable_review_sample(candidates, sample_size=sample_size)
    if len(selected) < sample_size:
        raise ValueError("multi-turn report has fewer reviewable rows than sample_size")
    scenario_ids = [str(row.get("scenario_id", "")) for row in selected]
    if any(not scenario_id for scenario_id in scenario_ids):
        raise ValueError("review rows must have scenario_id")
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("review rows must have unique scenario_id")
    if any(not _projected_turns(row) for row in selected):
        raise ValueError("review rows must have observable turns")
    return {
        "schema_version": "multiturn-human-review-queue-v1",
        "status": "pending_human_review",
        "source_report": {
            "dataset_id": report.get("dataset_id"),
            "dataset_version": report.get("dataset_version"),
            "runtime": report.get("runtime"),
        },
        "requested_count": sample_size,
        "reviewed_count": 0,
        "sampling": {
            "strategy": "stable_family_round_robin_v1",
            "candidate_count": len(candidates),
        },
        "review_contract": {
            "gold_response_leakage": ["none", "suspected", "confirmed"],
            "semantic_fidelity": ["pass", "fail", "unclear"],
            "simulator_action_validity": ["pass", "fail", "unclear"],
            "notes_required": True,
        },
        "items": [_trajectory_projection(row) for row in selected],
    }


def _trajectory_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only observable dialogue content for the reviewer."""

    projected_turns = _projected_turns(row)
    return {
        "scenario_id": _sanitize(row.get("scenario_id")),
        "dialogue_id": _sanitize(row.get("dialogue_id")),
        "turns": projected_turns,
        "review": {
            "status": "pending",
            "gold_response_leakage": None,
            "semantic_fidelity": None,
            "simulator_action_validity": None,
            "notes": None,
        },
    }


def _stable_review_sample(
    rows: list[Mapping[str, Any]], *, sample_size: int
) -> list[Mapping[str, Any]]:
    """Sample scenario families round-robin while preserving report order.

    A queue should expose behavior and risk diversity without depending on
    random state. Within a family, multi-turn rows are preferred because they
    provide more observable simulator/agent interaction for the reviewer.
    """

    families: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for index, row in enumerate(rows):
        if not _projected_turns(row):
            continue
        family = _scenario_family(row.get("scenario_id"))
        families.setdefault(family, []).append((index, row))
    for values in families.values():
        values.sort(
            key=lambda item: (
                -len(_projected_turns(item[1])),
                item[0],
            )
        )
    selected: list[Mapping[str, Any]] = []
    family_names = sorted(families)
    offset = 0
    while len(selected) < sample_size and family_names:
        progressed = False
        for family in family_names:
            values = families[family]
            if offset < len(values):
                selected.append(values[offset][1])
                progressed = True
                if len(selected) == sample_size:
                    break
        if not progressed:
            break
        offset += 1
    return selected


def _projected_turns(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    turns = row.get("turns")
    if not isinstance(turns, list):
        return []
    projected: list[dict[str, Any]] = []
    for turn in turns:
        if not isinstance(turn, Mapping):
            continue
        action = turn.get("user_action")
        trace = turn.get("agent_trace")
        if not isinstance(action, Mapping) or not isinstance(trace, Mapping):
            continue
        projected.append(
            {
                "turn_id": _sanitize(turn.get("turn_id")),
                "user_message": _sanitize(action.get("message")),
                "agent_response": _sanitize(trace.get("response")),
                "agent_route": _sanitize(trace.get("route")),
                "agent_next_action": _sanitize(trace.get("next_action")),
                "tools_called": _sanitize(trace.get("tools_called", [])),
                "agent_status": _sanitize(trace.get("status")),
            }
        )
    return projected


def _scenario_family(value: Any) -> str:
    scenario_id = str(value or "")
    parts = scenario_id.split("_")
    while parts and (parts[-1] == "v1" or re.fullmatch(r"\d+", parts[-1])):
        parts.pop()
    return "_".join(parts) or scenario_id


__all__ = [
    "HumanTrajectoryReview",
    "build_multiturn_review_queue",
    "load_multiturn_review_labels",
    "reviewed_multiturn_stats",
]

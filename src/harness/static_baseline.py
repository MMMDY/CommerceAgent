"""Compare static evaluation reports without conflating Judge-dependent fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_TRACKS = (
    "intent_route",
    "scripted_clarification",
    "tool_workflow",
    "rag_grounding",
    "guardrail_handoff",
)


def compare_static_baselines(
    historical_report: Mapping[str, Any],
    current_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare stable hard-evaluation shape and isolate Judge-dependent results.

    A Judge-off deterministic rerun can establish dataset, repetition, track,
    and hard-pass invariants.  It cannot establish that Judge-derived Final
    Pass values are unchanged, so that comparison is explicitly non-comparable.
    """

    historical = _canonical_projection(historical_report)
    current = _canonical_projection(current_report)
    checks = {
        "dataset_hash": historical["dataset_hash"] == current["dataset_hash"],
        "dataset_shape": (
            historical["selected_cases"] == current["selected_cases"]
            and historical["completed_cases"] == current["completed_cases"]
            and historical["repetitions"] == current["repetitions"]
            and historical["attempts"] == current["attempts"]
        ),
        "track_shape": historical["tracks"] == current["tracks"],
        "hard_pass": (
            historical["hard_passed_cases"] == current["hard_passed_cases"]
            and historical["hard_passed_cases"] == historical["selected_cases"]
            and current["hard_passed_cases"] == current["selected_cases"]
        ),
    }
    judge_input_comparison = _compare_judge_inputs(historical_report, current_report)
    judge_comparable = (
        historical["judge_signature"] == current["judge_signature"]
        and historical_report.get("status") == "completed"
        and current_report.get("status") == "completed"
        and judge_input_comparison["status"] == "complete"
    )
    final_pass_comparison = (
        {
            "historical": historical["final_pass"],
            "current": current["final_pass"],
            "all_repetitions_pass_rate_historical": historical[
                "all_repetitions_pass_rate"
            ],
            "all_repetitions_pass_rate_current": current[
                "all_repetitions_pass_rate"
            ],
            "status": "comparable",
        }
        if judge_comparable
        else {
            "status": "N/A",
            "reason": _judge_not_comparable_reason(
                historical_report,
                current_report,
                historical,
                current,
                judge_input_comparison,
            ),
        }
    )
    hard_runtime_complete = all(checks.values())
    reports_complete = (
        historical_report.get("status") == "completed"
        and current_report.get("status") == "completed"
    )
    judge_signature_match = historical["judge_signature"] == current["judge_signature"]
    return {
        "schema_version": "static-baseline-comparison-v1",
        "status": "invariant_preserved" if hard_runtime_complete else "regression",
        "evidence_status": (
            "complete" if hard_runtime_complete and judge_comparable else "incomplete"
        ),
        "comparison_scope": (
            "hard_runtime_and_judge" if judge_comparable else "hard_runtime_only"
        ),
        "report_status": {
            "historical": historical_report.get("status"),
            "current": current_report.get("status"),
            "both_completed": reports_complete,
        },
        "historical": historical,
        "current": current,
        "checks": checks,
        "judge_dependent": {
            "status": "comparable" if judge_comparable else "not_comparable",
            "reports_complete": reports_complete,
            "signature_match": judge_signature_match,
            "historical_judge": historical["judge"],
            "current_judge": current["judge"],
            "historical_signature": historical["judge_signature"],
            "current_signature": current["judge_signature"],
            "input_hashes": judge_input_comparison,
            "final_pass": final_pass_comparison,
        },
        "confidence_note": (
            "Hard/runtime invariants are directly comparable; Judge-dependent "
            "Final Pass requires the same Judge mode, model, prompt, and rubric."
        ),
    }


def _compare_judge_inputs(
    historical_report: Mapping[str, Any], current_report: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare the stable Judge input identity for each judged attempt."""

    historical = _judge_input_rows(historical_report)
    current = _judge_input_rows(current_report)
    shared = set(historical) & set(current)
    matching = sum(historical[key] == current[key] for key in shared)
    if len(shared) != len(historical) or len(shared) != len(current):
        status = "incomplete"
    elif matching != len(shared):
        status = "mismatch"
    else:
        status = "complete"
    return {
        "status": status,
        "historical_count": len(historical),
        "current_count": len(current),
        "shared_count": len(shared),
        "matching_count": matching,
    }


def _judge_input_rows(report: Mapping[str, Any]) -> dict[tuple[str, int], str]:
    rows = report.get("results")
    if not isinstance(rows, list):
        return {}
    counts: dict[str, int] = {}
    result: dict[tuple[str, int], str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        input_hash = row.get("judge_input_hash")
        case_id = row.get("case_id")
        if not isinstance(input_hash, str) or not isinstance(case_id, str):
            continue
        occurrence = counts.get(case_id, 0)
        counts[case_id] = occurrence + 1
        result[(case_id, occurrence)] = input_hash
    return result


def _judge_not_comparable_reason(
    historical_report: Mapping[str, Any],
    current_report: Mapping[str, Any],
    historical: Mapping[str, Any],
    current: Mapping[str, Any],
    input_comparison: Mapping[str, Any],
) -> str:
    if (
        historical_report.get("status") != "completed"
        or current_report.get("status") != "completed"
    ):
        return "one or both reports are incomplete"
    if historical["judge_signature"] != current["judge_signature"]:
        return "historical and current Judge signatures differ"
    if input_comparison.get("status") != "complete":
        return "Judge input hash coverage or identity differs"
    return "Judge-dependent result is unavailable"


def _canonical_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    tracks = report.get("tracks")
    normalized_tracks: dict[str, dict[str, Any]] = {}
    if isinstance(tracks, Mapping):
        for name in _TRACKS:
            value = tracks.get(name)
            if isinstance(value, Mapping):
                normalized_tracks[name] = {
                    "selected": value.get("selected"),
                    "attempts": value.get("attempts"),
                    "hard_pass": value.get("hard_pass"),
                }
            else:
                normalized_tracks[name] = {
                    "selected": None,
                    "attempts": None,
                    "hard_pass": None,
                }
    return {
        "dataset_hash": report.get("dataset_hash"),
        "selected_cases": report.get("selected_cases"),
        "completed_cases": report.get("completed_cases"),
        "repetitions": report.get("repetitions"),
        "attempts": report.get("attempts"),
        "hard_passed_cases": report.get("hard_passed_cases"),
        "judge": report.get("judge"),
        "judge_signature": {
            "mode": report.get("judge"),
            "config_hash": report.get("judge_config_hash"),
            "models": report.get("judge_models", []),
            "prompt_hash": report.get("judge_prompt_hash"),
            "rubric_hash": report.get("rubric_hash"),
            "rubric_version": report.get("rubric_version"),
        },
        "final_pass": report.get("passed_cases"),
        "all_repetitions_pass_rate": report.get("all_repetitions_pass_rate"),
        "tracks": normalized_tracks,
    }


__all__ = ["compare_static_baselines"]

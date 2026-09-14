from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harness.runner import main


def test_runner_filters_case_and_emits_deterministic_hard_eval_json(capsys: object) -> None:
    result = main(
        (
            "--dataset",
            "evals/commerce_bench_zh/cases.jsonl",
            "--track",
            "intent_route",
            "--case-id",
            "intent_add_product_001",
            "--judge",
            "off",
            "--timeout",
            "1",
        )
    )
    assert result == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    report = json.loads(output)
    assert report["judge"] == "off"
    assert report["selected_cases"] == report["completed_cases"] == 1
    assert report["runtime"] == "deterministic_fixture"
    assert len(report["runtime_fixture_hash"]) == 64
    assert report["results"][0]["case_id"] == "intent_add_product_001"
    assert report["results"][0]["hard_pass"] is True


def test_runner_rejects_a_nonpositive_timeout() -> None:
    try:
        main(("--dataset", str(Path("evals/commerce_bench_zh/cases.jsonl")), "--timeout", "0"))
    except SystemExit as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected argument rejection")


def test_runner_isolates_a_case_missing_from_runtime_fixture(
    capsys: object, tmp_path: Path
) -> None:
    full_fixture = Path("evals/commerce_bench_zh/cases.runtime.jsonl")
    fixture = tmp_path / "partial.runtime.jsonl"
    fixture.write_text(full_fixture.read_text(encoding="utf-8").splitlines()[0] + "\n")
    result = main(
        (
            "--dataset",
            "evals/commerce_bench_zh/cases.jsonl",
            "--case-id",
            "intent_add_product_002",
            "--runtime-fixture",
            str(fixture),
            "--judge",
            "off",
        )
    )
    assert result == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    report = json.loads(output)
    assert report["completed_cases"] == 1
    assert report["results"][0]["runtime_error"] == "runtime_execution_failed"
    assert report["results"][0]["hard_pass"] is False


def test_runner_emits_deterministic_full_intent_track_report(capsys: object) -> None:
    args = (
        "--dataset",
        "evals/commerce_bench_zh/cases.jsonl",
        "--track",
        "intent_route",
        "--judge",
        "off",
        "--timeout",
        "1",
    )

    assert main(args) == 0
    first = capsys.readouterr().out  # type: ignore[attr-defined]
    assert main(args) == 0
    second = capsys.readouterr().out  # type: ignore[attr-defined]

    assert first == second
    report = json.loads(first)
    assert report["selected_cases"] == report["completed_cases"] == 150
    assert report["passed_cases"] == 150
    assert report["failed_cases"] == 0
    assert all(item["runtime_error"] is None for item in report["results"])


def test_runner_accepts_an_explicit_runtime_fixture(capsys: object) -> None:
    result = main(
        (
            "--dataset",
            "evals/commerce_bench_zh/cases.jsonl",
            "--case-id",
            "intent_add_product_001",
            "--runtime-fixture",
            "evals/commerce_bench_zh/cases.runtime.jsonl",
        )
    )
    assert result == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["passed_cases"] == 1


@pytest.mark.parametrize(
    ("track", "case_id"),
    (
        ("tool_workflow", "workflow_track_order_001"),
        ("rag_grounding", "rag_fact_001_1"),
        ("scripted_clarification", "clarify_shopping_001"),
        ("guardrail_handoff", "guardrail_cross_account_001"),
    ),
)
def test_runner_drives_a_real_agent_loop_fixture_for_each_non_intent_track(
    capsys: object, track: str, case_id: str
) -> None:
    assert main(
        (
            "--dataset",
            "evals/commerce_bench_zh/cases.jsonl",
            "--track",
            track,
            "--case-id",
            case_id,
            "--judge",
            "off",
            "--timeout",
            "1",
        )
    ) == 0
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["selected_cases"] == report["completed_cases"] == report["passed_cases"] == 1
    assert report["failed_cases"] == 0
    assert report["results"][0]["runtime_error"] is None

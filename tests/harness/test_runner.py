from __future__ import annotations

import json
from pathlib import Path

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


def test_runner_isolates_a_case_missing_from_runtime_fixture(capsys: object) -> None:
    result = main(
        (
            "--dataset",
            "evals/commerce_bench_zh/cases.jsonl",
            "--case-id",
            "intent_add_product_002",
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

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
    assert report["results"][0]["case_id"] == "intent_add_product_001"
    assert report["results"][0]["hard_pass"] is False


def test_runner_rejects_a_nonpositive_timeout() -> None:
    try:
        main(("--dataset", str(Path("evals/commerce_bench_zh/cases.jsonl")), "--timeout", "0"))
    except SystemExit as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected argument rejection")

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harness.deterministic_runtime import (
    DeterministicRuntimeFactory,
    RuntimeFixtureError,
    RuntimeFixtureLoader,
)
from src.harness.loader import CaseLoader
from src.harness.run_driver import RunDriver
from src.harness.schema import ExpectedOutcome

DATASET = Path("evals/commerce_bench_zh/cases.jsonl")
RUNTIME_FIXTURE = Path("evals/commerce_bench_zh/cases.runtime.jsonl")


def test_runtime_fixture_drives_agent_loop_without_observing_gold() -> None:
    case = CaseLoader(DATASET).load(case_id="intent_add_product_001")[0]
    factory = DeterministicRuntimeFactory(RuntimeFixtureLoader(RUNTIME_FIXTURE).load())

    passing = RunDriver(runtime=factory).run_case(case=case, timeout_seconds=1)
    changed_gold = case.model_copy(
        update={"expected": ExpectedOutcome(values={"intent": "wrong", "route": "wrong"})}
    )
    failing = RunDriver(runtime=factory).run_case(case=changed_gold, timeout_seconds=1)

    assert passing.trace == failing.trace
    assert passing.hard_eval.passed
    assert not failing.hard_eval.passed
    assert passing.trace.status == "complete"
    assert passing.trace.next_action == "respond"


def test_runtime_fixture_schema_rejects_embedded_expected_gold(tmp_path: Path) -> None:
    raw = json.loads(RUNTIME_FIXTURE.read_text(encoding="utf-8"))
    raw["expected"] = {"intent": "add_product"}
    fixture = tmp_path / "runtime.jsonl"
    fixture.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeFixtureError, match="invalid runtime fixture"):
        RuntimeFixtureLoader(fixture).load()


def test_runtime_fixture_validation_is_enforced_by_real_agent_loop(tmp_path: Path) -> None:
    raw = json.loads(RUNTIME_FIXTURE.read_text(encoding="utf-8"))
    raw["decision"]["route"] = "untrusted_route"
    fixture = tmp_path / "runtime.jsonl"
    fixture.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")
    factory = DeterministicRuntimeFactory(RuntimeFixtureLoader(fixture).load())
    case = CaseLoader(DATASET).load(case_id="intent_add_product_001")[0]

    result = RunDriver(runtime=factory).run_case(case=case, timeout_seconds=1)

    assert result.trace.status == "fail"
    assert result.trace.route == "untrusted_route"
    assert not result.hard_eval.passed

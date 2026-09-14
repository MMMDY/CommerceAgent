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


def _first_runtime_fixture() -> dict[str, object]:
    return json.loads(RUNTIME_FIXTURE.read_text(encoding="utf-8").splitlines()[0])


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


def test_runtime_fixture_covers_and_drives_the_complete_intent_route_track() -> None:
    cases = CaseLoader(DATASET).load(track="intent_route")
    fixtures = RuntimeFixtureLoader(RUNTIME_FIXTURE).load()
    factory = DeterministicRuntimeFactory(fixtures)

    assert len(cases) == 150
    assert {case.id for case in cases}.issubset({fixture.case_id for fixture in fixtures})

    results = [RunDriver(runtime=factory).run_case(case=case, timeout_seconds=1) for case in cases]
    assert all(result.runtime_error is None for result in results)
    assert all(result.trace.status == "complete" for result in results)
    assert all(result.hard_eval.passed for result in results)


def test_runtime_fixture_schema_rejects_embedded_expected_gold(tmp_path: Path) -> None:
    raw = _first_runtime_fixture()
    raw["expected"] = {"intent": "add_product"}
    fixture = tmp_path / "runtime.jsonl"
    fixture.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeFixtureError, match="invalid runtime fixture"):
        RuntimeFixtureLoader(fixture).load()


def test_runtime_fixture_validation_is_enforced_by_real_agent_loop(tmp_path: Path) -> None:
    raw = _first_runtime_fixture()
    raw["decision"]["route"] = "untrusted_route"
    fixture = tmp_path / "runtime.jsonl"
    fixture.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")
    factory = DeterministicRuntimeFactory(RuntimeFixtureLoader(fixture).load())
    case = CaseLoader(DATASET).load(case_id="intent_add_product_001")[0]

    result = RunDriver(runtime=factory).run_case(case=case, timeout_seconds=1)

    assert result.trace.status == "fail"
    assert result.trace.route == "untrusted_route"
    assert not result.hard_eval.passed


def test_runtime_factory_supplies_all_published_rag_grounding_fixtures() -> None:
    """The 50 grounding cases execute through the same AgentLoop boundary."""
    cases = CaseLoader(DATASET).load(track="rag_grounding")
    factory = DeterministicRuntimeFactory(RuntimeFixtureLoader(RUNTIME_FIXTURE).load())

    results = [RunDriver(runtime=factory).run_case(case=case, timeout_seconds=1) for case in cases]

    assert len(results) == 50
    assert all(result.runtime_error is None for result in results)
    assert all(result.hard_eval.passed for result in results)

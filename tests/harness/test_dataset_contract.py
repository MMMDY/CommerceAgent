"""Semantic completeness contracts for all 300 frozen evaluation cases."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _cases() -> list[dict[str, object]]:
    return [json.loads(line) for line in (ROOT / "evals/commerce_bench_zh/cases.jsonl").read_text().splitlines()]


def test_all_cases_have_exactly_one_track_and_complete_contract() -> None:
    cases = _cases()
    assert len(cases) == 300
    assert len({case["id"] for case in cases}) == 300
    assert Counter(case["task_type"] for case in cases) == {
        "intent_route": 150, "tool_workflow": 60, "rag_grounding": 50,
        "scripted_clarification": 20, "guardrail_handoff": 20,
    }


def test_intent_and_workflow_cases_have_actionable_goldens() -> None:
    for case in _cases():
        expected = case["expected"]
        if case["task_type"] == "intent_route":
            assert {"intent", "route", "tool"} <= expected.keys()
        if case["task_type"] == "tool_workflow":
            assert {"intent", "route", "next_action", "tool", "required_slots", "confirmation_required"} <= expected.keys()
            assert isinstance(expected["required_slots"], list)


def test_rag_clarification_and_guardrail_goldens_have_verifiable_evidence() -> None:
    knowledge_ids = {json.loads(line)["id"] for line in (ROOT / "evals/commerce_bench_zh/knowledge.jsonl").read_text().splitlines()}
    for case in _cases():
        expected = case["expected"]
        if case["task_type"] == "rag_grounding":
            assert set(expected["evidence_ids"]) <= knowledge_ids
            assert expected["required_facts"]
        if case["task_type"] == "scripted_clarification":
            assert expected["next_action"] == "ask_clarification"
            assert expected["required_slots"] and expected["acceptable_keywords"]
        if case["task_type"] == "guardrail_handoff":
            assert expected["outcome"] and expected["reason_code"]

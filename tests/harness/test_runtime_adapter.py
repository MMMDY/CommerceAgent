from __future__ import annotations

from src.harness.runtime import FixtureManager, RuntimeTrace, TraceAdapter
from src.harness.schema import EvalCase


def _case() -> EvalCase:
    return EvalCase.from_raw(
        {
            "id": "intent_xxx",
            "schema_version": "1.0",
            "locale": "zh-CN",
            "task_type": "intent_route",
            "messages": [{"role": "user", "content": "x", "schema_version": "1.0"}],
            "context": {"nested": {"value": 1}},
            "expected": {"intent": "x", "route": "r", "tool": None},
            "forbidden_tools": [],
            "tags": ["static"],
            "source": {},
        }
    )


def test_fixture_manager_deep_copies_case_context() -> None:
    fixture = FixtureManager().create(_case())
    fixture["nested"]["value"] = 2
    assert _case().context["nested"]["value"] == 1


def test_trace_adapter_outputs_normalized_trace() -> None:
    trace = TraceAdapter().normalize(
        case_id="intent_xxx", trace=RuntimeTrace("r", "x", "respond", {}, (), (), "ok", "complete")
    )
    assert trace.case_id == "intent_xxx"
    assert trace.status == "complete"

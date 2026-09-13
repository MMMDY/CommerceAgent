from src.harness.hard_eval import evaluate
from src.harness.schema import EvalCase, NormalizedTrace


def _case(task_type: str, expected: dict, forbidden_tools: list[str] | None = None) -> EvalCase:
    return EvalCase.from_raw(
        {
            "schema_version": "1.0",
            "id": "case_001",
            "locale": "zh-CN",
            "task_type": task_type,
            "messages": [{"schema_version": "1.0", "role": "user", "content": "test"}],
            "context": {},
            "expected": expected,
            "forbidden_tools": forbidden_tools or [],
            "tags": ["test"],
            "source": {"dataset": "test"},
        }
    )


def test_intent_route_golden_pass_and_fail() -> None:
    case = _case("intent_route", {"intent": "status", "route": "orders"})
    assert evaluate(
        case,
        NormalizedTrace(case_id="case_001", intent="status", route="orders", status="complete"),
    ).passed
    assert not evaluate(
        case, NormalizedTrace(case_id="case_001", intent="wrong", route="orders", status="complete")
    ).passed


def test_workflow_forbidden_tool_is_hard_failure() -> None:
    case = _case(
        "tool_workflow",
        {
            "intent": "status",
            "route": "orders",
            "next_action": "call_tool",
            "tool": "get_order",
            "args": {"order_id": "O1"},
        },
        ["refund"],
    )
    trace = NormalizedTrace(
        case_id="case_001",
        intent="status",
        route="orders",
        next_action="call_tool",
        tools_called=("get_order", "refund"),
        args={"order_id": "O1"},
        status="complete",
    )
    assert "forbidden_tool_called" in evaluate(case, trace).hard_fail_reasons

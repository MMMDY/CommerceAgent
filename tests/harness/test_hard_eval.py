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


def test_workflow_checks_confirmation_and_exact_arguments() -> None:
    case = _case(
        "tool_workflow",
        {
            "intent": "cancel",
            "route": "orders",
            "next_action": "call_tool",
            "tool": "prepare_cancel_order",
            "args": {"order_id": "O1"},
            "confirmation_required": True,
        },
    )
    trace = NormalizedTrace(
        case_id="case_001",
        intent="cancel",
        route="orders",
        next_action="call_tool",
        tools_called=("prepare_cancel_order",),
        args={"order_id": "O1", "actor_id": "spoofed"},
        status="complete",
    )
    result = evaluate(case, trace)
    assert not result.passed
    assert "required_args_mismatch" in result.hard_fail_reasons
    assert "confirmation" not in result.hard_fail_reasons


def test_workflow_rejects_order_not_owned_by_authenticated_user() -> None:
    case = EvalCase.from_raw(
        {
            "schema_version": "1.0",
            "id": "case_001",
            "locale": "zh-CN",
            "task_type": "tool_workflow",
            "messages": [{"schema_version": "1.0", "role": "user", "content": "test"}],
            "context": {
                "authenticated_user_id": "USER-001",
                "orders": [{"order_id": "O1", "owner_id": "USER-002"}],
            },
            "expected": {
                "intent": "status",
                "route": "orders",
                "next_action": "call_tool",
                "tool": "get_order",
                "args": {"order_id": "O1"},
                "confirmation_required": False,
            },
            "forbidden_tools": [],
            "tags": ["test"],
            "source": {"dataset": "test"},
        }
    )
    trace = NormalizedTrace(
        case_id="case_001",
        intent="status",
        route="orders",
        next_action="call_tool",
        tools_called=("get_order",),
        args={"order_id": "O1"},
        status="complete",
    )
    result = evaluate(case, trace)
    assert not result.passed
    assert "resource_owner_mismatch" in result.hard_fail_reasons

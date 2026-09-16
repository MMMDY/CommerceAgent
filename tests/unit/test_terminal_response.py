from uuid import uuid4

from src.orchestration.terminal_response import _fallback_content, stable_reason_code
from src.protocols import RunContext, RunStatus


def context_with_order() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="demo-tenant",
        actor_id="demo-user-001",
        status=RunStatus.FAILED,
        state={
            "tool_data_by_name": {
                "get_order_status": {
                    "order": {
                        "order_id": "ORD-DEMO-001",
                        "status": "shipped",
                        "tracking_id": "TRK-DEMO-001",
                        "eta": "2026-09-16",
                    }
                }
            }
        },
    )


def test_decision_rejection_uses_only_trusted_partial_tool_result() -> None:
    content = _fallback_content(
        context=context_with_order(),
        status=RunStatus.FAILED,
        reason_code="DECISION_REJECTED",
        retryable=True,
        result_summary=None,
    )

    assert "ORD-DEMO-001" in content
    assert "TRK-DEMO-001" in content
    assert "未通过安全检查" in content
    assert "未执行退款" not in content


def test_decision_rejection_without_evidence_does_not_invent_business_result() -> None:
    context = context_with_order().model_copy(update={"state": {}})
    content = _fallback_content(
        context=context,
        status=RunStatus.FAILED,
        reason_code="DECISION_REJECTED",
        retryable=True,
        result_summary=None,
    )

    assert "ORD-DEMO-001" not in content
    assert "下一步决策未通过安全检查" in content


def test_reason_codes_are_stable_for_public_run_snapshots() -> None:
    assert stable_reason_code("decision_rejected") == "DECISION_REJECTED"
    assert stable_reason_code("model_unavailable") == "MODEL_GATEWAY_ERROR"
    assert stable_reason_code("custom_failure") == "CUSTOM_FAILURE"

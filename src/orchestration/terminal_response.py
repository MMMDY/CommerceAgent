"""Idempotent, user-visible responses for every paused or terminal Run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.protocols import EventType, RunContext, RunStatus
from src.repositories.messages import MessageRecord, MessageRepository
from src.repositories.runs import RunRepository


@dataclass(frozen=True, slots=True)
class TerminalResponse:
    content: str
    reason_code: str | None
    retryable: bool
    message: MessageRecord
    published: bool


def publish_terminal_response(
    *,
    context: RunContext,
    messages: MessageRepository,
    runs: RunRepository,
    status: RunStatus | None = None,
    reason_code: str | None = None,
    preferred_content: str | None = None,
    retryable: bool | None = None,
    result_summary: dict[str, Any] | None = None,
) -> TerminalResponse:
    """Publish at most one safe assistant response for a Run.

    The message repository serializes the per-conversation check, so calling
    this from recovery and the original worker is safe. Existing assistant
    messages are returned without creating another response.
    """
    effective_status = status or context.status
    stable_reason = stable_reason_code(reason_code or _state_reason(context))
    can_retry = retryable if retryable is not None else effective_status in {
        RunStatus.FAILED, RunStatus.EXPIRED
    }
    content = (preferred_content or "").strip() or _fallback_content(
        context=context,
        status=effective_status,
        reason_code=stable_reason,
        retryable=can_retry,
        result_summary=result_summary,
    )
    terminal_status = effective_status in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.EXPIRED,
    }
    if terminal_status:
        message = messages.append_assistant_once_for_run(
            conversation_id=context.conversation_id,
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            run_id=context.run_id,
            content=content,
        )
    else:
        # Waiting prompts are stage responses, not the final response. A
        # later user answer or human review must be able to add another one.
        message = messages.append_assistant(
            conversation_id=context.conversation_id,
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            content=content,
            run_id=context.run_id,
        )
    published = message.created
    if terminal_status and stable_reason is not None:
        runs.set_terminal_reason(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            reason=stable_reason,
        )
    if published:
        try:
            runs.mark_response_published(
                run_id=context.run_id,
                tenant_id=context.tenant_id,
            )
        except Exception:
            # The response itself is already durable; timing metadata must not
            # turn a successful user-visible publication into a failed run.
            pass
        runs.append_event(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            event_type=EventType.ASSISTANT_RESPONSE,
            step_id="response",
            payload={"status": "published", "character_count": len(content)},
        )
        if terminal_status:
            runs.append_event(
                run_id=context.run_id,
                tenant_id=context.tenant_id,
                event_type=EventType.TERMINAL_RESPONSE_PUBLISHED,
                step_id="terminal",
                payload={
                    "status": effective_status.value,
                    "reason_code": stable_reason,
                    "retryable": can_retry,
                    "fallback_used": preferred_content is None or not preferred_content.strip(),
                },
            )
    return TerminalResponse(
        content=message.content_redacted,
        reason_code=stable_reason,
        retryable=can_retry,
        message=message,
        published=published,
    )


def _state_reason(context: RunContext) -> str | None:
    value = context.state.get("last_step_reason") or context.state.get("mutation_error")
    return str(value) if value else None


def stable_reason_code(reason: str | None) -> str | None:
    if not reason:
        return None
    mapping = {
        "decision_rejected": "DECISION_REJECTED",
        "model_unavailable": "MODEL_GATEWAY_ERROR",
        "tool_execution_failed": "TOOL_EXECUTION_FAILED",
        "max_steps_exceeded": "MAX_STEPS_EXCEEDED",
        "token_budget_exhausted": "TOKEN_BUDGET_EXHAUSTED",
        "deadline_exceeded": "DEADLINE_EXCEEDED",
        "cancelled_by_user": "CANCELLED_BY_USER",
        "cancelled": "CANCELLED_BY_USER",
        "readonly_loop_no_progress": "NO_PROGRESS",
    }
    return mapping.get(reason, reason.upper()[:128])


def _fallback_content(
    *,
    context: RunContext,
    status: RunStatus,
    reason_code: str | None,
    retryable: bool,
    result_summary: dict[str, Any] | None,
) -> str:
    del result_summary  # Reserved for future redacted domain-specific summaries.
    if status is RunStatus.COMPLETED:
        return "本次请求已完成。"
    if status is RunStatus.WAITING_USER:
        return "还需要你补充必要信息后才能继续当前流程。"
    if status is RunStatus.WAITING_CONFIRMATION:
        return "请在确认卡片中选择是否继续该操作。"
    if status is RunStatus.WAITING_HUMAN:
        return "自动处理已暂停，当前请求已转人工审核，请查看人工处理窗口。"
    if status is RunStatus.CANCELLED:
        return "本次请求已取消，未继续执行后续操作。"
    if status is RunStatus.EXPIRED:
        return "本次请求已超时失效，未能确认最终结果，请重新发起。"
    if status is RunStatus.FAILED:
        if reason_code == "DECISION_REJECTED":
            partial = _order_partial_result(context)
            if partial:
                return (
                    f"{partial}下一步处理未通过安全检查，流程未继续执行。"
                    + ("你可以点击重试，或转人工继续处理。" if retryable else "")
                )
            return "Agent 的下一步决策未通过安全检查，本次请求未完成。你可以点击重试或转人工处理。"
        reason_text = {
            "MODEL_GATEWAY_ERROR": "模型服务暂时不可用",
            "TOOL_EXECUTION_FAILED": "工具调用未完成",
            "UPSTREAM_UNAVAILABLE": "上游服务暂时不可用",
            "UNEXPECTED_EXECUTION_ERROR": "系统处理异常",
        }.get(reason_code or "", "本次处理未完成")
        return f"{reason_text}，本次请求未完成。" + ("你可以点击重试。" if retryable else "")
    return "当前请求已停止，请查看执行日志获取状态。"
    

def _order_partial_result(context: RunContext) -> str:
    by_tool = context.state.get("tool_data_by_name")
    if not isinstance(by_tool, dict):
        return ""
    status_data = by_tool.get("get_order_status")
    if not isinstance(status_data, dict):
        return ""
    order = status_data.get("order")
    if not isinstance(order, dict):
        return ""
    order_id = order.get("order_id")
    status = order.get("status")
    eta = order.get("eta")
    tracking = order.get("tracking_id")
    if (
        not isinstance(order_id, str)
        or not order_id
        or not isinstance(status, str)
        or not status
    ):
        return ""
    details = f"订单 {order_id} 已查询到：当前{_status_label(status)}"
    if isinstance(eta, str) and eta:
        details += f"，预计 {eta}"
    if isinstance(tracking, str) and tracking:
        details += f"，物流单号为 {tracking}"
    return details + "。"


def _status_label(status: str) -> str:
    return {
        "shipped": "已发货",
        "delivered": "已送达",
        "processing": "处理中",
        "paid": "已支付",
    }.get(status, status)

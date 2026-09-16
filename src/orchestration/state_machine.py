"""Explicit legal run-state transitions for the runtime."""

from __future__ import annotations

from src.protocols import RunStatus


class StateTransitionError(ValueError):
    """A runtime attempted an illegal lifecycle transition."""


TERMINAL = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.EXPIRED}
)
TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.ROUTING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.ROUTING: frozenset(
        {
            RunStatus.RUNNING_READONLY,
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.WAITING_HUMAN,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING_READONLY: frozenset(
        {
            RunStatus.RUNNING_READONLY,
            RunStatus.WAITING_USER,
            RunStatus.WAITING_HUMAN,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.RUNNING_WORKFLOW: frozenset(
        {
            RunStatus.WAITING_USER,
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMMITTING,
            RunStatus.WAITING_HUMAN,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.WAITING_USER: frozenset(
        {
            RunStatus.RUNNING_READONLY,
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.WAITING_HUMAN,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.WAITING_CONFIRMATION: frozenset(
        {
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMMITTING,
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.COMMITTING: frozenset(
        {RunStatus.VERIFYING, RunStatus.WAITING_HUMAN, RunStatus.FAILED}
    ),
    RunStatus.VERIFYING: frozenset(
        {RunStatus.COMPLETED, RunStatus.WAITING_HUMAN, RunStatus.FAILED}
    ),
    RunStatus.WAITING_HUMAN: frozenset(
        {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
}

STATUS_LABELS: dict[RunStatus, str] = {
    RunStatus.CREATED: "已受理",
    RunStatus.ROUTING: "正在判断请求",
    RunStatus.RUNNING_READONLY: "正在执行查询",
    RunStatus.RUNNING_WORKFLOW: "正在执行流程",
    RunStatus.WAITING_USER: "等待补充信息",
    RunStatus.WAITING_CONFIRMATION: "等待确认",
    RunStatus.COMMITTING: "正在提交变更",
    RunStatus.VERIFYING: "正在核验结果",
    RunStatus.WAITING_HUMAN: "等待人工处理",
    RunStatus.COMPLETED: "已完成",
    RunStatus.FAILED: "执行失败",
    RunStatus.CANCELLED: "已取消",
    RunStatus.EXPIRED: "已过期",
}

STATUS_DESCRIPTIONS: dict[RunStatus, str] = {
    RunStatus.CREATED: "消息已保存，准备启动 Agent",
    RunStatus.ROUTING: "识别意图并选择执行路径",
    RunStatus.RUNNING_READONLY: "Agent 正在读取订单、商品或政策信息",
    RunStatus.RUNNING_WORKFLOW: "Agent 正在执行已授权业务流程",
    RunStatus.WAITING_USER: "需要用户补充必要信息",
    RunStatus.WAITING_CONFIRMATION: "需要用户确认即将执行的操作",
    RunStatus.COMMITTING: "正在提交业务变更",
    RunStatus.VERIFYING: "正在读取并核对变更结果",
    RunStatus.WAITING_HUMAN: "已转交人工，等待人工处理",
    RunStatus.COMPLETED: "Agent 已完成本次处理",
    RunStatus.FAILED: "本次处理未能完成",
    RunStatus.CANCELLED: "本次处理已取消",
    RunStatus.EXPIRED: "本次处理超过有效期限",
}


def state_machine_definition() -> list[dict[str, object]]:
    """Return the safe, backend-owned state-machine definition for the UI."""

    return [
        {
            "status": status.value,
            "label": STATUS_LABELS[status],
            "description": STATUS_DESCRIPTIONS[status],
            "terminal": status in TERMINAL,
            "transitions": [target.value for target in TRANSITIONS.get(status, ())],
        }
        for status in RunStatus
    ]


def allowed_actions(status: RunStatus) -> tuple[str, ...]:
    """Expose UI capabilities from the same source as lifecycle semantics."""

    if status in {
        RunStatus.CREATED,
        RunStatus.ROUTING,
        RunStatus.RUNNING_READONLY,
        RunStatus.RUNNING_WORKFLOW,
        RunStatus.COMMITTING,
        RunStatus.VERIFYING,
    }:
        return ("cancel",)
    if status is RunStatus.WAITING_USER:
        return ("continue", "cancel")
    if status is RunStatus.WAITING_CONFIRMATION:
        return ("confirm", "reject", "cancel")
    if status is RunStatus.WAITING_HUMAN:
        return ("refresh",)
    if status in TERMINAL:
        return ("new_message", "retry")
    return ()


def require_transition(current: RunStatus, target: RunStatus) -> None:
    if current in TERMINAL or target not in TRANSITIONS.get(current, frozenset()):
        raise StateTransitionError(f"illegal transition: {current} -> {target}")

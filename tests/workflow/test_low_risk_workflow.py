from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.mutation_safety import (
    MutationAdapterResult,
    MutationAdapterStatus,
    MutationCompletion,
    MutationExecutionClaim,
    MutationExecutionIntent,
    MutationExecutionStatus,
    StoredMutationExecution,
)
from src.orchestration.low_risk_workflow import (
    LowRiskWorkflowError,
    execute_low_risk,
)
from src.protocols import ExecutionMode, RunContext, RunStatus


class _ExecutionStore:
    def __init__(self) -> None:
        self.value: StoredMutationExecution | None = None

    def reserve(self, intent: MutationExecutionIntent) -> StoredMutationExecution:
        if self.value is None:
            self.value = StoredMutationExecution(intent, MutationExecutionStatus.RESERVED)
        return self.value

    def load(self, intent: MutationExecutionIntent) -> StoredMutationExecution | None:
        return self.value if self.value and self.value.intent == intent else None

    def claim(self, intent: MutationExecutionIntent) -> MutationExecutionClaim:
        assert self.value is not None and self.value.intent == intent
        if self.value.status is MutationExecutionStatus.RESERVED:
            self.value = StoredMutationExecution(intent, MutationExecutionStatus.IN_PROGRESS)
            return MutationExecutionClaim(self.value, acquired=True)
        return MutationExecutionClaim(self.value, acquired=False)

    def complete(self, completion: MutationCompletion) -> None:
        assert self.value is not None
        self.value = StoredMutationExecution(
            self.value.intent,
            completion.status,
            completion.business_reference,
            dict(completion.response_redacted),
        )


class _Checkpoints:
    def __init__(self, executions: _ExecutionStore) -> None:
        self.executions = executions
        self.version = 0

    def checkpoint(self, **_: Any) -> int:
        self.version += 1
        return self.version

    def checkpoint_mutation(self, *, completion: MutationCompletion, **_: Any) -> int:
        self.executions.complete(completion)
        self.version += 1
        return self.version


class _Handoffs:
    def __init__(self) -> None:
        self.count = 0

    def create(self, **_: Any):
        self.count += 1
        return uuid4()


class _System:
    def __init__(self, status: MutationAdapterStatus) -> None:
        self.status = status
        self.calls = 0

    def commit(self, **_: Any) -> MutationAdapterResult:
        self.calls += 1
        return MutationAdapterResult(
            status=self.status,
            business_reference=(
                "invoice-1" if self.status is MutationAdapterStatus.SUCCEEDED else None
            ),
        )


def _context() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant-demo",
        actor_id="actor-demo",
        execution_mode=ExecutionMode.WORKFLOW,
        workflow_id="invoice_request",
        workflow_version="1",
        status=RunStatus.RUNNING_WORKFLOW,
    )


def test_low_risk_success_is_durable_and_replay_does_not_call_adapter_twice() -> None:
    executions = _ExecutionStore()
    checkpoints = _Checkpoints(executions)
    system = _System(MutationAdapterStatus.SUCCEEDED)
    first = execute_low_risk(
        context=_context(),
        route="invoice_request",
        arguments={"order_id": "ORD-DEMO-001", "invoice_type": "electronic", "title": "个人"},
        executions=executions,
        checkpoints=checkpoints,
        system=system,
    )
    assert first.context.status is RunStatus.COMPLETED
    assert first.context.state["low_risk_status"] == "succeeded"
    assert system.calls == 1

    replay = execute_low_risk(
        context=first.context,
        route="invoice_request",
        arguments={"order_id": "ORD-DEMO-001", "invoice_type": "electronic", "title": "个人"},
        executions=executions,
        checkpoints=checkpoints,
        system=system,
    )
    assert replay.context.status is RunStatus.COMPLETED
    assert replay.context.state["low_risk_operation"] == "create_invoice_request"
    assert system.calls == 1


def test_low_risk_unknown_is_handoff_and_replay_does_not_retry() -> None:
    executions = _ExecutionStore()
    checkpoints = _Checkpoints(executions)
    handoffs = _Handoffs()
    system = _System(MutationAdapterStatus.UNKNOWN)
    first = execute_low_risk(
        context=_context(),
        route="delivery_issue",
        arguments={
            "order_id": "ORD-DEMO-001",
            "item_id": "TAH6206",
            "issue_type": "damaged_delivery",
        },
        executions=executions,
        checkpoints=checkpoints,
        handoffs=handoffs,
        system=system,
    )
    assert first.context.status is RunStatus.WAITING_HUMAN
    assert first.context.state["low_risk_status"] == "unknown"
    assert system.calls == 1
    assert handoffs.count == 1

    replay = execute_low_risk(
        context=first.context,
        route="delivery_issue",
        arguments={
            "order_id": "ORD-DEMO-001",
            "item_id": "TAH6206",
            "issue_type": "damaged_delivery",
        },
        executions=executions,
        checkpoints=checkpoints,
        handoffs=handoffs,
        system=system,
    )
    assert replay.context.status is RunStatus.WAITING_HUMAN
    assert system.calls == 1


def test_low_risk_rejection_is_failed_without_false_handoff() -> None:
    executions = _ExecutionStore()
    checkpoints = _Checkpoints(executions)
    handoffs = _Handoffs()
    result = execute_low_risk(
        context=_context(),
        route="invoice_request",
        arguments={"order_id": "ORD-DEMO-001", "invoice_type": "electronic", "title": "个人"},
        executions=executions,
        checkpoints=checkpoints,
        handoffs=handoffs,
        system=_System(MutationAdapterStatus.REJECTED),
    )
    assert result.context.status is RunStatus.FAILED
    assert result.context.state["low_risk_status"] == "failed"
    assert handoffs.count == 0


def test_low_risk_missing_slots_fails_before_reserving_intent() -> None:
    executions = _ExecutionStore()
    with pytest.raises(LowRiskWorkflowError) as error:
        execute_low_risk(
            context=_context(),
            route="delivery_issue",
            arguments={"order_id": "ORD-DEMO-001"},
            executions=executions,
            checkpoints=_Checkpoints(executions),
        )
    assert error.value.code == "MISSING_SLOTS"
    assert executions.value is None

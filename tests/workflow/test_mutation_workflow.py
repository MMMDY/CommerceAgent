from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

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
from src.orchestration.mutation_workflow import (
    MutationWorkflowError,
    confirm_mutation,
    prepare_mutation,
)
from src.protocols import DomainEvent, EventType, ExecutionMode, RunContext, RunStatus
from src.repositories.mutations import (
    ConfirmationTokenInput,
    ConfirmationTokenRecord,
    ConfirmationUnavailableError,
    IdempotencyReservation,
)
from src.workflows.mutations import MutationPlanner, MutationPlanningError


class _MemoryConfirmations:
    """Small repository double preserving the SQL repository's contracts."""

    def __init__(self) -> None:
        self.record: ConfirmationTokenRecord | None = None
        self.record_id = uuid4()
        self._idempotency: dict[str, IdempotencyReservation] = {}

    def issue(self, token: ConfirmationTokenInput) -> UUID:
        self.record = ConfirmationTokenRecord(
            token_id=self.record_id,
            token_hash=token.token_hash,
            run_id=token.run_id,
            tenant_id=token.tenant_id,
            actor_ref=token.actor_ref,
            mutation_type=token.mutation_type,
            resource_ref=token.resource_ref,
            preview_hash=token.preview_hash,
            arguments_hash=token.arguments_hash,
            policy_version=token.policy_version,
            workflow_version=token.workflow_version,
            status="waiting",
            expires_at=token.expires_at,
            row_version=0,
        )
        return self.record_id

    def load_for_run(
        self, *, run_id: UUID, tenant_id: str, actor_ref: str, token_hash: str | None = None
    ) -> ConfirmationTokenRecord | None:
        record = self.record
        if record is None:
            return None
        if (record.run_id, record.tenant_id, record.actor_ref) != (run_id, tenant_id, actor_ref):
            return None
        if token_hash is not None and record.token_hash != token_hash:
            return None
        return record

    def consume_and_reserve(
        self,
        *,
        token_hash: str,
        tenant_id: str,
        actor_ref: str,
        expected_token_version: int,
        operation: str,
        idempotency_key_hash: str,
        request_fingerprint: str,
        expires_at: datetime | None,
    ) -> IdempotencyReservation:
        del expires_at
        existing = self._idempotency.get(idempotency_key_hash)
        if existing is not None:
            if existing.reused:
                return existing
            return replace(existing, reused=True)
        record = self.record
        if (
            record is None
            or record.token_hash != token_hash
            or record.tenant_id != tenant_id
            or record.actor_ref != actor_ref
            or record.status != "waiting"
            or record.row_version != expected_token_version
            or record.expires_at <= datetime.now(UTC)
        ):
            raise ConfirmationUnavailableError("confirmation unavailable")
        self.record = replace(record, status="consumed", row_version=record.row_version + 1)
        reservation = IdempotencyReservation(
            record_id=self.record_id,
            status="reserved",
            reused=False,
        )
        self._idempotency[idempotency_key_hash] = reservation
        del operation, request_fingerprint
        return reservation


class _MemoryExecution:
    def __init__(self) -> None:
        self.value: StoredMutationExecution | None = None

    def reserve(self, intent: MutationExecutionIntent) -> None:
        self.value = StoredMutationExecution(intent, MutationExecutionStatus.RESERVED)

    def load(self, intent: MutationExecutionIntent) -> StoredMutationExecution | None:
        if self.value is None or self.value.intent != intent:
            return None
        return self.value

    def claim(self, intent: MutationExecutionIntent) -> MutationExecutionClaim:
        if self.value is None or self.value.intent != intent:
            raise RuntimeError("intent unavailable")
        if self.value.status is MutationExecutionStatus.RESERVED:
            self.value = replace(self.value, status=MutationExecutionStatus.IN_PROGRESS)
            return MutationExecutionClaim(self.value, acquired=True)
        return MutationExecutionClaim(self.value, acquired=False)

    def complete(self, completion: MutationCompletion) -> None:
        assert self.value is not None
        assert self.value.status is MutationExecutionStatus.IN_PROGRESS
        self.value = StoredMutationExecution(
            self.value.intent,
            completion.status,
            completion.business_reference,
            dict(completion.response_redacted),
        )


class _MemoryCheckpoints:
    def __init__(self, executions: _MemoryExecution) -> None:
        self.executions = executions
        self.calls: list[dict[str, Any]] = []

    def checkpoint(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        return len(self.calls)

    def checkpoint_mutation(self, *, completion: MutationCompletion, **kwargs: Any) -> int:
        self.executions.complete(completion)
        self.calls.append({**kwargs, "completion": completion})
        return len(self.calls)


class _MemoryHandoffs:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> UUID:
        self.created.append(kwargs)
        return uuid4()


class _MemoryAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _ControlledMutationSystem:
    def __init__(self, status: MutationAdapterStatus, *, verify_result: bool = True) -> None:
        self.status = status
        self.verify_result = verify_result
        self.commit_calls = 0
        self.readback_calls = 0

    def commit(self, **_: Any) -> MutationAdapterResult:
        self.commit_calls += 1
        return MutationAdapterResult(
            status=self.status,
            business_reference=(
                "DEMO-REF-1" if self.status is MutationAdapterStatus.SUCCEEDED else None
            ),
            response_redacted={"status": "accepted"},
        )

    def verify(self, **_: Any) -> bool:
        return self.verify_result

    def readback(self, **_: Any) -> None:
        self.readback_calls += 1
        return None


def _context() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant-demo",
        actor_id="demo-user-001",
        execution_mode=ExecutionMode.WORKFLOW,
        workflow_id="mutation",
        workflow_version="phase4-v1",
        status=RunStatus.RUNNING_WORKFLOW,
    )


def _prepare_and_confirm(
    mutation_type: str,
    arguments: dict[str, object],
    *,
    system: _ControlledMutationSystem | None = None,
) -> tuple[
    RunContext,
    _ControlledMutationSystem,
    _MemoryConfirmations,
    _MemoryCheckpoints,
    _MemoryHandoffs,
    _MemoryAudit,
]:
    context = _context()
    confirmations = _MemoryConfirmations()
    executions = _MemoryExecution()
    checkpoints = _MemoryCheckpoints(executions)
    handoffs = _MemoryHandoffs()
    audit = _MemoryAudit()
    prepared, _, token = prepare_mutation(
        context=context,
        mutation_type=mutation_type,
        arguments=arguments,
        confirmations=confirmations,
        checkpoints=checkpoints,
        token_ttl=timedelta(minutes=5),
    )
    intent = MutationExecutionIntent(
        record_id=confirmations.record_id,
        tenant_id=context.tenant_id,
        operation=str(prepared.state["mutation_operation"]),
        request_fingerprint=str(prepared.state["mutation_arguments_hash"]),
    )
    executions.reserve(intent)
    controlled = system or _ControlledMutationSystem(MutationAdapterStatus.SUCCEEDED)
    updated = confirm_mutation(
        context=prepared,
        token_plaintext=token,
        idempotency_key="idempotency-key-1",
        confirmations=confirmations,
        executions=executions,
        checkpoints=checkpoints,
        handoffs=handoffs,
        audit=audit,
        mutation_system=controlled,
    )
    return updated, controlled, confirmations, checkpoints, handoffs, audit


@pytest.mark.parametrize(
    ("mutation_type", "arguments"),
    (
        ("cancel_order", {"order_id": "ORD-DEMO-CANCEL-001", "reason": "不想要了"}),
        (
            "change_order",
            {"order_id": "ORD-DEMO-CANCEL-001", "new_address": "上海市浦东新区测试路 20 号"},
        ),
        (
            "request_refund",
            {"order_id": "ORD-DEMO-001", "item_id": "TAH6206", "reason": "质量问题"},
        ),
        (
            "return_product",
            {"order_id": "ORD-DEMO-001", "item_id": "TAH6206", "reason": "不合适"},
        ),
        (
            "exchange_product",
            {"order_id": "ORD-DEMO-001", "item_id": "TAH6206", "replacement_sku": "TAH6207"},
        ),
    ),
)
def test_each_mutation_workflow_replays_prepare_confirm_commit_verify(
    mutation_type: str, arguments: dict[str, object]
) -> None:
    updated, system, confirmations, checkpoints, handoffs, _ = _prepare_and_confirm(
        mutation_type, arguments
    )

    assert updated.status is RunStatus.COMPLETED
    assert updated.state["mutation_outcome"] == "succeeded"
    assert system.commit_calls == 1
    assert confirmations.record is not None and confirmations.record.status == "consumed"
    assert not handoffs.created
    event_types = tuple(
        event.event_type
        for call in checkpoints.calls
        for event in call.get("events", ())
        if isinstance(event, DomainEvent)
    )
    assert event_types == (
        EventType.MUTATION_PREPARED,
        EventType.USER_CONFIRMED,
        EventType.COMMIT_OBSERVED,
        EventType.STATE_VERIFIED,
    )
    serialized = repr(checkpoints.calls)
    assert "idempotency-key-1" not in serialized
    event_payloads = repr(
        [
            event.payload
            for call in checkpoints.calls
            for event in call.get("events", ())
            if isinstance(event, DomainEvent)
        ]
    )
    assert "上海市浦东新区测试路 20 号" not in event_payloads


def test_unknown_commit_creates_handoff_and_never_claims_success() -> None:
    updated, system, _, checkpoints, handoffs, audit = _prepare_and_confirm(
        "cancel_order",
        {"order_id": "ORD-DEMO-CANCEL-001", "reason": "不想要了"},
        system=_ControlledMutationSystem(MutationAdapterStatus.UNKNOWN),
    )

    assert updated.status is RunStatus.WAITING_HUMAN
    assert updated.state["mutation_outcome"] == "unknown"
    assert "business_reference" not in updated.state
    assert system.commit_calls == 1
    assert system.readback_calls == 1
    assert updated.state["mutation_readback_attempted"] is True
    assert updated.state["mutation_readback_found"] is False
    assert len(handoffs.created) == 1
    assert handoffs.created[0]["reason_code"] == "MUTATION_STATUS_UNKNOWN"
    assert audit.events[0]["event_type"] == "mutation_handoff_created"
    assert any(
        event.event_type is EventType.MUTATION_UNCERTAIN
        for call in checkpoints.calls
        for event in call.get("events", ())
        if isinstance(event, DomainEvent)
    )


def test_verify_mismatch_enters_handoff_without_success_response() -> None:
    updated, system, _, _, handoffs, audit = _prepare_and_confirm(
        "request_refund",
        {"order_id": "ORD-DEMO-001", "item_id": "TAH6206", "reason": "质量问题"},
        system=_ControlledMutationSystem(
            MutationAdapterStatus.SUCCEEDED,
            verify_result=False,
        ),
    )

    assert updated.status is RunStatus.WAITING_HUMAN
    assert updated.state["mutation_outcome"] == "verification_mismatch"
    assert updated.state.get("verified_state") is None
    assert len(handoffs.created) == 1
    assert handoffs.created[0]["reason_code"] == "VERIFY_MISMATCH"
    assert audit.events[0]["event_type"] == "mutation_handoff_created"


def test_confirmation_is_single_use_at_workflow_boundary() -> None:
    updated, system, confirmations, checkpoints, handoffs, audit = _prepare_and_confirm(
        "cancel_order",
        {"order_id": "ORD-DEMO-CANCEL-001", "reason": "不想要了"},
    )
    assert updated.status is RunStatus.COMPLETED
    assert system.commit_calls == 1
    assert not handoffs.created
    assert len(audit.events) == 0
    assert checkpoints.calls
    assert confirmations.record is not None and confirmations.record.status == "consumed"

    # A second request cannot reach the boundary because the token is no
    # longer waiting.  This mirrors the SQL repository's atomic row-version
    # check without requiring a database in the workflow contract suite.
    with pytest.raises(MutationWorkflowError, match="失效"):
        _ = confirm_mutation(
            context=updated,
            token_plaintext="not-the-original-token",
            idempotency_key="idempotency-key-1",
            confirmations=confirmations,
            executions=_MemoryExecution(),
            checkpoints=checkpoints,
        )


def test_changed_preview_cannot_reuse_a_confirmation_token() -> None:
    context = _context()
    confirmations = _MemoryConfirmations()
    executions = _MemoryExecution()
    checkpoints = _MemoryCheckpoints(executions)
    prepared, _, token = prepare_mutation(
        context=context,
        mutation_type="change_order",
        arguments={
            "order_id": "ORD-DEMO-CANCEL-001",
            "new_address": "上海市浦东新区测试路 20 号",
        },
        confirmations=confirmations,
        checkpoints=checkpoints,
    )
    tampered = prepared.model_copy(
        update={
            "state": {
                **prepared.state,
                "mutation_preview_hash": "sha256:tampered-preview",
            }
        }
    )
    with pytest.raises(MutationWorkflowError, match="预览已变化"):
        confirm_mutation(
            context=tampered,
            token_plaintext=token,
            idempotency_key="idempotency-key-1",
            confirmations=confirmations,
            executions=executions,
            checkpoints=checkpoints,
        )
    assert confirmations.record is not None and confirmations.record.status == "waiting"
    assert executions.value is None


def test_expired_or_cross_actor_confirmation_never_reaches_commit() -> None:
    context = _context()
    confirmations = _MemoryConfirmations()
    executions = _MemoryExecution()
    checkpoints = _MemoryCheckpoints(executions)
    prepared, _, token = prepare_mutation(
        context=context,
        mutation_type="cancel_order",
        arguments={"order_id": "ORD-DEMO-CANCEL-001", "reason": "不想要了"},
        confirmations=confirmations,
        checkpoints=checkpoints,
    )
    assert confirmations.record is not None
    confirmations.record = replace(
        confirmations.record, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    with pytest.raises(MutationWorkflowError):
        confirm_mutation(
            context=prepared,
            token_plaintext=token,
            idempotency_key="idempotency-key-expired",
            confirmations=confirmations,
            executions=executions,
            checkpoints=checkpoints,
            mutation_system=_ControlledMutationSystem(MutationAdapterStatus.SUCCEEDED),
        )
    assert executions.value is None

    # Re-prepare a fresh token, then change only the authenticated actor.
    context = _context()
    confirmations = _MemoryConfirmations()
    checkpoints = _MemoryCheckpoints(executions := _MemoryExecution())
    prepared, _, token = prepare_mutation(
        context=context,
        mutation_type="cancel_order",
        arguments={"order_id": "ORD-DEMO-CANCEL-001", "reason": "不想要了"},
        confirmations=confirmations,
        checkpoints=checkpoints,
    )
    foreign_context = prepared.model_copy(update={"actor_id": "demo-user-002"})
    with pytest.raises(MutationWorkflowError):
        confirm_mutation(
            context=foreign_context,
            token_plaintext=token,
            idempotency_key="idempotency-key-foreign",
            confirmations=confirmations,
            executions=executions,
            checkpoints=checkpoints,
            mutation_system=_ControlledMutationSystem(MutationAdapterStatus.SUCCEEDED),
        )
    assert executions.value is None


def test_planner_rejects_missing_slots_and_policy_denials() -> None:
    planner = MutationPlanner()
    with pytest.raises(MutationPlanningError, match="补充") as missing:
        planner.prepare(
            mutation_type="exchange_product",
            actor_id="demo-user-001",
            arguments={"order_id": "ORD-DEMO-001", "item_id": "TAH6206"},
        )
    assert missing.value.code == "MISSING_SLOTS"
    with pytest.raises(MutationPlanningError, match="不支持取消") as denied:
        planner.prepare(
            mutation_type="cancel_order",
            actor_id="demo-user-001",
            arguments={"order_id": "ORD-DEMO-001", "reason": "不想要了"},
        )
    assert denied.value.code == "POLICY_DENIED"

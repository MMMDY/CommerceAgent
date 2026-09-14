"""Deterministic Phase 4 mutation orchestration.

This is deliberately separate from ``AgentLoop``.  The model/router selects a
workflow; after that, this module owns every state transition and calls the
runtime-only commit boundary exactly once.
"""

# ruff: noqa: E501

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from src.mutation_safety import (
    MutationAdapterResult,
    MutationAdapterStatus,
    MutationCompletion,
    MutationExecutionIntent,
    MutationExecutionStatus,
)
from src.orchestration.mutation_execution import DurableMutationBoundary
from src.orchestration.persistence import RepositoryCheckpointStore
from src.protocols import DomainEvent, EventType, RunContext, RunStatus
from src.repositories.mutations import (
    ConfirmationRepository,
    ConfirmationTokenInput,
    ConfirmationUnavailableError,
    IdempotencyConflictError,
    MutationExecutionRepository,
)
from src.workflows.mutations import (
    MutationPlanner,
    MutationPlanningError,
    MutationPreview,
    arguments_hash,
    hash_secret,
    preview_hash,
)

MUTATION_ROUTE_TO_TYPE = {
    "cancel_order": "cancel_order",
    "change_order": "change_order",
    "refund": "request_refund",
    "return": "return_product",
    "exchange": "exchange_product",
}


class MutationWorkflowError(RuntimeError):
    """A mutation could not safely advance."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DemoMutationSystem:
    """Small process-local business fixture used until real APIs are wired."""

    def __init__(self) -> None:
        self._completed: dict[tuple[str, str], dict[str, object]] = {}

    def commit(
        self,
        *,
        operation: str,
        actor_id: str,
        resource_ref: str,
        arguments: dict[str, object],
        idempotency_key: str,
    ) -> MutationAdapterResult:
        key = (actor_id, idempotency_key)
        if key in self._completed:
            existing = self._completed[key]
            stored_response = existing.get("response", {})
            response = (
                {str(k): v for k, v in stored_response.items()}
                if isinstance(stored_response, dict)
                else {}
            )
            return MutationAdapterResult(
                status=MutationAdapterStatus.SUCCEEDED,
                business_reference=str(existing["business_reference"]),
                response_redacted=response,
            )
        reference = f"DEMO-{operation.removeprefix('commit_').upper()}-{resource_ref}"
        response = {
            "operation": operation,
            "resource_ref": resource_ref,
            "status": "accepted",
            "actor_scope": "verified_owner",
        }
        self._completed[key] = {"business_reference": reference, "response": response}
        return MutationAdapterResult(
            status=MutationAdapterStatus.SUCCEEDED,
            business_reference=reference,
            response_redacted=response,
        )


DEMO_MUTATION_SYSTEM = DemoMutationSystem()


def prepare_mutation(
    *,
    context: RunContext,
    mutation_type: str,
    arguments: dict[str, object],
    confirmations: ConfirmationRepository,
    checkpoints: RepositoryCheckpointStore,
    token_ttl: timedelta = timedelta(minutes=10),
) -> tuple[RunContext, MutationPreview, str]:
    """Prepare a mutation and return the one-time plaintext token once."""

    planner = MutationPlanner()
    try:
        preview = planner.prepare(
            mutation_type=mutation_type,
            actor_id=context.actor_id,
            arguments=arguments,
        )
    except MutationPlanningError as error:
        raise MutationWorkflowError(error.code, str(error)) from error
    now = datetime.now(UTC)
    expires_at = now + token_ttl
    token_plaintext = secrets.token_urlsafe(32)
    token_hash = hash_secret(token_plaintext)
    public_preview = preview.as_public()
    p_hash = preview_hash(preview)
    a_hash = arguments_hash(preview.normalized_args)
    confirmations.issue(
        ConfirmationTokenInput(
            token_hash=token_hash,
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            actor_ref=context.actor_id,
            mutation_type=mutation_type,
            resource_ref=preview.resource_ref,
            preview_hash=p_hash,
            arguments_hash=a_hash,
            policy_version=preview.policy_version,
            workflow_version=preview.workflow_version,
            expires_at=expires_at,
        )
    )
    state = dict(context.state)
    state.update(
        {
            "mutation_type": mutation_type,
            "mutation_args": preview.normalized_args,
            "mutation_preview": public_preview,
            "mutation_preview_hash": p_hash,
            "mutation_arguments_hash": a_hash,
            "mutation_resource_ref": preview.resource_ref,
            "mutation_operation": preview.operation,
            "mutation_expires_at": expires_at.isoformat(),
            "confirmation_token_required": True,
        }
    )
    version = checkpoints.checkpoint(
        context=context,
        status=RunStatus.WAITING_CONFIRMATION,
        next_step="confirm_mutation",
        state=state,
        events=(
            DomainEvent(
                event_type=EventType.MUTATION_PREPARED,
                payload={
                    "mutation_type": mutation_type,
                    "resource_ref": preview.resource_ref,
                    "preview_hash": p_hash,
                    "expires_at": expires_at.isoformat(),
                },
            ),
        ),
    )
    return (
        context.model_copy(
            update={
                "status": RunStatus.WAITING_CONFIRMATION,
                "state": state,
                "step_count": context.step_count + 1,
                "checkpoint_version": version,
            }
        ),
        preview,
        token_plaintext,
    )


def reject_mutation(
    *,
    context: RunContext,
    confirmations: ConfirmationRepository,
    checkpoints: RepositoryCheckpointStore,
    token_hash: str,
) -> RunContext:
    record = confirmations.load_for_run(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
        actor_ref=context.actor_id,
        token_hash=token_hash,
    )
    if record is None or record.status != "waiting":
        raise MutationWorkflowError("CONFIRMATION_UNAVAILABLE", "确认已失效")
    confirmations.reject(
        token_hash=token_hash,
        tenant_id=context.tenant_id,
        actor_ref=context.actor_id,
        expected_version=record.row_version,
    )
    state = dict(context.state)
    state["mutation_outcome"] = "rejected_by_user"
    version = checkpoints.checkpoint(
        context=context,
        status=RunStatus.CANCELLED,
        next_step="terminal",
        state=state,
        events=(DomainEvent(event_type=EventType.FAILED, payload={"reason": "user_rejected"}),),
    )
    return context.model_copy(
        update={"status": RunStatus.CANCELLED, "state": state, "step_count": context.step_count + 1, "checkpoint_version": version}
    )


def confirm_mutation(
    *,
    context: RunContext,
    token_plaintext: str,
    idempotency_key: str,
    confirmations: ConfirmationRepository,
    executions: MutationExecutionRepository,
    checkpoints: RepositoryCheckpointStore,
) -> RunContext:
    """Consume confirmation, commit once, then verify the fixture state."""

    token_hash = hash_secret(token_plaintext)
    record = confirmations.load_for_run(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
        actor_ref=context.actor_id,
        token_hash=token_hash,
    )
    if record is None or record.status != "waiting":
        raise MutationWorkflowError("CONFIRMATION_UNAVAILABLE", "确认已失效或已使用")
    state = dict(context.state)
    if record.preview_hash != state.get("mutation_preview_hash"):
        raise MutationWorkflowError("PREVIEW_CHANGED", "预览已变化，请重新确认")
    operation = str(state.get("mutation_operation", ""))
    fingerprint = str(state.get("mutation_arguments_hash", ""))
    try:
        reservation = confirmations.consume_and_reserve(
            token_hash=token_hash,
            tenant_id=context.tenant_id,
            actor_ref=context.actor_id,
            expected_token_version=record.row_version,
            operation=operation,
            idempotency_key_hash=hash_secret(idempotency_key),
            request_fingerprint=fingerprint,
            expires_at=None,
        )
    except (ConfirmationUnavailableError, IdempotencyConflictError) as error:
        raise MutationWorkflowError("CONFIRMATION_CONFLICT", "确认请求已失效或发生冲突") from error
    if reservation.reused:
        # A previously completed idempotency record is replayed by the caller;
        # never execute the mutation again.
        state["mutation_replayed"] = True
        return context

    state["mutation_idempotency_record_id"] = str(reservation.record_id)
    state["mutation_idempotency_key_hash"] = hash_secret(idempotency_key)
    state["mutation_commit_status"] = "started"
    committing_version = checkpoints.checkpoint(
        context=context,
        status=RunStatus.COMMITTING,
        next_step="commit_mutation",
        state=state,
        events=(DomainEvent(event_type=EventType.USER_CONFIRMED, payload={"operation": operation}),),
    )
    committing = context.model_copy(
        update={"status": RunStatus.COMMITTING, "state": state, "step_count": context.step_count + 1, "checkpoint_version": committing_version}
    )
    intent = MutationExecutionIntent(
        record_id=reservation.record_id,
        tenant_id=context.tenant_id,
        operation=operation,
        request_fingerprint=fingerprint,
    )
    outcome_version: dict[str, int] = {}

    def checkpoint_completion(completion: MutationCompletion) -> None:
        state_after = dict(committing.state)
        state_after["mutation_commit_status"] = completion.status.value
        if completion.business_reference:
            state_after["business_reference"] = completion.business_reference
        status = (
            RunStatus.VERIFYING
            if completion.status in {MutationExecutionStatus.SUCCEEDED, MutationExecutionStatus.UNKNOWN}
            else RunStatus.FAILED
        )
        next_step = "verify_mutation" if status is RunStatus.VERIFYING else "terminal"
        version = checkpoints.checkpoint_mutation(
            context=committing,
            status=status,
            next_step=next_step,
            state=state_after,
            events=(
                DomainEvent(
                    event_type=EventType.COMMIT_OBSERVED,
                    payload={"status": completion.status.value, "business_reference": completion.business_reference},
                ),
            ),
            completion=completion,
        )
        outcome_version["value"] = version
        outcome_version["status"] = status.value  # type: ignore[assignment]

    boundary = DurableMutationBoundary(executions)
    outcome = boundary.execute(
        intent=intent,
        adapter=lambda key: DEMO_MUTATION_SYSTEM.commit(
            operation=operation,
            actor_id=context.actor_id,
            resource_ref=str(state.get("mutation_resource_ref", "")),
            arguments=dict(state.get("mutation_args", {})),
            idempotency_key=key,
        ),
        checkpoint=checkpoint_completion,
    )
    if outcome.status is not MutationExecutionStatus.SUCCEEDED:
        status = RunStatus.WAITING_HUMAN if outcome.status is MutationExecutionStatus.UNKNOWN else RunStatus.FAILED
        final_version = checkpoints.checkpoint(
            context=committing.model_copy(update={"status": RunStatus.VERIFYING, "checkpoint_version": outcome_version["value"]}),
            status=status,
            next_step="terminal",
            state={**committing.state, "mutation_outcome": outcome.status.value},
            events=(DomainEvent(event_type=EventType.FAILED, payload={"reason": "mutation_status_unknown"}),),
        )
        return committing.model_copy(update={"status": status, "step_count": committing.step_count + 2, "checkpoint_version": final_version})
    verifying = committing.model_copy(
        update={"status": RunStatus.VERIFYING, "state": {**committing.state, "mutation_outcome": "succeeded"}, "step_count": committing.step_count + 1, "checkpoint_version": outcome_version["value"]}
    )
    final_state = dict(verifying.state)
    final_state["verified_state"] = {"operation": operation, "status": "applied"}
    final_version = checkpoints.checkpoint(
        context=verifying,
        status=RunStatus.COMPLETED,
        next_step="terminal",
        state=final_state,
        events=(DomainEvent(event_type=EventType.STATE_VERIFIED, payload={"status": "applied"}),),
    )
    return verifying.model_copy(
        update={"status": RunStatus.COMPLETED, "state": final_state, "step_count": verifying.step_count + 1, "checkpoint_version": final_version}
    )


def refresh_mutation_token(
    *,
    context: RunContext,
    confirmations: ConfirmationRepository,
    checkpoints: RepositoryCheckpointStore,
    token_ttl: timedelta = timedelta(minutes=10),
) -> tuple[str, str, dict[str, object]]:
    """Atomically invalidate the previous waiting token and issue a new one."""

    if context.status is not RunStatus.WAITING_CONFIRMATION:
        raise MutationWorkflowError("RUN_NOT_WAITING_CONFIRMATION", "当前 run 不等待确认")
    record = confirmations.load_for_run(
        run_id=context.run_id, tenant_id=context.tenant_id, actor_ref=context.actor_id
    )
    preview = context.state.get("mutation_preview")
    preview_hash_value = context.state.get("mutation_preview_hash")
    arguments_hash_value = context.state.get("mutation_arguments_hash")
    mutation_type = context.state.get("mutation_type")
    resource_ref = context.state.get("mutation_resource_ref")
    operation = context.state.get("mutation_operation")
    if (
        record is None
        or record.status != "waiting"
        or not isinstance(preview, dict)
        or not isinstance(preview_hash_value, str)
        or not isinstance(arguments_hash_value, str)
        or not isinstance(mutation_type, str)
        or not isinstance(resource_ref, str)
        or not isinstance(operation, str)
    ):
        raise MutationWorkflowError("TOKEN_REFRESH_REQUIRED", "确认 token 不可刷新")
    if record.preview_hash != preview_hash_value or record.arguments_hash != arguments_hash_value:
        raise MutationWorkflowError("PREVIEW_CHANGED", "预览已变化")
    expires_at = datetime.now(UTC) + token_ttl
    token_plaintext = secrets.token_urlsafe(32)
    confirmations.rotate_waiting(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
        actor_ref=context.actor_id,
        expected_preview_hash=preview_hash_value,
        token=ConfirmationTokenInput(
            token_hash=hash_secret(token_plaintext),
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            actor_ref=context.actor_id,
            mutation_type=mutation_type,
            resource_ref=resource_ref,
            preview_hash=preview_hash_value,
            arguments_hash=arguments_hash_value,
            policy_version=record.policy_version,
            workflow_version=record.workflow_version,
            expires_at=expires_at,
        ),
    )
    state = dict(context.state)
    state["mutation_expires_at"] = expires_at.isoformat()
    checkpoints.checkpoint(
        context=context,
        status=RunStatus.WAITING_CONFIRMATION,
        next_step="confirm_mutation",
        state=state,
        events=(
            DomainEvent(
                event_type=EventType.MUTATION_PREPARED,
                payload={
                    "mutation_type": mutation_type,
                    "resource_ref": resource_ref,
                    "preview_hash": preview_hash_value,
                    "expires_at": expires_at.isoformat(),
                },
            ),
        ),
    )
    return token_plaintext, expires_at.isoformat(), dict(preview)


def mutation_type_for_route(route: str) -> str | None:
    return MUTATION_ROUTE_TO_TYPE.get(route)

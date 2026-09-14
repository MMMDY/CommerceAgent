"""Deterministic, non-confirmed write workflows for operational requests.

Invoice requests and delivery claims do not change order/payment state in the
demo system, but they still create durable intents and are never executed by a
model-visible commit tool.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from uuid import NAMESPACE_URL, UUID, uuid5

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
from src.repositories.audit import AuditRepository
from src.repositories.handoffs import HandoffRepository
from src.repositories.mutations import MutationExecutionRepository

LOW_RISK_ROUTES = frozenset({"invoice_request", "delivery_issue"})


class LowRiskWorkflowError(ValueError):
    def __init__(self, code: str, message: str, missing_slots: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.missing_slots = missing_slots


@dataclass(frozen=True, slots=True)
class LowRiskResult:
    context: RunContext
    business_reference: str | None


class DemoLowRiskSystem:
    def __init__(self) -> None:
        self._requests: dict[str, dict[str, object]] = {}

    def commit(
        self, *, operation: str, actor_id: str, resource_ref: str, arguments: dict[str, object], key: str
    ) -> MutationAdapterResult:
        if key in self._requests:
            item = self._requests[key]
            return MutationAdapterResult(
                status=MutationAdapterStatus.SUCCEEDED,
                business_reference=str(item["business_reference"]),
                response_redacted={"status": "accepted"},
            )
        reference = f"DEMO-{operation.upper()}-{resource_ref}"
        self._requests[key] = {"business_reference": reference, "actor_id": actor_id, "arguments": arguments}
        return MutationAdapterResult(
            status=MutationAdapterStatus.SUCCEEDED,
            business_reference=reference,
            response_redacted={"status": "accepted"},
        )


DEMO_LOW_RISK_SYSTEM = DemoLowRiskSystem()


def extract_low_risk_arguments(route: str, text: str, *, intent: str | None = None) -> dict[str, object]:
    order = re.search(r"ORD-[A-Z0-9-]+", text, flags=re.IGNORECASE)
    skus = re.findall(r"SKU-[A-Z0-9-]+", text, flags=re.IGNORECASE)
    args: dict[str, object] = {}
    if order:
        args["order_id"] = order.group(0).upper()
    if route == "invoice_request":
        args.update({"invoice_type": "electronic", "title": "个人"})
    elif route == "delivery_issue":
        if skus:
            args["item_id"] = skus[0].upper()
        args["issue_type"] = intent or "delivery_issue"
    return args


def execute_low_risk(
    *,
    context: RunContext,
    route: str,
    arguments: dict[str, object],
    executions: MutationExecutionRepository,
    checkpoints: RepositoryCheckpointStore,
    handoffs: HandoffRepository | None = None,
    audit: AuditRepository | None = None,
    system: DemoLowRiskSystem | None = None,
) -> LowRiskResult:
    if route not in LOW_RISK_ROUTES:
        raise LowRiskWorkflowError("UNKNOWN_LOW_RISK_ROUTE", "暂不支持该低风险操作")
    required = ("order_id",) if route == "invoice_request" else ("order_id", "item_id")
    missing = tuple(slot for slot in required if not arguments.get(slot))
    if missing:
        raise LowRiskWorkflowError("MISSING_SLOTS", "还需要补充必要信息", missing)
    operation = "create_invoice_request" if route == "invoice_request" else "report_delivery_issue"
    resource_ref = str(arguments["order_id"])
    fingerprint = _hash(arguments)
    record_id = uuid5(NAMESPACE_URL, f"commerce-agent:{context.run_id}:{operation}")
    intent = MutationExecutionIntent(
        record_id=record_id,
        tenant_id=context.tenant_id,
        operation=operation,
        request_fingerprint=fingerprint,
    )
    executions.reserve(intent)
    state = dict(context.state)
    state.update({"low_risk_operation": operation, "low_risk_args": dict(arguments)})
    completion_state: dict[str, object] = {}
    outcome_version: dict[str, int] = {}
    system = system or DEMO_LOW_RISK_SYSTEM

    def checkpoint(completion: MutationCompletion) -> None:
        after = dict(state)
        after["low_risk_status"] = completion.status.value
        if completion.business_reference:
            after["business_reference"] = completion.business_reference
        completion_state.update(after)
        target = (
            RunStatus.COMPLETED
            if completion.status is MutationExecutionStatus.SUCCEEDED
            else RunStatus.WAITING_HUMAN
        )
        events = (
            DomainEvent(
                event_type=EventType.COMMIT_OBSERVED,
                payload={"operation": operation, "status": completion.status.value},
            ),
        )
        outcome_version["value"] = checkpoints.checkpoint_mutation(
            context=context,
            status=target,
            next_step="terminal",
            state=after,
            events=events,
            completion=completion,
        )

    outcome = DurableMutationBoundary(executions).execute(
        intent=intent,
        adapter=lambda key: system.commit(
            operation=operation,
            actor_id=context.actor_id,
            resource_ref=resource_ref,
            arguments=arguments,
            key=key,
        ),
        checkpoint=checkpoint,
    )
    if outcome.status is MutationExecutionStatus.UNKNOWN:
        ticket_id = _handoff(
            context=context,
            operation=operation,
            reason="LOW_RISK_STATUS_UNKNOWN",
            handoffs=handoffs,
            audit=audit,
        )
        final_state = {**completion_state, "low_risk_status": "unknown"}
        if ticket_id:
            final_state["handoff_ticket_id"] = str(ticket_id)
        final_version = checkpoints.checkpoint(
            context=context.model_copy(update={"status": RunStatus.VERIFYING, "checkpoint_version": outcome_version["value"]}),
            status=RunStatus.WAITING_HUMAN,
            next_step="terminal",
            state=final_state,
            events=(
                DomainEvent(event_type=EventType.MUTATION_UNCERTAIN, payload={"operation": operation}),
                *(
                    (DomainEvent(event_type=EventType.HANDOFF_CREATED, payload={"handoff_ticket_id": str(ticket_id)}),)
                    if ticket_id
                    else ()
                ),
            ),
        )
        return LowRiskResult(
            context=context.model_copy(update={"status": RunStatus.WAITING_HUMAN, "state": final_state, "step_count": context.step_count + 2, "checkpoint_version": final_version}),
            business_reference=None,
        )
    completed = context.model_copy(
        update={"status": RunStatus.COMPLETED, "state": completion_state, "step_count": context.step_count + 1, "checkpoint_version": outcome_version["value"]}
    )
    return LowRiskResult(context=completed, business_reference=outcome.business_reference)


def _hash(arguments: dict[str, object]) -> str:
    encoded = dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def _handoff(*, context: RunContext, operation: str, reason: str, handoffs: HandoffRepository | None, audit: AuditRepository | None) -> UUID | None:
    ticket_id = handoffs.create(run_id=context.run_id, tenant_id=context.tenant_id, actor_ref=context.actor_id, reason_code=reason, operation=operation, details={}) if handoffs else None
    if audit:
        audit.append(tenant_id=context.tenant_id, actor_ref=context.actor_id, event_type="low_risk_handoff_created", payload={"run_id": str(context.run_id), "operation": operation, "reason": reason}, payload_hash=_hash({"run_id": str(context.run_id), "operation": operation, "reason": reason}))
    return ticket_id

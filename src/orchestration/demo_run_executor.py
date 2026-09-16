"""Background execution for the demo workbench.

Message acceptance is intentionally separate from this module.  The API stores
the user message and run reservation first, then this single-concurrency demo
dispatcher invokes the existing orchestration components.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.agent.intent_classifier import IntentClassifier
from src.config import Settings
from src.db import get_engine
from src.models.gateway import ModelGatewayError, OpenAICompatibleGateway
from src.orchestration.api_runtime import execute_readonly_run
from src.orchestration.low_risk_workflow import (
    LOW_RISK_ROUTES,
    LowRiskWorkflowError,
    execute_low_risk,
    extract_low_risk_arguments,
)
from src.orchestration.mutation_workflow import (
    MutationWorkflowError,
    mutation_type_for_route,
    prepare_mutation,
)
from src.orchestration.persistence import RepositoryCheckpointStore
from src.orchestration.route_catalog import DEFAULT_INTENT_ROUTE_RULES
from src.orchestration.router import IntentRouter, RouteDecision, RouteOutcome
from src.orchestration.terminal_response import publish_terminal_response
from src.protocols import DomainEvent, EventType, Message, RoutingPromptView, RunContext, RunStatus
from src.repositories.audit import AuditRepository
from src.repositories.handoffs import HandoffRepository
from src.repositories.messages import MessageRepository
from src.repositories.model_invocations import ModelInvocationRepository
from src.repositories.mutations import ConfirmationRepository, MutationExecutionRepository
from src.repositories.run_lifecycle import RunRoutingRepository
from src.repositories.runs import RunRepository
from src.workflows.mutations import extract_arguments

_SLOT_LABELS = {
    "order_id": "订单号",
    "item_id": "退款商品编号",
    "reason": "退款原因",
    "new_address": "新地址",
    "replacement_sku": "替换商品编号",
}


def _missing_slot_prompt(
    *, route: str, missing_slots: tuple[str, ...], arguments: dict[str, object]
) -> str:
    """Turn workflow slot metadata into a direct, user-facing question."""

    labels = [_SLOT_LABELS.get(slot, slot) for slot in missing_slots]
    if route == "refund":
        examples = {
            "item_id": "例如 BHD308/10",
            "reason": "例如质量问题或不想要",
        }
    else:
        examples = {}
    details = "、".join(
        f"{label}（{examples[slot]}）" if slot in examples else label
        for slot, label in zip(missing_slots, labels, strict=True)
    )
    resource = str(arguments.get("order_id", ""))
    prefix = f"要继续处理订单 {resource}，" if resource else "要继续处理这个请求，"
    return f"{prefix}请补充：{details}。补充后我会继续当前退款流程。"


def _execute_message_run(
    *,
    conversation_id: UUID,
    content: str,
    actor_id: str,
    run_id: UUID,
    tenant_id: str,
    settings: Settings,
) -> None:
    """Run one accepted message and persist user-visible lifecycle evidence."""

    engine = get_engine()
    messages = MessageRepository(engine)
    runs = RunRepository(engine)
    persisted = runs.load_latest_checkpoint(run_id=run_id, tenant_id=tenant_id)
    if persisted is not None:
        context = RunContext.model_validate(persisted)
        if context.status is RunStatus.WAITING_USER:
            context = context.model_copy(update={"status": RunStatus.RUNNING_WORKFLOW})
    else:
        context = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            status=RunStatus.CREATED,
        )

    def observe(event_type: EventType, step: str, payload: dict[str, Any]) -> None:
        try:
            runs.append_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type=event_type,
                step_id=step,
                payload=payload,
            )
        except Exception:
            # Observability must not turn a valid business result into a second
            # failure. The durable checkpoint events remain authoritative.
            return

    try:
        if context.status is RunStatus.CREATED:
            observe(EventType.RUN_CREATED, "accept", {"message_id": "[REDACTED]"})
        if (
            context.status in {RunStatus.RUNNING_WORKFLOW, RunStatus.RUNNING_READONLY}
            and context.workflow_id
        ):
            routed = RouteDecision(
                outcome=RouteOutcome.EXECUTE,
                execution_mode=context.execution_mode,
                workflow_id=context.workflow_id,
                workflow_version=context.workflow_version,
                intent=str(context.state.get("intent") or "continuation"),
                reason_code="CONTINUATION",
            )
        else:
            observe(EventType.MODEL_REQUEST_STARTED, "route_intent_risk", {"purpose": "routing"})
            routing_prompt = RoutingPromptView(
                conversation=(Message(role="user", content=content),),
                allowed_intents=tuple(rule.intent for rule in DEFAULT_INTENT_ROUTE_RULES),
            )
            candidate = IntentClassifier(
                gateway=OpenAICompatibleGateway(settings),
                invocations=ModelInvocationRepository(engine),
            ).classify(context=context, prompt=routing_prompt)
            observe(
                EventType.MODEL_REQUEST_SUCCEEDED,
                "route_intent_risk",
                {"purpose": "routing", "outcome": "classified"},
            )
            routed = IntentRouter(DEFAULT_INTENT_ROUTE_RULES).decide(candidate)
            routed_context = context.model_copy(update={"status": RunStatus.ROUTING})
            RunRoutingRepository(engine).select_route(context=routed_context, decision=routed)
        if routed.outcome is RouteOutcome.HANDOFF:
            handoff_id = HandoffRepository(engine).create(
                run_id=run_id,
                tenant_id=tenant_id,
                actor_ref=actor_id,
                reason_code=routed.reason_code,
                operation=routed.workflow_id,
                details={
                    "message": "请求需要人工处理",
                    "route_reason": routed.reason_code,
                },
            )
            handoff_state = dict(context.state)
            handoff_state["handoff_ticket_id"] = str(handoff_id)
            RepositoryCheckpointStore(runs).checkpoint(
                context=context,
                status=RunStatus.WAITING_HUMAN,
                next_step="terminal",
                state=handoff_state,
                events=(
                    DomainEvent(
                        event_type=EventType.HANDOFF_CREATED,
                        payload={
                            "handoff_ticket_id": str(handoff_id),
                            "reason": routed.reason_code,
                        },
                    ),
                ),
            )
            prompt = "该请求需要人工审核，请查看右侧的人工处理窗口并选择审核结果。"
            publish_terminal_response(
                context=context.model_copy(
                    update={"status": RunStatus.WAITING_HUMAN, "state": handoff_state}
                ),
                messages=messages,
                runs=runs,
                preferred_content=prompt,
                reason_code=routed.reason_code,
                retryable=False,
            )
            return

        assert routed.execution_mode is not None
        assert routed.workflow_id is not None
        routed_state = dict(context.state)
        routed_state.update({"intent": routed.intent or "", "route": routed.workflow_id})
        routed_context = context.model_copy(
            update={
                "status": (
                    RunStatus.RUNNING_READONLY
                    if routed.execution_mode.value == "readonly_loop"
                    else RunStatus.RUNNING_WORKFLOW
                ),
                "execution_mode": routed.execution_mode,
                "workflow_id": routed.workflow_id,
                "workflow_version": routed.workflow_version,
                "state": routed_state,
            }
        )
        if routed.execution_mode.value == "readonly_loop":
            try:
                result = execute_readonly_run(
                    settings=settings,
                    context=routed_context,
                    route=routed.workflow_id,
                    messages=messages,
                    run_repository=runs,
                    action_observer=lambda action, payload: observe(
                        EventType(action), "agent", payload
                    ),
                )
                response = next(
                    (step.response for step in reversed(result.steps) if step.response), None
                )
                if result.context.status is not RunStatus.RUNNING_READONLY:
                    reason = result.context.state.get("last_step_reason")
                    if isinstance(reason, str) and reason:
                        runs.set_terminal_reason(run_id=run_id, tenant_id=tenant_id, reason=reason)
                    publish_terminal_response(
                        context=result.context,
                        messages=messages,
                        runs=runs,
                        preferred_content=response,
                        reason_code=reason if isinstance(reason, str) else None,
                    )
            except Exception:
                observe(
                    EventType.MODEL_REQUEST_FAILED,
                    "readonly_loop",
                    {"purpose": "agent", "error_code": "UPSTREAM_UNAVAILABLE"},
                )
                _mark_failed(
                    runs, messages, routed_context, "UPSTREAM_UNAVAILABLE", observe
                )
            return

        mutation_type: str | None = None
        mutation_arguments: dict[str, object] = {}
        try:
            mutation_type = mutation_type_for_route(routed.workflow_id)
            if mutation_type is not None:
                previous_arguments = routed_context.state.get("mutation_args", {})
                if isinstance(previous_arguments, dict):
                    mutation_arguments.update(
                        {str(key): value for key, value in previous_arguments.items()}
                    )
                mutation_arguments.update(extract_arguments(mutation_type, content))
                prepared_context, preview, _ = prepare_mutation(
                    context=routed_context,
                    mutation_type=mutation_type,
                    arguments=mutation_arguments,
                    confirmations=ConfirmationRepository(engine),
                    checkpoints=RepositoryCheckpointStore(runs),
                )
                observe(
                    EventType.TOOL_REQUEST_SUCCEEDED,
                    "prepare_confirmation",
                    {"tool": mutation_type, "status": "prepared"},
                )
                publish_terminal_response(
                    context=prepared_context,
                    messages=messages,
                    runs=runs,
                    preferred_content=(
                        f"已生成操作预览：{preview.summary}。请在确认卡片中选择是否继续。"
                    ),
                    retryable=False,
                )
            elif routed.workflow_id in LOW_RISK_ROUTES:
                mutation_arguments = extract_low_risk_arguments(
                    routed.workflow_id, content, intent=routed.intent
                )
                low_risk_context = execute_low_risk(
                    context=routed_context,
                    route=routed.workflow_id,
                    arguments=mutation_arguments,
                    executions=MutationExecutionRepository(engine),
                    checkpoints=RepositoryCheckpointStore(runs),
                    handoffs=HandoffRepository(engine),
                    audit=AuditRepository(engine),
                ).context
                response = (
                    "已提交请求，系统已记录。"
                    if low_risk_context.status is RunStatus.COMPLETED
                    else "请求状态暂时无法确认，已转人工处理。"
                )
                publish_terminal_response(
                    context=low_risk_context,
                    messages=messages,
                    runs=runs,
                    preferred_content=response,
                    retryable=False,
                )
            else:
                raise MutationWorkflowError("UNKNOWN_MUTATION", "暂不支持该操作")
        except (MutationWorkflowError, LowRiskWorkflowError) as error:
            state = dict(routed_context.state)
            state.update({"mutation_error": error.code, "mutation_message": str(error)})
            missing_slots = tuple(getattr(error, "missing_slots", ()))
            if error.code == "MISSING_SLOTS":
                state["mutation_args"] = dict(mutation_arguments)
                state["missing_slots"] = list(missing_slots)
            target_status = (
                RunStatus.WAITING_USER if error.code == "MISSING_SLOTS" else RunStatus.WAITING_HUMAN
            )
            next_step = "collect_slots" if target_status is RunStatus.WAITING_USER else "terminal"
            event_type = (
                EventType.WAITING_FOR_USER
                if target_status is RunStatus.WAITING_USER
                else EventType.FAILED
            )
            handoff_id = None
            if target_status is RunStatus.WAITING_HUMAN:
                handoff_id = HandoffRepository(engine).create(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    actor_ref=actor_id,
                    reason_code=error.code,
                    operation=mutation_type,
                    details={
                        "mutation_error": error.code,
                        "message": str(error),
                        **(
                            {"order_id": str(mutation_arguments["order_id"])}
                            if mutation_arguments.get("order_id")
                            else {}
                        ),
                        **(
                            {"item_id": str(mutation_arguments["item_id"])}
                            if mutation_arguments.get("item_id")
                            else {}
                        ),
                    },
                )
                state["handoff_ticket_id"] = str(handoff_id)
            RepositoryCheckpointStore(runs).checkpoint(
                context=routed_context,
                status=target_status,
                next_step=next_step,
                state=state,
                events=(
                    DomainEvent(event_type=event_type, payload={"reason": error.code}),
                    *(
                        (DomainEvent(
                            event_type=EventType.HANDOFF_CREATED,
                            payload={"handoff_ticket_id": str(handoff_id), "reason": error.code},
                        ),)
                        if handoff_id
                        else ()
                    ),
                ),
            )
            if error.code == "MISSING_SLOTS":
                prompt = _missing_slot_prompt(
                    route=routed.workflow_id,
                    missing_slots=missing_slots,
                    arguments=mutation_arguments,
                )
                publish_terminal_response(
                    context=routed_context.model_copy(
                        update={"status": RunStatus.WAITING_USER, "state": state}
                    ),
                    messages=messages,
                    runs=runs,
                    preferred_content=prompt,
                    reason_code=error.code,
                    retryable=False,
                )
            elif handoff_id:
                prompt = "该请求需要人工审核，请查看右侧的人工处理窗口并选择审核结果。"
                publish_terminal_response(
                    context=routed_context.model_copy(
                        update={"status": RunStatus.WAITING_HUMAN, "state": state}
                    ),
                    messages=messages,
                    runs=runs,
                    preferred_content=prompt,
                    reason_code=error.code,
                    retryable=False,
                )

    except ModelGatewayError:
        decision = RouteDecision(outcome=RouteOutcome.HANDOFF, reason_code="CLASSIFIER_UNAVAILABLE")
        RunRoutingRepository(engine).select_route(
            context=context.model_copy(update={"status": RunStatus.ROUTING}), decision=decision
        )
        handoff_id = HandoffRepository(engine).create(
            run_id=run_id,
            tenant_id=tenant_id,
            actor_ref=actor_id,
            reason_code=decision.reason_code,
            operation=None,
            details={"message": "请求需要人工处理", "route_reason": decision.reason_code},
        )
        handoff_state = dict(context.state)
        handoff_state["handoff_ticket_id"] = str(handoff_id)
        RepositoryCheckpointStore(runs).checkpoint(
            context=context,
            status=RunStatus.WAITING_HUMAN,
            next_step="terminal",
            state=handoff_state,
            events=(
                DomainEvent(
                    event_type=EventType.HANDOFF_CREATED,
                    payload={
                        "handoff_ticket_id": str(handoff_id),
                        "reason": decision.reason_code,
                    },
                ),
            ),
        )
        publish_terminal_response(
            context=context.model_copy(
                update={"status": RunStatus.WAITING_HUMAN, "state": handoff_state}
            ),
            messages=messages,
            runs=runs,
            preferred_content="当前请求需要人工审核，请查看右侧的人工处理窗口并选择审核结果。",
            reason_code=decision.reason_code,
            retryable=False,
        )
        observe(
            EventType.MODEL_REQUEST_FAILED,
            "route_intent_risk",
            {"error_code": "CLASSIFIER_UNAVAILABLE"},
        )
    except Exception:
        _mark_failed(runs, messages, context, "UNEXPECTED_EXECUTION_ERROR", observe)


def execute_message_run(
    *,
    conversation_id: UUID,
    content: str,
    actor_id: str,
    run_id: UUID,
    tenant_id: str,
    settings: Settings,
) -> None:
    """Execute one Run and guarantee an outer failure response boundary."""
    runs = RunRepository(get_engine())
    messages = MessageRepository(get_engine())
    try:
        _execute_message_run(
            conversation_id=conversation_id,
            content=content,
            actor_id=actor_id,
            run_id=run_id,
            tenant_id=tenant_id,
            settings=settings,
        )
    except Exception:
        persisted = runs.load_latest_checkpoint(run_id=run_id, tenant_id=tenant_id)
        recovery_context = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            status=RunStatus.CREATED,
        )
        if isinstance(persisted, dict):
            try:
                recovery_context = RunContext.model_validate(persisted)
            except ValueError:
                pass
        try:
            _mark_failed(
                runs,
                messages,
                recovery_context,
                "UNEXPECTED_EXECUTION_ERROR",
                lambda *_args: None,
            )
        except Exception:
            # The worker must not crash-loop on its own recovery path. The
            # startup repair scan will retry the projection after persistence
            # becomes available.
            return


def _mark_failed(
    runs: RunRepository,
    messages: MessageRepository,
    context: RunContext,
    reason: str,
    observe: Any,
) -> None:
    run_id = context.run_id
    tenant_id = context.tenant_id
    with runs._engine.begin() as connection:  # noqa: SLF001 - narrow recovery boundary
        connection.execute(
            text(
                "UPDATE runtime.agent_runs SET status = 'failed', current_step = 'terminal', "
                "terminal_reason = :reason, updated_at = now(), row_version = row_version + 1 "
                "WHERE run_id = :run_id AND tenant_id = :tenant_id "
                "AND status NOT IN ('completed', 'failed', 'cancelled', 'expired')"
            ),
            {"run_id": run_id, "tenant_id": tenant_id, "reason": reason},
        )
    failed_context = context.model_copy(
        update={
            "status": RunStatus.FAILED,
            "state": {**context.state, "last_step_reason": reason},
        }
    )
    try:
        publish_terminal_response(
            context=failed_context,
            messages=messages,
            runs=runs,
            reason_code=reason,
        )
    except Exception:
        try:
            runs.append_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type=EventType.TERMINAL_RESPONSE_PUBLISH_FAILED,
                step_id="terminal",
                payload={"reason_code": reason},
            )
        except Exception:
            pass
    observe(EventType.FAILED, "terminal", {"reason": reason})

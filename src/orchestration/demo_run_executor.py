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
from src.evolution.failure_attribution import FailureAttributionService
from src.evolution.skill_retriever import select_skill_from_registry
from src.models.gateway import ModelGatewayError, OpenAICompatibleGateway
from src.orchestration.api_runtime import execute_readonly_run
from src.orchestration.confidence import calibrate_classification
from src.orchestration.conversational_fallback import response_for
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
from src.orchestration.risk_router import RiskAssessment, assess_request
from src.orchestration.route_catalog import intent_route_rules
from src.orchestration.router import IntentRouter, RouteDecision, RouteOutcome
from src.orchestration.terminal_response import publish_terminal_response
from src.protocols import (
    DomainEvent,
    EventType,
    Message,
    RequestDomain,
    RequestRiskLevel,
    ResponsePolicy,
    RiskHint,
    RoutingPromptView,
    RunContext,
    RunStatus,
)
from src.release.progressive_delivery import (
    TrafficAssignment,
    assign_traffic,
    build_release_comparison,
)
from src.repositories.audit import AuditRepository
from src.repositories.handoffs import HandoffRepository
from src.repositories.messages import MessageRepository
from src.repositories.model_invocations import ModelInvocationRepository
from src.repositories.mutations import ConfirmationRepository, MutationExecutionRepository
from src.repositories.releases import ReleaseRepository
from src.repositories.run_lifecycle import RunRoutingRepository
from src.repositories.runs import RunRepository
from src.repositories.skills import SkillRepository
from src.safety.responses import safe_response_for
from src.safety.router import SafetyRouter
from src.workflows.mutations import extract_arguments, hash_secret

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


def _record_release_assignment(
    *,
    engine: Any,
    context: RunContext,
    routed: RouteDecision,
    candidate_routed: RouteDecision | None = None,
    current_skill: str | None = None,
    candidate_skill: str | None = None,
    record_event: bool = True,
    risk_level: RequestRiskLevel,
    observe: Any,
) -> TrafficAssignment | None:
    """Record a safe release decision; never makes an unregistered candidate live."""

    try:
        releases = ReleaseRepository(engine)
        release = releases.latest_active(tenant_id=context.tenant_id)
        if release is None:
            return None
        route = routed.workflow_id
        write_route = bool(route and mutation_type_for_route(route))
        risk_hint = RiskHint.WRITE if write_route else RiskHint.READ_ONLY
        candidate_runtime_available = releases.runtime_available(
            tenant_id=context.tenant_id,
            version=str(release["candidate_version"]),
        )
        assignment = assign_traffic(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            run_id=str(context.run_id),
            conversation_id=str(context.conversation_id),
            current_version=str(release["current_version"]),
            candidate_version=str(release["candidate_version"]),
            stage=str(release["stage"]),
            status=str(release["status"]),
            risk_level=risk_level,
            risk_hint=risk_hint,
            candidate_runtime_available=candidate_runtime_available,
        )
        comparison = build_release_comparison(
            current_route=routed.workflow_id,
            candidate_route=(
                candidate_routed.workflow_id if candidate_routed is not None else None
            ),
            current_response_policy=routed.response_policy.value,
            candidate_response_policy=(
                candidate_routed.response_policy.value
                if candidate_routed is not None
                else None
            ),
            current_skill=current_skill,
            candidate_skill=candidate_skill,
            # Candidate execution is observation-only in Shadow; a cost
            # estimate is explicitly unknown until the candidate actually
            # produces a priced model invocation in an approved environment.
            estimated_cost_delta_microusd=None,
            candidate_runtime_available=candidate_runtime_available,
            candidate_execution_allowed=assignment.candidate_execution_allowed,
        )
        releases.record_assignment(
            tenant_id=context.tenant_id,
            release_id=UUID(str(release["release_id"])),
            run_id=context.run_id,
            actor_id=context.actor_id,
            conversation_id=context.conversation_id,
            assignment=assignment,
            risk_level=risk_level.value,
            risk_hint=risk_hint.value,
            comparison=comparison,
        )
        if record_event:
            observe(
                EventType.RELEASE_ASSIGNED,
                "release_assignment",
                {
                "release_id": str(release["release_id"]),
                "mode": assignment.mode,
                "selected_version": assignment.selected_version,
                "traffic_percent": assignment.traffic_percent,
                "bucket": assignment.bucket,
                "reason": assignment.reason,
                "current_route": comparison["current_route"],
                "candidate_route": comparison["candidate_route"],
                "current_response_policy": comparison["current_response_policy"],
                "candidate_response_policy": comparison["candidate_response_policy"],
                "current_skill": comparison["current_skill"],
                "candidate_skill": comparison["candidate_skill"],
                "estimated_cost_delta_microusd": comparison[
                    "estimated_cost_delta_microusd"
                ],
                "candidate_execution_allowed": comparison[
                    "candidate_execution_allowed"
                ],
                },
            )
        return assignment
    except Exception:
        # Release observability is auxiliary. The request remains governed by
        # the normal safety/router path when its control-plane table is down.
        return None


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
    try:
        runs.mark_dispatch_started(run_id=run_id, tenant_id=tenant_id)
    except Exception:
        # Timing metadata is best effort; lifecycle and user-visible recovery
        # remain authoritative if the observability column is unavailable.
        pass
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
        # SafetyRouter is the first decision boundary.  Deterministic P0
        # checks remain active even when the semantic V2 flag is disabled;
        # semantic triage can only escalate to a handoff and never grants a
        # business route.  The legacy risk assessment then supplies the
        # low-risk social/capability hints used by Router V2.
        safety_route = SafetyRouter(enabled=settings.enable_safety_router_v2).route(content)
        risk_assessment = assess_request(content)
        safety_handoff = safety_route.effective_disposition.value == "handoff"
        if safety_route.assessment.hard_block or safety_handoff:
            risk_assessment = RiskAssessment(
                domain=RequestDomain.UNKNOWN,
                risk_level=safety_route.assessment.risk_level,
                reason_code=safety_route.assessment.reason_code,
                hard_block=safety_route.assessment.hard_block,
                safety_category=safety_route.assessment.category,
            )
        observe(
            EventType.SAFETY_ROUTED,
            "safety_router",
            {
                "domain": risk_assessment.domain.value,
                "risk_level": risk_assessment.risk_level.value,
                "category": risk_assessment.safety_category.value,
                "disposition": safety_route.effective_disposition.value,
                "shadow_only": safety_route.shadow_only,
                "detector_version": safety_route.assessment.detector_version,
                "reason_code": risk_assessment.reason_code,
            },
        )
        if safety_route.assessment.hard_block:
            try:
                AuditRepository(engine).append(
                    tenant_id=tenant_id,
                    actor_ref="safety-router",
                    event_type="safety_p0_detected",
                    payload={
                        "run_id": str(run_id),
                        "category": safety_route.assessment.category.value,
                        "reason_code": safety_route.assessment.reason_code,
                        "detector_version": safety_route.assessment.detector_version,
                        "disposition": safety_route.effective_disposition.value,
                    },
                    payload_hash=hash_secret(
                        f"{run_id}:{safety_route.assessment.category.value}:"
                        f"{safety_route.assessment.reason_code}"
                    ),
                )
            except Exception:
                # The user-facing safety boundary remains fail-closed when the
                # auxiliary audit projection is temporarily unavailable.
                pass
        shadow_routed: RouteDecision | None = None
        current_routed_for_release: RouteDecision | None = None
        release_assignment: TrafficAssignment | None = None
        release_assignment_recorded = False
        if safety_handoff:
            routed = RouteDecision(
                outcome=RouteOutcome.HANDOFF,
                reason_code=risk_assessment.reason_code,
                response_policy=ResponsePolicy.HUMAN_HANDOFF,
                request_domain=risk_assessment.domain,
                request_risk_level=risk_assessment.risk_level,
            )
        elif (
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
            route_rules = intent_route_rules(
                routing_v2=settings.enable_routing_v2,
                conversational_fallback=settings.enable_conversational_fallback,
            )
            routing_prompt = RoutingPromptView(
                conversation=(Message(role="user", content=content),),
                allowed_intents=tuple(rule.intent for rule in route_rules),
            )
            candidate = IntentClassifier(
                gateway=OpenAICompatibleGateway(settings),
                invocations=ModelInvocationRepository(engine),
            ).classify(context=context, prompt=routing_prompt)
            candidate_updates: dict[str, object] = {}
            if (
                candidate.domain is RequestDomain.UNKNOWN
                and risk_assessment.domain is not RequestDomain.UNKNOWN
            ):
                candidate_updates["domain"] = risk_assessment.domain
            if (
                candidate.request_risk_level is RequestRiskLevel.UNKNOWN
                and risk_assessment.risk_level is not RequestRiskLevel.UNKNOWN
            ):
                candidate_updates["request_risk_level"] = risk_assessment.risk_level
            if candidate_updates:
                candidate = candidate.model_copy(update=candidate_updates)
            calibrated_confidence = calibrate_classification(candidate)
            observe(
                EventType.MODEL_REQUEST_SUCCEEDED,
                "route_intent_risk",
                {
                    "purpose": "routing",
                    "outcome": "classified",
                    "intent": candidate.intent,
                    "domain": candidate.domain.value,
                    "request_risk_level": candidate.request_risk_level.value,
                    "confidence": candidate.confidence,
                    "domain_confidence": calibrated_confidence.domain,
                    "risk_confidence": calibrated_confidence.risk,
                    "confidence_calibration_version": calibrated_confidence.version,
                    "alternative_count": len(candidate.alternatives),
                },
            )
            routed = IntentRouter(route_rules).decide(candidate)
            current_routed_for_release = routed
            shadow_rules = intent_route_rules(
                routing_v2=True,
                conversational_fallback=True,
            )
            shadow_routed = IntentRouter(shadow_rules).decide(candidate)
            diff_fields = tuple(
                field
                for field in (
                    "outcome",
                    "workflow_id",
                    "intent",
                    "reason_code",
                    "response_policy",
                    "request_domain",
                    "request_risk_level",
                )
                if getattr(routed, field) != getattr(shadow_routed, field)
            )
            observe(
                EventType.ROUTING_SHADOW_COMPARED,
                "route_intent_risk",
                {
                    "current_router": (
                        "v2"
                        if settings.enable_routing_v2 and settings.enable_conversational_fallback
                        else "v1"
                    ),
                    "shadow_router": "v2",
                    "current_outcome": routed.outcome.value,
                    "current_reason_code": routed.reason_code,
                    "current_intent": routed.intent,
                    "current_response_policy": routed.response_policy.value,
                    "shadow_outcome": shadow_routed.outcome.value,
                    "shadow_reason_code": shadow_routed.reason_code,
                    "shadow_intent": shadow_routed.intent,
                    "shadow_response_policy": shadow_routed.response_policy.value,
                    "different": bool(diff_fields),
                    "diff_fields": list(diff_fields),
                    "shadow_is_observation_only": True,
                },
            )
            release_assignment = _record_release_assignment(
                engine=engine,
                context=context,
                routed=routed,
                candidate_routed=shadow_routed,
                risk_level=risk_assessment.risk_level,
                observe=observe,
            )
            release_assignment_recorded = True
            if (
                release_assignment is not None
                and release_assignment.mode == "canary"
                and release_assignment.candidate_execution_allowed
                and shadow_routed is not None
                and shadow_routed.outcome is RouteOutcome.EXECUTE
            ):
                routed = shadow_routed
            routed_context = context.model_copy(update={"status": RunStatus.ROUTING})
            RunRoutingRepository(engine).select_route(context=routed_context, decision=routed)
        if not release_assignment_recorded:
            _record_release_assignment(
                engine=engine,
                context=context,
                routed=routed,
                candidate_routed=shadow_routed,
                risk_level=risk_assessment.risk_level,
                observe=observe,
            )
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
            handoff_state.update(
                {
                    "response_policy": routed.response_policy.value,
                    "request_domain": routed.request_domain.value,
                    "request_risk_level": routed.request_risk_level.value,
                }
            )
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
            try:
                FailureAttributionService(engine).record_run_outcome(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    status="waiting_human",
                    terminal_reason=routed.reason_code,
                    route=routed.workflow_id,
                )
            except Exception:
                pass
            prompt = (
                safe_response_for(risk_assessment.safety_category)
                if risk_assessment.hard_block
                else "该请求需要人工审核，请查看右侧的人工处理窗口并选择审核结果。"
            )
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

        if routed.outcome is RouteOutcome.ASK_USER:
            clarify_state = dict(context.state)
            clarify_state.update(
                {
                    "route_reason": routed.reason_code,
                    "response_policy": ResponsePolicy.ASK_USER.value,
                    "request_domain": routed.request_domain.value,
                    "request_risk_level": routed.request_risk_level.value,
                }
            )
            RepositoryCheckpointStore(runs).checkpoint(
                context=context,
                status=RunStatus.WAITING_USER,
                next_step="clarify",
                state=clarify_state,
                events=(
                    DomainEvent(
                        event_type=EventType.WAITING_FOR_USER,
                        payload={"reason": routed.reason_code},
                    ),
                ),
            )
            if routed.reason_code == "LOW_CLASSIFICATION_CONFIDENCE":
                try:
                    FailureAttributionService(engine).record_run_outcome(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        status="waiting_user",
                        terminal_reason=routed.reason_code,
                        route=routed.workflow_id,
                    )
                except Exception:
                    pass
            publish_terminal_response(
                context=context.model_copy(
                    update={"status": RunStatus.WAITING_USER, "state": clarify_state}
                ),
                messages=messages,
                runs=runs,
                preferred_content="我还不确定你的具体需求，可以补充一下你想查询或办理的事项吗？",
                reason_code=routed.reason_code,
                retryable=False,
            )
            return

        assert routed.execution_mode is not None
        assert routed.workflow_id is not None
        routed_state = dict(context.state)
        routed_state.update(
            {
                "intent": routed.intent or "",
                "route": routed.workflow_id,
                "response_policy": routed.response_policy.value,
                "request_domain": routed.request_domain.value,
                "request_risk_level": routed.request_risk_level.value,
            }
        )
        skill_matching_enabled = False
        if settings.enable_experience_skills:
            try:
                # A control-plane kill switch is checked per request.  If its
                # table is unavailable, ordinary routing continues without a
                # Skill rather than treating stale state as permission.
                skill_matching_enabled = SkillRepository(engine).matching_enabled(
                    tenant_id=tenant_id
                )
            except Exception:
                skill_matching_enabled = False
        if settings.enable_experience_skills and skill_matching_enabled:
            # Skill matching is an auditable, bounded side path.  Shadow mode
            # records a candidate without changing the current route or reply.
            match_mode = (
                "shadow"
                if settings.enable_skill_shadow
                else ("canary" if settings.enable_skill_canary else "active")
            )
            try:
                matched = select_skill_from_registry(
                    text_value=content,
                    tenant_id=tenant_id,
                    route=routed.workflow_id,
                    candidates_loader=lambda: list(
                        SkillRepository(engine).candidates_for_match(
                            tenant_id=tenant_id, mode=match_mode
                        )
                    ),
                    mode=match_mode,
                )
                if matched is not None:
                    routed_state.update(
                        {
                            "skill_id": matched.skill_id,
                            "skill_version_id": matched.skill_version_id,
                            "skill_match_mode": matched.mode,
                            "skill_match_score": matched.score,
                            "skill_strategy": matched.strategy_view,
                        }
                    )
                    observe(
                        EventType.SKILL_MATCHED,
                        "skill_match",
                        {
                            "skill_id": matched.skill_id,
                            "skill_version_id": matched.skill_version_id,
                            "mode": matched.mode,
                            "match_score": matched.score,
                        },
                    )
                    SkillRepository(engine).record_match(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        skill_id=UUID(matched.skill_id),
                        skill_version_id=UUID(matched.skill_version_id),
                        match_score=matched.score,
                        mode=matched.mode,
                    )
                    if release_assignment is not None and current_routed_for_release is not None:
                        _record_release_assignment(
                            engine=engine,
                            context=context,
                            routed=current_routed_for_release,
                            candidate_routed=shadow_routed,
                            current_skill=(
                                matched.skill_id
                                if matched.mode == "active"
                                or (
                                    matched.mode == "canary"
                                    and release_assignment.mode == "current"
                                )
                                else None
                            ),
                            candidate_skill=(
                                matched.skill_id
                                if matched.mode in {"shadow", "canary"}
                                else None
                            ),
                            record_event=False,
                            risk_level=risk_assessment.risk_level,
                            observe=observe,
                        )
            except Exception:
                # Registry unavailability falls back to ordinary routing and
                # must not weaken the deterministic safety boundary.
                pass
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
        if routed.response_policy.value in {"conversational_response", "graceful_unsupported"}:
            conversational_response = response_for(
                intent=routed.intent or "unsupported_low_risk",
                content=content,
            )
            completed_context = RepositoryCheckpointStore(runs).checkpoint(
                context=routed_context,
                status=RunStatus.COMPLETED,
                next_step="terminal",
                state=routed_state,
                events=(
                    DomainEvent(
                        event_type=EventType.STEP_COMPLETED,
                        payload={
                            "route": routed.workflow_id,
                            "response_policy": routed.response_policy.value,
                        },
                    ),
                ),
            )
            del completed_context
            publish_terminal_response(
                context=routed_context.model_copy(
                    update={"status": RunStatus.COMPLETED, "state": routed_state}
                ),
                messages=messages,
                runs=runs,
                preferred_content=conversational_response,
                retryable=False,
            )
            return
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
            mutation_handoff_id: UUID | None = None
            if target_status is RunStatus.WAITING_HUMAN:
                mutation_handoff_id = HandoffRepository(engine).create(
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
                state["handoff_ticket_id"] = str(mutation_handoff_id)
                try:
                    FailureAttributionService(engine).record_run_outcome(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        status="waiting_human",
                        terminal_reason=error.code,
                        route=routed_context.workflow_id,
                    )
                except Exception:
                    pass
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
        try:
            FailureAttributionService(engine).record_run_outcome(
                tenant_id=tenant_id,
                run_id=run_id,
                status="waiting_human",
                terminal_reason=decision.reason_code,
                route=decision.workflow_id,
            )
        except Exception:
            pass
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
                "terminal_at = COALESCE(terminal_at, now()), "
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
    # Failure learning is an auxiliary projection. A persistence outage here
    # must never turn a safe terminal response into a second runtime failure.
    try:
        FailureAttributionService(runs._engine).record_run_outcome(  # noqa: SLF001 - recovery boundary
            tenant_id=tenant_id,
            run_id=run_id,
            status="failed",
            terminal_reason=reason,
            route=str(context.state.get("route") or "terminal"),
        )
    except Exception:
        pass

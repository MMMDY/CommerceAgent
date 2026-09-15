"""Phase 0 FastAPI application factory."""

# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from apps.api.bootstrap import ReadinessDependencies
from src.agent.intent_classifier import IntentClassifier
from src.config import Settings, get_settings
from src.db import get_engine
from src.memory.session import build_session_memory
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
    confirm_mutation,
    mutation_type_for_route,
    prepare_mutation,
    reject_mutation,
)
from src.orchestration.persistence import RepositoryCheckpointStore
from src.orchestration.route_catalog import DEFAULT_INTENT_ROUTE_RULES
from src.orchestration.router import IntentRouter, RouteDecision, RouteOutcome
from src.orchestration.run_creation import RunCreationSpec
from src.protocols import DomainEvent, EventType, Message, RoutingPromptView, RunContext, RunStatus
from src.repositories.audit import AuditRepository
from src.repositories.conversations import Conversation, ConversationRepository
from src.repositories.handoffs import HandoffRepository
from src.repositories.knowledge import KnowledgeRepository
from src.repositories.memory import MemoryRepository, MemoryValidationError
from src.repositories.messages import MessageConflictError, MessageRecord, MessageRepository
from src.repositories.model_invocations import ModelInvocationRepository
from src.repositories.mutations import ConfirmationRepository, MutationExecutionRepository
from src.repositories.run_lifecycle import RunLifecycleRepository, RunRoutingRepository
from src.repositories.runs import RunRepository, RunSnapshot
from src.workflows.mutations import extract_arguments, hash_secret

DEMO_TENANT_ID = "demo-tenant"
EVAL_REPORT_ROOT = Path(__file__).resolve().parents[2] / "evals" / "reports"


class EvalRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judge: Literal["off", "on"] = "off"
    mode: Literal["debug", "release"] = "debug"
    repetitions: int = Field(default=1, ge=1, le=3)


class EvalRunSummary(BaseModel):
    eval_run_id: str
    status: str
    selected_cases: int = 0
    completed_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    judge: str = "off"
    mode: str = "debug"
    repetitions: int = 1


def _eval_report_paths(eval_run_id: str) -> tuple[Path, Path]:
    # IDs are generated UUIDs; reject path traversal before touching disk.
    try:
        UUID(eval_run_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="evaluation not found") from error
    directory = EVAL_REPORT_ROOT / eval_run_id
    return directory / "report.json", directory / "report.md"


def _execute_eval_report(eval_run_id: str, payload: EvalRunCreateRequest) -> None:
    """Run the single-concurrency harness in a background task.

    stdout is consumed by the task and only the sanitized report files are
    exposed through the API.
    """
    directory = EVAL_REPORT_ROOT / eval_run_id
    command = [sys.executable, "-m", "src.harness.runner", "--dataset", "evals/commerce_bench_zh/cases.jsonl", "--judge", payload.judge, "--mode", payload.mode, "--repetitions", str(payload.repetitions), "--output-dir", str(directory)]
    try:
        completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=3600, check=False)
        report_path = directory / "report.json"
        report = json.loads(completed.stdout.splitlines()[-1]) if completed.stdout.strip() else {"status": "failed"}
        report["eval_run_id"] = eval_run_id
        if completed.returncode != 0:
            report["status"] = "failed"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    except Exception:
        (directory / "report.json").write_text(json.dumps({"schema_version": "1.0", "eval_run_id": eval_run_id, "status": "failed", "judge": payload.judge, "mode": payload.mode, "repetitions": payload.repetitions, "selected_cases": 300, "completed_cases": 0, "passed_cases": 0, "failed_cases": 300, "results": []}, ensure_ascii=False), encoding="utf-8")


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(min_length=1, max_length=128)


class ConversationResponse(BaseModel):
    id: UUID
    status: str
    created_at: str

    @classmethod
    def from_domain(cls, conversation: Conversation) -> ConversationResponse:
        return cls(
            id=conversation.id,
            status=conversation.status,
            created_at=conversation.created_at.isoformat(),
        )


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=1, max_length=128)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    run_id: UUID | None
    role: str
    content: str
    sequence_no: int
    created_at: str

    @classmethod
    def from_domain(cls, message: MessageRecord) -> MessageResponse:
        return cls(
            id=message.message_id,
            conversation_id=message.conversation_id,
            run_id=message.run_id,
            role=message.role,
            content=message.content_redacted,
            sequence_no=message.sequence_no,
            created_at=message.created_at.isoformat(),
        )


class MessageSendResponse(BaseModel):
    message_id: UUID
    run_id: UUID
    run_status: str
    assistant_response: str | None = None
    waiting_action: str | None = None
    confirmation_token: str | None = None
    preview: dict[str, object] | None = None
    confirmation_expires_at: str | None = None
    token_refresh_required: bool = False


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(accept|reject)$")
    confirmation_token: str = Field(min_length=20, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ConfirmationRefreshResponse(BaseModel):
    run_id: UUID
    run_status: str
    confirmation_token: str
    preview: dict[str, object]
    expires_at: str


class ConfirmationResponse(BaseModel):
    run_id: UUID
    run_status: str
    accepted: bool
    assistant_response: str | None = None
    preview: dict[str, object] | None = None
    token_refresh_required: bool = False


class HandoffResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["verified_success", "verified_failure"]
    resolution_note: str = Field(min_length=1, max_length=500)


class HandoffResponse(BaseModel):
    ticket_id: UUID
    run_id: UUID
    status: str
    run_status: str
    reason_code: str
    resolution: str | None = None


class PreferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: str = Field(min_length=1, max_length=64)
    value: dict[str, object] = Field(min_length=1, max_length=8)
    ttl_seconds: int = Field(default=2_592_000, ge=60, le=31_536_000)


class MemoryFactResponse(BaseModel):
    fact_id: UUID
    fact_type: str
    value: dict[str, object]


class SessionMemoryResponse(BaseModel):
    session: dict[str, object]
    preferences: list[MemoryFactResponse]


class EvidenceResponse(BaseModel):
    evidence_id: str
    source_uri: str
    version: str
    excerpt: str


class RunResponse(BaseModel):
    run_id: UUID
    conversation_id: UUID
    status: str
    current_step: str
    step_count: int
    last_checkpoint_seq: int
    terminal_reason: str | None = None
    preview: dict[str, object] | None = None
    confirmation_expires_at: str | None = None
    token_refresh_required: bool = False


def _message_repository() -> MessageRepository:
    return MessageRepository(get_engine())


def _run_repository() -> RunRepository:
    return RunRepository(get_engine())


def _run_response(
    snapshot: RunSnapshot,
    *,
    run_id: UUID,
    conversation_id: UUID,
    preview: dict[str, object] | None = None,
    confirmation_expires_at: str | None = None,
) -> RunResponse:
    # Keep this conversion local so the API never exposes checkpoint internals.
    return RunResponse(
        run_id=run_id,
        conversation_id=conversation_id,
        status=snapshot.status,
        current_step=snapshot.current_step,
        step_count=snapshot.step_count,
        last_checkpoint_seq=snapshot.last_checkpoint_seq,
        terminal_reason=snapshot.terminal_reason,
        preview=preview if snapshot.status == RunStatus.WAITING_CONFIRMATION.value else None,
        confirmation_expires_at=(
            confirmation_expires_at if snapshot.status == RunStatus.WAITING_CONFIRMATION.value else None
        ),
        token_refresh_required=snapshot.status == RunStatus.WAITING_CONFIRMATION.value,
    )


def _checkpoint_context(*, run_id: UUID, actor_id: str) -> RunContext:
    repository = RunRepository(get_engine())
    state = repository.load_latest_checkpoint(run_id=run_id, tenant_id=DEMO_TENANT_ID)
    if state is None:
        raise HTTPException(status_code=409, detail="run_checkpoint_unavailable")
    try:
        context = RunContext.model_validate(state)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="run_checkpoint_invalid") from error
    if context.actor_id != actor_id or context.tenant_id != DEMO_TENANT_ID:
        raise HTTPException(status_code=404, detail="run_not_found")
    return context


def get_demo_actor(
    x_demo_actor: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> str:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    actor = x_demo_actor or "demo-user-001"
    if actor not in settings.demo_actors:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="actor_not_allowed")
    return actor


def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository(get_engine())


def _web_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"


def create_app(*, readiness: ReadinessDependencies | None = None) -> FastAPI:
    app = FastAPI(title="CommerceAgent", version="0.1.0")
    readiness_dependencies = readiness or ReadinessDependencies.default()

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        is_ready, reason = readiness_dependencies.check()
        if is_ready:
            return JSONResponse({"status": "ready"})
        return JSONResponse(
            {"status": "not_ready", "reason": reason},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.get("/v1/evals", response_model=list[EvalRunSummary])
    def list_evaluations(
        limit: int = 20,
        offset: int = 0,
        status_filter: str | None = None,
        actor_id: str = Depends(get_demo_actor),
    ) -> list[EvalRunSummary]:
        del actor_id
        limit = max(1, min(limit, 100)); offset = max(0, offset)
        if not EVAL_REPORT_ROOT.is_dir():
            return []
        summaries: list[EvalRunSummary] = []
        for report_path in sorted(EVAL_REPORT_ROOT.glob("*/report.json"), reverse=True):
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                eval_id = report_path.parent.name
                summary = EvalRunSummary(eval_run_id=eval_id, status=str(payload.get("status", "unknown")), selected_cases=int(payload.get("selected_cases", 0)), completed_cases=int(payload.get("completed_cases", 0)), passed_cases=int(payload.get("passed_cases", 0)), failed_cases=int(payload.get("failed_cases", 0)), judge=str(payload.get("judge", "off")), mode=str(payload.get("mode", "debug")), repetitions=int(payload.get("repetitions", 1)))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if status_filter and summary.status != status_filter:
                continue
            summaries.append(summary)
        return summaries[offset : offset + limit]

    @app.post("/v1/evals", response_model=EvalRunSummary, status_code=status.HTTP_202_ACCEPTED)
    def create_evaluation(payload: EvalRunCreateRequest, background_tasks: BackgroundTasks, actor_id: str = Depends(get_demo_actor)) -> EvalRunSummary:
        del actor_id
        if payload.mode == "release" and payload.judge != "on":
            raise HTTPException(status_code=400, detail="release mode requires judge")
        eval_id = str(uuid4())
        directory = EVAL_REPORT_ROOT / eval_id
        directory.mkdir(parents=True, exist_ok=False)
        report = {"schema_version": "1.0", "status": "queued", "judge": payload.judge, "mode": payload.mode, "repetitions": payload.repetitions, "selected_cases": 300, "completed_cases": 0, "passed_cases": 0, "failed_cases": 0, "results": []}
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        background_tasks.add_task(_execute_eval_report, eval_id, payload)
        return EvalRunSummary(eval_run_id=eval_id, **{k: report[k] for k in ("status", "selected_cases", "completed_cases", "passed_cases", "failed_cases", "judge", "mode", "repetitions")})

    @app.get("/v1/evals/{eval_run_id}")
    def get_evaluation(eval_run_id: str, actor_id: str = Depends(get_demo_actor)) -> dict[str, Any]:
        del actor_id
        report_path, _ = _eval_report_paths(eval_run_id)
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="evaluation not found")
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=500, detail="evaluation unavailable") from error
        # Reports contain only redacted traces and aggregate metrics.
        return payload

    @app.get("/v1/evals/{eval_run_id}/cases")
    def list_evaluation_cases(eval_run_id: str, limit: int = 50, offset: int = 0, track: str | None = None, failed_only: bool = False, actor_id: str = Depends(get_demo_actor)) -> dict[str, Any]:
        del actor_id
        report_path, _ = _eval_report_paths(eval_run_id)
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="evaluation not found")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        rows = payload.get("results", [])
        rows = [row for row in rows if (not track or row.get("track") == track) and (not failed_only or row.get("final_pass") is not True)]
        limit = max(1, min(limit, 200)); offset = max(0, offset)
        return {"total": len(rows), "items": rows[offset : offset + limit]}

    @app.post("/v1/evals/{eval_run_id}/cancel")
    def cancel_evaluation(eval_run_id: str, actor_id: str = Depends(get_demo_actor)) -> dict[str, str]:
        del actor_id
        report_path, _ = _eval_report_paths(eval_run_id)
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="evaluation not found")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if payload.get("status") in {"completed", "failed", "cancelled"}:
            return {"eval_run_id": eval_run_id, "status": str(payload.get("status"))}
        payload["status"] = "cancelled"
        report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {"eval_run_id": eval_run_id, "status": "cancelled"}

    @app.post(
        "/v1/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_conversation(
        payload: ConversationCreateRequest,
        actor_id: str = Depends(get_demo_actor),
        repository: ConversationRepository = Depends(get_conversation_repository),
    ) -> ConversationResponse:
        conversation = repository.create_or_get(
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
            client_request_id=payload.client_request_id,
        )
        return ConversationResponse.from_domain(conversation)

    @app.get("/v1/conversations", response_model=list[ConversationResponse])
    def list_conversations(
        actor_id: str = Depends(get_demo_actor),
        repository: ConversationRepository = Depends(get_conversation_repository),
    ) -> list[ConversationResponse]:
        return [
            ConversationResponse.from_domain(conversation)
            for conversation in repository.list_for_actor(
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
            )
        ]

    @app.get("/internal/v1/demo/scenarios")
    def demo_scenarios(actor_id: str = Depends(get_demo_actor)) -> list[dict[str, str]]:
        del actor_id
        return [
            {
                "id": "order_delivery",
                "label": "查订单与物流",
                "prompt": "查询我的订单 ORD-DEMO-001 当前状态和物流预计送达时间；请分别核对订单与物流信息后再回答。",
            },
            {"id": "product_info", "label": "查商品", "prompt": "TAH6206 支持什么蓝牙版本？"},
            {"id": "policy", "label": "查政策", "prompt": "请说明退款政策"},
        ]

    @app.get("/v1/conversations/{conversation_id}/memory", response_model=SessionMemoryResponse)
    def get_memory(
        conversation_id: UUID,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
    ) -> SessionMemoryResponse:
        try:
            records = messages.list_for_actor(
                conversation_id=conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
                limit=500,
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail="conversation_not_found") from error
        run = None
        with get_engine().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT run_id FROM runtime.agent_runs WHERE conversation_id = :conversation_id "
                    "AND tenant_id = :tenant_id AND actor_ref = :actor_id ORDER BY created_at DESC LIMIT 1"
                ),
                {
                    "conversation_id": conversation_id,
                    "tenant_id": DEMO_TENANT_ID,
                    "actor_id": actor_id,
                },
            ).first()
        if row is not None:
            run = RunRepository(get_engine()).load_run(
                run_id=row[0], tenant_id=DEMO_TENANT_ID, actor_id=actor_id
            )
        preferences = MemoryRepository(get_engine()).active_for_actor(
            tenant_id=DEMO_TENANT_ID, actor_ref=actor_id
        )
        return SessionMemoryResponse(
            session=build_session_memory(messages=records, run=run),
            preferences=[
                MemoryFactResponse(fact_id=item.fact_id, fact_type=item.fact_type, value=item.value)
                for item in preferences
                if isinstance(item.value, dict)
            ],
        )

    @app.post("/v1/memory/preferences", response_model=MemoryFactResponse, status_code=201)
    def create_preference(
        payload: PreferenceCreateRequest,
        actor_id: str = Depends(get_demo_actor),
    ) -> MemoryFactResponse:
        try:
            fact_id = MemoryRepository(get_engine()).upsert_preference(
                tenant_id=DEMO_TENANT_ID,
                actor_ref=actor_id,
                fact_type=payload.fact_type,
                value=payload.value,
                source_type="user",
                source_ref="api",
                confidence=1.0,
                observed_at=datetime.now(UTC),
                valid_until=datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds),
            )
        except MemoryValidationError as error:
            raise HTTPException(status_code=400, detail="invalid_preference") from error
        return MemoryFactResponse(fact_id=fact_id, fact_type=payload.fact_type, value=payload.value)

    @app.delete("/v1/memory/preferences/{fact_id}", status_code=204, response_class=Response)
    def delete_preference(fact_id: UUID, actor_id: str = Depends(get_demo_actor)) -> Response:
        deleted = MemoryRepository(get_engine()).delete(
            fact_id=fact_id, tenant_id=DEMO_TENANT_ID, actor_ref=actor_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="memory_not_found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/v1/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
    def list_messages(
        conversation_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
        actor_id: str = Depends(get_demo_actor),
        repository: MessageRepository = Depends(_message_repository),
    ) -> list[MessageResponse]:
        try:
            messages = repository.list_for_actor(
                conversation_id=conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid_message_cursor") from error
        return [MessageResponse.from_domain(message) for message in messages]

    @app.post(
        "/v1/conversations/{conversation_id}/messages",
        response_model=MessageSendResponse,
        status_code=202,
    )
    def send_message(
        conversation_id: UUID,
        payload: MessageCreateRequest,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
    ) -> MessageSendResponse:
        run_id = uuid4()
        assistant_response: str | None = None
        confirmation_token: str | None = None
        preview: dict[str, object] | None = None
        confirmation_expires_at: str | None = None
        token_refresh_required = False
        # Resolve client-message idempotency before reserving a new Run.  This
        # is important because a conversation may still have an unfinished
        # handoff/confirmation run and the DB intentionally permits only one
        # active run per conversation.
        message = messages.find_user_by_client_message_id(
            conversation_id=conversation_id,
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
            client_message_id=payload.client_message_id,
        )
        if message is None:
            if not messages.conversation_exists(
                conversation_id=conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
            ):
                raise HTTPException(status_code=404, detail="conversation_not_found")
            settings = get_settings()
            fingerprint = "|".join(
                (settings.model or "unconfigured", settings.api_base or "unconfigured")
            )
            context = RunContext(
                run_id=run_id,
                conversation_id=conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
                status=RunStatus.CREATED,
            )
            spec = RunCreationSpec(
                policy_version="phase3-readonly-v1",
                model_config_hash=f"sha256:{sha256(fingerprint.encode()).hexdigest()}",
                prompt_version="agent-v1",
                current_step="route",
                max_steps=6,
                deadline_at=datetime.now(UTC) + timedelta(seconds=60),
            )
            try:
                RunLifecycleRepository(get_engine()).create_run(context=context, spec=spec)
            except Exception as error:
                raise HTTPException(status_code=503, detail="run_creation_unavailable") from error
            try:
                message = messages.append_user(
                    conversation_id=conversation_id,
                    tenant_id=DEMO_TENANT_ID,
                    actor_id=actor_id,
                    content=payload.content,
                    client_message_id=payload.client_message_id,
                    run_id=run_id,
                )
            except MessageConflictError as error:
                # A concurrent request won the idempotency race.  The newly
                # created reservation is cancelled so it cannot block the
                # conversation's next request.
                RunLifecycleRepository(get_engine()).cancel_unstarted_run(
                    run_id=run_id,
                    tenant_id=DEMO_TENANT_ID,
                    reason="MESSAGE_IDEMPOTENCY_CONFLICT",
                )
                raise HTTPException(status_code=409, detail="client_message_id_conflict") from error
            except ValueError as error:
                raise HTTPException(status_code=404, detail="conversation_not_found") from error
        else:
            run_id = message.run_id or run_id
        if not message.created:
            if message.run_id is None:
                raise HTTPException(status_code=500, detail="message_run_missing")
            run_id = message.run_id
            existing_run = RunRepository(get_engine()).load_run(
                run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id
            )
            run_status = (
                existing_run.status if existing_run is not None else RunStatus.CREATED.value
            )
            waiting_action = (
                "human_handoff" if run_status == RunStatus.WAITING_HUMAN.value else None
            )
            if run_status == RunStatus.WAITING_CONFIRMATION.value:
                token_refresh_required = True
        else:
            try:
                routing_prompt = RoutingPromptView(
                    conversation=(Message(role="user", content=payload.content),),
                    allowed_intents=tuple(rule.intent for rule in DEFAULT_INTENT_ROUTE_RULES),
                )
                candidate = IntentClassifier(
                    gateway=OpenAICompatibleGateway(settings),
                    invocations=ModelInvocationRepository(get_engine()),
                ).classify(context=context, prompt=routing_prompt)
                routed = IntentRouter(DEFAULT_INTENT_ROUTE_RULES).decide(candidate)
                routed_context = context.model_copy(update={"status": RunStatus.ROUTING})
                RunRoutingRepository(get_engine()).select_route(
                    context=routed_context, decision=routed
                )
                if routed.outcome.value == "handoff":
                    run_status, waiting_action = RunStatus.WAITING_HUMAN.value, "human_handoff"
                else:
                    assert routed.execution_mode is not None
                    assert routed.workflow_id is not None
                    assert routed.workflow_version is not None
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
                            "state": {"intent": routed.intent or "", "route": routed.workflow_id},
                        }
                    )
                    run_status = (
                        RunStatus.RUNNING_READONLY.value
                        if routed.execution_mode.value == "readonly_loop"
                        else RunStatus.RUNNING_WORKFLOW.value
                    )
                    waiting_action = None
                    if routed.execution_mode.value == "readonly_loop":
                        try:
                            result = execute_readonly_run(
                                settings=settings,
                                context=routed_context,
                                route=routed.workflow_id,
                                messages=messages,
                                run_repository=RunRepository(get_engine()),
                            )
                            run_status = result.context.status.value
                            response = next(
                                (step.response for step in reversed(result.steps) if step.response),
                                None,
                            )
                            if response:
                                assistant_response = response
                                messages.append_assistant(
                                    conversation_id=conversation_id,
                                    tenant_id=DEMO_TENANT_ID,
                                    actor_id=actor_id,
                                    content=response,
                                    run_id=run_id,
                                )
                            if run_status == RunStatus.WAITING_HUMAN.value:
                                waiting_action = "human_handoff"
                        except Exception:
                            # A provider or adapter outage is represented as a
                            # safe handoff; the request never exposes internals.
                            run_status, waiting_action = (
                                RunStatus.WAITING_HUMAN.value,
                                "human_handoff",
                            )
                    elif run_status == RunStatus.RUNNING_WORKFLOW.value:
                        try:
                            mutation_type = mutation_type_for_route(routed.workflow_id)
                            if mutation_type is not None:
                                prepared_context, prepared_preview, token = prepare_mutation(
                                    context=routed_context,
                                    mutation_type=mutation_type,
                                    arguments=extract_arguments(mutation_type, payload.content),
                                    confirmations=ConfirmationRepository(get_engine()),
                                    checkpoints=RepositoryCheckpointStore(RunRepository(get_engine())),
                                )
                                run_status = prepared_context.status.value
                                preview = prepared_preview.as_public()
                                confirmation_token = token
                                confirmation_expires_at = str(
                                    prepared_context.state.get("mutation_expires_at", "")
                                ) or None
                                waiting_action = "confirmation_required"
                            elif routed.workflow_id in LOW_RISK_ROUTES:
                                low_risk_context = execute_low_risk(
                                    context=routed_context,
                                    route=routed.workflow_id,
                                    arguments=extract_low_risk_arguments(
                                        routed.workflow_id,
                                        payload.content,
                                        intent=routed.intent,
                                    ),
                                    executions=MutationExecutionRepository(get_engine()),
                                    checkpoints=RepositoryCheckpointStore(RunRepository(get_engine())),
                                    handoffs=HandoffRepository(get_engine()),
                                    audit=AuditRepository(get_engine()),
                                ).context
                                run_status = low_risk_context.status.value
                                waiting_action = (
                                    "human_handoff"
                                    if low_risk_context.status is RunStatus.WAITING_HUMAN
                                    else None
                                )
                                assistant_response = (
                                    "已提交请求，系统已记录。"
                                    if low_risk_context.status is RunStatus.COMPLETED
                                    else "请求状态暂时无法确认，已转人工处理。"
                                )
                                messages.append_assistant(
                                    conversation_id=conversation_id,
                                    tenant_id=DEMO_TENANT_ID,
                                    actor_id=actor_id,
                                    content=assistant_response,
                                    run_id=run_id,
                                )
                            else:
                                raise MutationWorkflowError("UNKNOWN_MUTATION", "暂不支持该操作")
                        except (MutationWorkflowError, LowRiskWorkflowError) as error:
                            state = dict(routed_context.state)
                            state.update({"mutation_error": error.code, "mutation_message": str(error)})
                            target_status = (
                                RunStatus.WAITING_USER
                                if error.code == "MISSING_SLOTS"
                                else RunStatus.WAITING_HUMAN
                            )
                            next_step = "collect_slots" if target_status is RunStatus.WAITING_USER else "terminal"
                            event_type = (
                                EventType.WAITING_FOR_USER
                                if target_status is RunStatus.WAITING_USER
                                else EventType.FAILED
                            )
                            try:
                                RepositoryCheckpointStore(RunRepository(get_engine())).checkpoint(
                                    context=routed_context,
                                    status=target_status,
                                    next_step=next_step,
                                    state=state,
                                    events=(DomainEvent(event_type=event_type, payload={"reason": error.code}),),
                                )
                            except Exception:
                                pass
                            run_status = target_status.value
                            waiting_action = (
                                "collect_slots"
                                if target_status is RunStatus.WAITING_USER
                                else "human_handoff"
                            )
            except ModelGatewayError:
                RunRoutingRepository(get_engine()).select_route(
                    context=context.model_copy(update={"status": RunStatus.ROUTING}),
                    decision=RouteDecision(
                        outcome=RouteOutcome.HANDOFF, reason_code="CLASSIFIER_UNAVAILABLE"
                    ),
                )
                run_status, waiting_action = RunStatus.WAITING_HUMAN.value, "human_handoff"
        return MessageSendResponse(
            message_id=message.message_id,
            run_id=run_id,
            run_status=run_status,
            assistant_response=assistant_response,
            waiting_action=waiting_action,
            confirmation_token=confirmation_token,
            preview=preview,
            confirmation_expires_at=confirmation_expires_at,
            token_refresh_required=token_refresh_required,
        )

    @app.post("/v1/runs/{run_id}/confirmations", response_model=ConfirmationResponse)
    def confirm_run(
        run_id: UUID,
        payload: ConfirmationRequest,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
    ) -> ConfirmationResponse:
        runs = RunRepository(get_engine())
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if snapshot.status != RunStatus.WAITING_CONFIRMATION.value:
            raise HTTPException(status_code=409, detail="run_not_waiting_confirmation")
        context = _checkpoint_context(run_id=run_id, actor_id=actor_id)
        confirmations = ConfirmationRepository(get_engine())
        checkpoints = RepositoryCheckpointStore(runs)
        try:
            if payload.decision == "reject":
                updated = reject_mutation(
                    context=context,
                    confirmations=confirmations,
                    checkpoints=checkpoints,
                    token_hash=hash_secret(payload.confirmation_token),
                )
                response_text = "已取消该操作，未产生任何业务变更。"
                accepted = False
            else:
                updated = confirm_mutation(
                    context=context,
                    token_plaintext=payload.confirmation_token,
                    idempotency_key=payload.idempotency_key,
                    confirmations=confirmations,
                    executions=MutationExecutionRepository(get_engine()),
                    checkpoints=checkpoints,
                    handoffs=HandoffRepository(get_engine()),
                    audit=AuditRepository(get_engine()),
                )
                accepted = updated.status is RunStatus.COMPLETED
                response_text = (
                    "操作已提交并完成状态校验。"
                    if accepted
                    else "操作状态暂时无法确认，已转人工处理。"
                )
        except MutationWorkflowError as error:
            status_code = 409 if error.code in {"CONFIRMATION_UNAVAILABLE", "CONFIRMATION_CONFLICT", "PREVIEW_CHANGED"} else 400
            raise HTTPException(status_code=status_code, detail=error.code) from error
        try:
            messages.append_assistant(
                conversation_id=context.conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
                content=response_text,
                run_id=run_id,
            )
        except Exception:
            # The durable run remains authoritative even if message projection
            # is temporarily unavailable.
            pass
        return ConfirmationResponse(
            run_id=run_id,
            run_status=updated.status.value,
            accepted=accepted,
            assistant_response=response_text,
        )

    @app.post("/v1/runs/{run_id}/confirmations/refresh", response_model=ConfirmationRefreshResponse)
    def refresh_confirmation(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
    ) -> ConfirmationRefreshResponse:
        from src.orchestration.mutation_workflow import refresh_mutation_token

        runs = RunRepository(get_engine())
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if snapshot.status != RunStatus.WAITING_CONFIRMATION.value:
            raise HTTPException(status_code=409, detail="run_not_waiting_confirmation")
        context = _checkpoint_context(run_id=run_id, actor_id=actor_id)
        try:
            token, expires_at, public_preview = refresh_mutation_token(
                context=context,
                confirmations=ConfirmationRepository(get_engine()),
                checkpoints=RepositoryCheckpointStore(runs),
            )
        except MutationWorkflowError as error:
            raise HTTPException(status_code=409, detail=error.code) from error
        return ConfirmationRefreshResponse(
            run_id=run_id,
            run_status=RunStatus.WAITING_CONFIRMATION.value,
            confirmation_token=token,
            preview=public_preview,
            expires_at=expires_at,
        )

    @app.post("/internal/v1/handoffs/{ticket_id}/resolve", response_model=HandoffResponse)
    def resolve_handoff(
        ticket_id: UUID,
        payload: HandoffResolveRequest,
        actor_id: str = Depends(get_demo_actor),
    ) -> HandoffResponse:
        handoffs = HandoffRepository(get_engine())
        ticket = handoffs.get_for_actor(
            ticket_id=ticket_id, tenant_id=DEMO_TENANT_ID, actor_ref=actor_id
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="handoff_not_found")
        if ticket.status != "open":
            raise HTTPException(status_code=409, detail="handoff_already_resolved")
        runs = RunRepository(get_engine())
        snapshot = runs.load_run(
            run_id=ticket.run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        context = _checkpoint_context(run_id=ticket.run_id, actor_id=actor_id)
        if context.status is not RunStatus.WAITING_HUMAN:
            raise HTTPException(status_code=409, detail="run_not_waiting_human")
        target = (
            RunStatus.COMPLETED
            if payload.outcome == "verified_success"
            else RunStatus.FAILED
        )
        state = dict(context.state)
        state["handoff_resolution"] = payload.outcome
        state["handoff_resolution_note"] = payload.resolution_note
        state["mutation_outcome"] = payload.outcome
        RepositoryCheckpointStore(runs).checkpoint(
            context=context,
            status=target,
            next_step="terminal",
            state=state,
            events=(
                DomainEvent(
                    event_type=EventType.HANDOFF_RESOLVED,
                    payload={"ticket_id": str(ticket_id), "outcome": payload.outcome},
                ),
            ),
        )
        resolved = handoffs.resolve(
            ticket_id=ticket_id,
            tenant_id=DEMO_TENANT_ID,
            resolution=payload.resolution_note,
        )
        if resolved is None:
            raise HTTPException(status_code=409, detail="handoff_resolution_conflict")
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=actor_id,
            event_type="mutation_handoff_resolved",
            payload={"ticket_id": str(ticket_id), "run_id": str(ticket.run_id), "outcome": payload.outcome},
            payload_hash=hash_secret(f"{ticket_id}:{payload.outcome}:{payload.resolution_note}"),
        )
        return HandoffResponse(
            ticket_id=ticket_id,
            run_id=ticket.run_id,
            status=resolved.status,
            run_status=target.value,
            reason_code=ticket.reason_code,
            resolution=resolved.resolution,
        )

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunResponse)
    def cancel_run(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
    ) -> RunResponse:
        runs = RunRepository(get_engine())
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        context = _checkpoint_context(run_id=run_id, actor_id=actor_id)
        if context.status not in {RunStatus.WAITING_CONFIRMATION, RunStatus.WAITING_USER}:
            raise HTTPException(status_code=409, detail="run_not_cancellable")
        state = dict(context.state)
        state["mutation_outcome"] = "cancelled"
        preview_hash_value = state.get("mutation_preview_hash")
        if isinstance(preview_hash_value, str):
            try:
                ConfirmationRepository(get_engine()).invalidate_waiting(
                    run_id=run_id,
                    tenant_id=DEMO_TENANT_ID,
                    actor_ref=actor_id,
                    expected_preview_hash=preview_hash_value,
                )
            except Exception:
                # The run checkpoint is authoritative; a consumed/expired
                # token is already unable to advance the cancelled run.
                pass
        checkpoints = RepositoryCheckpointStore(runs)
        version = checkpoints.checkpoint(
            context=context,
            status=RunStatus.CANCELLED,
            next_step="terminal",
            state=state,
            events=(DomainEvent(event_type=EventType.FAILED, payload={"reason": "cancelled_by_user"}),),
        )
        updated = replace(
            snapshot,
            status=RunStatus.CANCELLED.value,
            step_count=snapshot.step_count + 1,
            row_version=version,
        )
        return _run_response(updated, run_id=run_id, conversation_id=snapshot.conversation_id or context.conversation_id)

    @app.get("/v1/runs/{run_id}", response_model=RunResponse)
    def get_run(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> RunResponse:
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if snapshot.conversation_id is None:
            raise HTTPException(status_code=500, detail="run_data_invalid")
        checkpoint = runs.load_latest_checkpoint(run_id=run_id, tenant_id=DEMO_TENANT_ID)
        raw_preview = checkpoint.get("state", {}).get("mutation_preview") if checkpoint else None
        preview = raw_preview if isinstance(raw_preview, dict) else None
        raw_expiry = checkpoint.get("state", {}).get("mutation_expires_at") if checkpoint else None
        expiry = raw_expiry if isinstance(raw_expiry, str) else None
        return _run_response(
            snapshot,
            run_id=run_id,
            conversation_id=snapshot.conversation_id,
            preview=preview,
            confirmation_expires_at=expiry,
        )

    @app.get("/v1/runs/{run_id}/events")
    def get_run_events(
        run_id: UUID,
        after_sequence: int = 0,
        limit: int = 200,
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> list[dict[str, object]]:
        if runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id) is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        try:
            events = runs.replay_events(
                run_id=run_id,
                tenant_id=DEMO_TENANT_ID,
                after_sequence=after_sequence,
                limit=limit,
                actor_id=actor_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid_event_cursor") from error
        return [
            {
                "id": event.sequence,
                "type": event.event.event_type.value,
                "step_id": event.step_id,
                "payload": event.event.payload,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ]

    @app.get("/v1/runs/{run_id}/evidence", response_model=list[EvidenceResponse])
    def get_run_evidence(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> list[EvidenceResponse]:
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        # Expose only citations selected in the final validated response, not
        # every candidate returned by retrieval.
        raw_ids: list[object] = []
        for event in runs.replay_events(
            run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id
        ):
            if event.event.event_type is EventType.STEP_COMPLETED:
                candidate = event.event.payload.get("evidence_ids")
                if isinstance(candidate, list):
                    raw_ids = candidate
        evidence_ids = tuple(item for item in raw_ids if isinstance(item, str))
        evidence = KnowledgeRepository(get_engine()).evidence_for_ids(
            tenant_id=DEMO_TENANT_ID, access_level="customer", evidence_ids=evidence_ids
        )
        return [
            EvidenceResponse(
                evidence_id=item.evidence_id,
                source_uri=item.source_uri,
                version=item.version,
                excerpt=item.excerpt,
            )
            for item in evidence
        ]

    @app.get("/v1/conversations/{conversation_id}/stream")
    def stream_conversation(
        conversation_id: UUID,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> StreamingResponse:
        try:
            after = int(last_event_id or "0")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid_event_cursor") from error

        def events() -> Iterator[str]:
            # A bounded, replay-oriented stream: clients reconnect with the last
            # numeric event ID; the server remains the source of truth.
            conversations = ConversationRepository(get_engine()).list_for_actor(
                tenant_id=DEMO_TENANT_ID, actor_id=actor_id
            )
            if not any(item.id == conversation_id for item in conversations):
                return
            for conversation in conversations:
                del conversation
            # Runs are discovered by the event join through a bounded query.
            with get_engine().connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT run_id FROM runtime.agent_runs WHERE conversation_id = :conversation_id "
                        "AND tenant_id = :tenant_id AND actor_ref = :actor_id ORDER BY created_at DESC LIMIT 1"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": DEMO_TENANT_ID,
                        "actor_id": actor_id,
                    },
                ).all()
            if not rows:
                yield ": heartbeat\n\n"
                return
            emitted = False
            for event in runs.replay_events(
                run_id=rows[0][0], tenant_id=DEMO_TENANT_ID, actor_id=actor_id, after_sequence=after
            ):
                emitted = True
                payload = json.dumps(event.event.payload, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.sequence}\nevent: {event.event.event_type.value}\ndata: {payload}\n\n"
            if not emitted:
                yield ": heartbeat\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    web_dist = _web_dist()
    assets = web_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> FileResponse:
        del path, request
        index = web_dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="web_build_not_found")

    return app


app = create_app()

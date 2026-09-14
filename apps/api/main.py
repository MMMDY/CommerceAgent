"""Phase 0 FastAPI application factory."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from apps.api.bootstrap import ReadinessDependencies
from src.agent.intent_classifier import IntentClassifier
from src.config import Settings, get_settings
from src.db import get_engine
from src.models.gateway import ModelGatewayError, OpenAICompatibleGateway
from src.orchestration.route_catalog import DEFAULT_INTENT_ROUTE_RULES
from src.orchestration.router import IntentRouter, RouteDecision, RouteOutcome
from src.orchestration.run_creation import RunCreationSpec
from src.protocols import Message, RoutingPromptView, RunContext, RunStatus
from src.repositories.conversations import Conversation, ConversationRepository
from src.repositories.messages import MessageConflictError, MessageRecord, MessageRepository
from src.repositories.run_lifecycle import RunLifecycleRepository, RunRoutingRepository
from src.repositories.runs import RunRepository, RunSnapshot

DEMO_TENANT_ID = "demo-tenant"


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
        return cls(id=message.message_id, conversation_id=message.conversation_id, run_id=message.run_id,
                   role=message.role, content=message.content_redacted, sequence_no=message.sequence_no,
                   created_at=message.created_at.isoformat())


class MessageSendResponse(BaseModel):
    message_id: UUID
    run_id: UUID
    run_status: str
    assistant_response: str | None = None
    waiting_action: str | None = None


class RunResponse(BaseModel):
    run_id: UUID
    conversation_id: UUID
    status: str
    current_step: str
    step_count: int
    last_checkpoint_seq: int
    terminal_reason: str | None = None


def _message_repository() -> MessageRepository:
    return MessageRepository(get_engine())


def _run_repository() -> RunRepository:
    return RunRepository(get_engine())


def _run_response(snapshot: RunSnapshot, *, run_id: UUID, conversation_id: UUID) -> RunResponse:
    # Keep this conversion local so the API never exposes checkpoint internals.
    return RunResponse(
        run_id=run_id, conversation_id=conversation_id, status=snapshot.status,
        current_step=snapshot.current_step, step_count=snapshot.step_count,
        last_checkpoint_seq=snapshot.last_checkpoint_seq, terminal_reason=snapshot.terminal_reason,
    )


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
                conversation_id=conversation_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id,
                after_sequence=after_sequence, limit=limit,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid_message_cursor") from error
        return [MessageResponse.from_domain(message) for message in messages]

    @app.post("/v1/conversations/{conversation_id}/messages", response_model=MessageSendResponse, status_code=202)
    def send_message(
        conversation_id: UUID,
        payload: MessageCreateRequest,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
    ) -> MessageSendResponse:
        run_id = uuid4()
        try:
            message = messages.append_user(
                conversation_id=conversation_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id,
                content=payload.content, client_message_id=payload.client_message_id, run_id=run_id,
            )
        except MessageConflictError as error:
            raise HTTPException(status_code=409, detail="client_message_id_conflict") from error
        except ValueError as error:
            raise HTTPException(status_code=404, detail="conversation_not_found") from error
        if not message.created:
            if message.run_id is None:
                raise HTTPException(status_code=500, detail="message_run_missing")
            run_id = message.run_id
            existing_run = RunRepository(get_engine()).load_run(
                run_id=run_id, tenant_id=DEMO_TENANT_ID
            )
            run_status = existing_run.status if existing_run is not None else RunStatus.CREATED.value
            waiting_action = "human_handoff" if run_status == RunStatus.WAITING_HUMAN.value else None
        else:
            settings = get_settings()
            fingerprint = "|".join((settings.model or "unconfigured", settings.api_base or "unconfigured"))
            context = RunContext(
                run_id=run_id, conversation_id=conversation_id, tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id, status=RunStatus.CREATED,
            )
            spec = RunCreationSpec(
                policy_version="phase3-readonly-v1",
                model_config_hash=f"sha256:{sha256(fingerprint.encode()).hexdigest()}",
                prompt_version="agent-v1", current_step="route", max_steps=6,
                deadline_at=datetime.now(UTC) + timedelta(seconds=60),
            )
            try:
                RunLifecycleRepository(get_engine()).create_run(context=context, spec=spec)
            except Exception as error:
                raise HTTPException(status_code=503, detail="run_creation_unavailable") from error
            try:
                routing_prompt = RoutingPromptView(
                    conversation=(Message(role="user", content=payload.content),),
                    allowed_intents=tuple(rule.intent for rule in DEFAULT_INTENT_ROUTE_RULES),
                )
                candidate = IntentClassifier(gateway=OpenAICompatibleGateway(settings)).classify(
                    context=context, prompt=routing_prompt
                )
                routed = IntentRouter(DEFAULT_INTENT_ROUTE_RULES).decide(candidate)
                routed_context = context.model_copy(update={"status": RunStatus.ROUTING})
                RunRoutingRepository(get_engine()).select_route(context=routed_context, decision=routed)
                if routed.outcome.value == "handoff":
                    run_status, waiting_action = RunStatus.WAITING_HUMAN.value, "human_handoff"
                else:
                    assert routed.execution_mode is not None
                    run_status = (
                        RunStatus.RUNNING_READONLY.value
                        if routed.execution_mode.value == "readonly_loop"
                        else RunStatus.RUNNING_WORKFLOW.value
                    )
                    waiting_action = None
            except ModelGatewayError:
                RunRoutingRepository(get_engine()).select_route(
                    context=context.model_copy(update={"status": RunStatus.ROUTING}),
                    decision=RouteDecision(outcome=RouteOutcome.HANDOFF, reason_code="CLASSIFIER_UNAVAILABLE"),
                )
                run_status, waiting_action = RunStatus.WAITING_HUMAN.value, "human_handoff"
        return MessageSendResponse(message_id=message.message_id, run_id=run_id, run_status=run_status, waiting_action=waiting_action)

    @app.get("/v1/runs/{run_id}", response_model=RunResponse)
    def get_run(
        run_id: UUID, actor_id: str = Depends(get_demo_actor), runs: RunRepository = Depends(_run_repository),
    ) -> RunResponse:
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if snapshot.conversation_id is None:
            raise HTTPException(status_code=500, detail="run_data_invalid")
        return _run_response(snapshot, run_id=run_id, conversation_id=snapshot.conversation_id)

    @app.get("/v1/runs/{run_id}/events")
    def get_run_events(
        run_id: UUID, after_sequence: int = 0, limit: int = 200,
        actor_id: str = Depends(get_demo_actor), runs: RunRepository = Depends(_run_repository),
    ) -> list[dict[str, object]]:
        if runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID) is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        try:
            events = runs.replay_events(run_id=run_id, tenant_id=DEMO_TENANT_ID,
                                        after_sequence=after_sequence, limit=limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid_event_cursor") from error
        return [{"id": event.sequence, "type": event.event.event_type.value,
                 "step_id": event.step_id, "payload": event.event.payload,
                 "occurred_at": event.occurred_at.isoformat()} for event in events]

    @app.get("/v1/conversations/{conversation_id}/stream")
    def stream_conversation(
        conversation_id: UUID, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        actor_id: str = Depends(get_demo_actor), runs: RunRepository = Depends(_run_repository),
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
                rows = connection.execute(text(
                    "SELECT run_id FROM runtime.agent_runs WHERE conversation_id = :conversation_id "
                    "AND tenant_id = :tenant_id ORDER BY created_at DESC LIMIT 1"
                ), {"conversation_id": conversation_id, "tenant_id": DEMO_TENANT_ID}).all()
            if not rows:
                yield ": heartbeat\\n\\n"
                return
            emitted = False
            for event in runs.replay_events(
                run_id=rows[0][0], tenant_id=DEMO_TENANT_ID, after_sequence=after
            ):
                emitted = True
                payload = json.dumps(event.event.payload, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.sequence}\\nevent: {event.event.event_type.value}\\ndata: {payload}\\n\\n"
            if not emitted:
                yield ": heartbeat\\n\\n"

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

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

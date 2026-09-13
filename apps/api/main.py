"""Phase 0 FastAPI application factory."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings, get_settings
from src.db import check_ready, get_engine
from src.repositories.conversations import Conversation, ConversationRepository

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


def create_app() -> FastAPI:
    app = FastAPI(title="CommerceAgent", version="0.1.0")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        is_ready, reason = check_ready()
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

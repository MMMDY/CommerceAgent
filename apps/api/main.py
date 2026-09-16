"""Phase 0 FastAPI application factory."""

# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from apps.api.bootstrap import ReadinessDependencies
from src.config import Settings, get_settings
from src.db import get_engine
from src.harness.resources import InsufficientDiskError, ensure_disk_budget
from src.memory.session import build_session_memory
from src.orchestration.demo_run_executor import execute_message_run
from src.orchestration.mutation_workflow import (
    MutationWorkflowError,
    confirm_mutation,
    reject_mutation,
)
from src.orchestration.persistence import RepositoryCheckpointStore
from src.orchestration.run_creation import RunCreationSpec
from src.orchestration.state_machine import (
    STATUS_DESCRIPTIONS,
    STATUS_LABELS,
    allowed_actions,
    state_machine_definition,
)
from src.orchestration.terminal_response import publish_terminal_response
from src.protocols import DomainEvent, EventType, RunContext, RunStatus
from src.repositories.audit import AuditRepository
from src.repositories.conversations import Conversation, ConversationRepository
from src.repositories.handoffs import HandoffRepository
from src.repositories.knowledge import KnowledgeRepository
from src.repositories.memory import MemoryRepository, MemoryValidationError
from src.repositories.messages import MessageConflictError, MessageRecord, MessageRepository
from src.repositories.mutations import ConfirmationRepository, MutationExecutionRepository
from src.repositories.run_lifecycle import (
    ActiveRunConflictError,
    RunLifecycleRepository,
)
from src.repositories.runs import RunRepository, RunSnapshot
from src.telemetry.lifecycle import ShutdownGate
from src.telemetry.metrics import Metrics
from src.workflows.mutations import hash_secret

DEMO_TENANT_ID = "demo-tenant"
EVAL_REPORT_ROOT = Path(__file__).resolve().parents[2] / "evals" / "reports"
_EVAL_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_EVAL_PROCESS_LOCK = Lock()


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
    command = [
        sys.executable,
        "-m",
        "src.harness.runner",
        "--dataset",
        "evals/commerce_bench_zh/cases.jsonl",
        "--judge",
        payload.judge,
        "--mode",
        payload.mode,
        "--repetitions",
        str(payload.repetitions),
        "--eval-run-id",
        eval_run_id,
        "--output-dir",
        str(directory),
    ]
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[2],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with _EVAL_PROCESS_LOCK:
            _EVAL_PROCESSES[eval_run_id] = process
        stdout, stderr = process.communicate(timeout=3600)
        report_path = directory / "report.json"
        report = json.loads(stdout.splitlines()[-1]) if stdout.strip() else {"status": "failed"}
        report["eval_run_id"] = eval_run_id
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if existing.get("status") == "cancelled":
            return
        if process.returncode != 0:
            report["status"] = "failed"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()
        (directory / "report.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "eval_run_id": eval_run_id,
                    "status": "failed",
                    "error": "evaluation_timeout",
                    "results": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        (directory / "report.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "eval_run_id": eval_run_id,
                    "status": "failed",
                    "judge": payload.judge,
                    "mode": payload.mode,
                    "repetitions": payload.repetitions,
                    "selected_cases": 300,
                    "completed_cases": 0,
                    "passed_cases": 0,
                    "failed_cases": 300,
                    "results": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    finally:
        with _EVAL_PROCESS_LOCK:
            _EVAL_PROCESSES.pop(eval_run_id, None)


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


class RetryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(min_length=8, max_length=128)


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


class HumanReviewResponse(BaseModel):
    ticket_id: UUID
    run_id: UUID
    status: str
    reason_code: str
    operation: str | None = None
    details: dict[str, object]
    created_at: str
    resolved_at: str | None = None
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
    allowed_actions: tuple[str, ...] = ()
    status_label: str = ""
    status_description: str = ""
    retryable: bool = False


class ActiveRunResponse(BaseModel):
    run: RunResponse | None = None


class StateMachineResponse(BaseModel):
    states: list[dict[str, object]]


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
            confirmation_expires_at
            if snapshot.status == RunStatus.WAITING_CONFIRMATION.value
            else None
        ),
        token_refresh_required=snapshot.status == RunStatus.WAITING_CONFIRMATION.value,
        allowed_actions=allowed_actions(RunStatus(snapshot.status)),
        status_label=STATUS_LABELS[RunStatus(snapshot.status)],
        status_description=(
            f"{STATUS_DESCRIPTIONS[RunStatus(snapshot.status)]}，原因：{snapshot.terminal_reason}"
            if snapshot.status == RunStatus.FAILED.value and snapshot.terminal_reason
            else STATUS_DESCRIPTIONS[RunStatus(snapshot.status)]
        ),
        retryable="retry" in allowed_actions(RunStatus(snapshot.status)),
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


def _repair_missing_terminal_responses(*, tenant_id: str, limit: int = 100) -> None:
    """Backfill user-visible replies for terminal Runs from before this fix."""
    runs = RunRepository(get_engine())
    messages = MessageRepository(get_engine())
    for snapshot in runs.terminal_runs_without_response(tenant_id=tenant_id, limit=limit):
        if snapshot.conversation_id is None:
            continue
        checkpoint = runs.load_latest_checkpoint(run_id=snapshot.run_id, tenant_id=tenant_id)
        state = checkpoint.get("state", {}) if isinstance(checkpoint, dict) else {}
        context_data = dict(checkpoint) if isinstance(checkpoint, dict) else {}
        context_data.update(
            {
                "run_id": snapshot.run_id,
                "conversation_id": snapshot.conversation_id,
                "tenant_id": tenant_id,
                "actor_id": runs.actor_for_run(run_id=snapshot.run_id, tenant_id=tenant_id),
                "status": snapshot.status,
                "state": state if isinstance(state, dict) else {},
            }
        )
        try:
            context = RunContext.model_validate(context_data)
            publish_terminal_response(context=context, messages=messages, runs=runs)
        except Exception:
            # A malformed legacy checkpoint remains visible for manual repair;
            # one bad record must not prevent other Runs from being repaired.
            continue


def get_demo_actor(
    x_demo_actor: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> str:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    actor = x_demo_actor or "demo-user-001"
    if actor not in settings.demo_actors:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="actor_not_allowed")
    return actor


def require_admission(request: Request) -> Iterator[None]:
    """Reject new runs once graceful shutdown has begun."""

    gate: ShutdownGate = request.app.state.shutdown_gate
    metrics: Metrics = request.app.state.metrics
    with gate.admission() as accepted:
        if not accepted:
            raise HTTPException(status_code=503, detail="service_draining")
        metrics.increment("requests_admitted")
        yield


def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository(get_engine())


def _web_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"


def create_app(*, readiness: ReadinessDependencies | None = None) -> FastAPI:
    app = FastAPI(title="CommerceAgent", version="0.1.0")
    app.state.shutdown_gate = ShutdownGate()
    app.state.metrics = Metrics()
    app.state.run_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="commerce-agent-run"
    )
    readiness_dependencies = readiness or ReadinessDependencies.default()

    @app.on_event("shutdown")
    def graceful_shutdown() -> None:
        gate: ShutdownGate = app.state.shutdown_gate
        gate.stop_accepting()
        gate.wait_for_idle(timeout=5.0)
        app.state.run_executor.shutdown(wait=True, cancel_futures=False)

    @app.on_event("startup")
    def recover_active_runs() -> None:
        """Reattach non-terminal demo runs after a single-process restart."""

        try:
            engine = get_engine()
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE runtime.agent_runs SET status = 'expired', current_step = 'terminal', "
                        "terminal_reason = 'DEADLINE_EXCEEDED_DURING_RESTART', updated_at = now(), "
                        "row_version = row_version + 1 WHERE tenant_id = :tenant_id "
                        "AND status IN ('created', 'routing', 'running_readonly', 'running_workflow') "
                        "AND deadline_at <= now()"
                    ),
                    {"tenant_id": DEMO_TENANT_ID},
                )
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT run_id, conversation_id, actor_ref, status, deadline_at "
                        "FROM runtime.agent_runs WHERE tenant_id = :tenant_id "
                        "AND status IN ('created', 'routing', 'running_readonly', 'running_workflow') "
                        "AND deadline_at > now()"
                    ),
                    {"tenant_id": DEMO_TENANT_ID},
                ).all()
            settings = get_settings()
            messages = MessageRepository(engine)
            _repair_missing_terminal_responses(tenant_id=DEMO_TENANT_ID)
            for row in rows:
                conversation_id, actor_id = row[1], row[2]
                history = messages.list_for_actor(
                    conversation_id=conversation_id,
                    tenant_id=DEMO_TENANT_ID,
                    actor_id=actor_id,
                    limit=500,
                )
                content = next(
                    (item.content_redacted for item in reversed(history) if item.role == "user"),
                    "继续处理当前任务",
                )
                app.state.run_executor.submit(
                    execute_message_run,
                    conversation_id=conversation_id,
                    content=content,
                    actor_id=actor_id,
                    run_id=row[0],
                    tenant_id=DEMO_TENANT_ID,
                    settings=settings,
                )
        except Exception:
            # Startup must remain available for new conversations even when a
            # stale recovery record is malformed; the Run remains queryable.
            return

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

    @app.get("/internal/v1/metrics")
    def metrics(actor_id: str = Depends(get_demo_actor)) -> dict[str, int]:
        del actor_id
        return dict(app.state.metrics.snapshot())

    @app.get("/v1/evals", response_model=list[EvalRunSummary])
    def list_evaluations(
        limit: int = 20,
        offset: int = 0,
        status_filter: str | None = None,
        actor_id: str = Depends(get_demo_actor),
    ) -> list[EvalRunSummary]:
        del actor_id
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        if not EVAL_REPORT_ROOT.is_dir():
            return []
        summaries: list[EvalRunSummary] = []
        for report_path in sorted(EVAL_REPORT_ROOT.glob("*/report.json"), reverse=True):
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                eval_id = report_path.parent.name
                summary = EvalRunSummary(
                    eval_run_id=eval_id,
                    status=str(payload.get("status", "unknown")),
                    selected_cases=int(payload.get("selected_cases", 0)),
                    completed_cases=int(payload.get("completed_cases", 0)),
                    passed_cases=int(payload.get("passed_cases", 0)),
                    failed_cases=int(payload.get("failed_cases", 0)),
                    judge=str(payload.get("judge", "off")),
                    mode=str(payload.get("mode", "debug")),
                    repetitions=int(payload.get("repetitions", 1)),
                )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if status_filter and summary.status != status_filter:
                continue
            summaries.append(summary)
        return summaries[offset : offset + limit]

    @app.post("/v1/evals", response_model=EvalRunSummary, status_code=status.HTTP_202_ACCEPTED)
    def create_evaluation(
        payload: EvalRunCreateRequest,
        background_tasks: BackgroundTasks,
        actor_id: str = Depends(get_demo_actor),
    ) -> EvalRunSummary:
        del actor_id
        if payload.mode == "release" and payload.judge != "on":
            raise HTTPException(status_code=400, detail="release mode requires judge")
        try:
            ensure_disk_budget(EVAL_REPORT_ROOT)
        except InsufficientDiskError as error:
            # Do not disclose host capacity or filesystem details to callers.
            raise HTTPException(status_code=507, detail="evaluation_storage_unavailable") from error
        eval_id = str(uuid4())
        directory = EVAL_REPORT_ROOT / eval_id
        directory.mkdir(parents=True, exist_ok=False)
        report = {
            "schema_version": "1.0",
            "status": "queued",
            "judge": payload.judge,
            "mode": payload.mode,
            "repetitions": payload.repetitions,
            "selected_cases": 300,
            "completed_cases": 0,
            "passed_cases": 0,
            "failed_cases": 0,
            "results": [],
        }
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8"
        )
        background_tasks.add_task(_execute_eval_report, eval_id, payload)
        return EvalRunSummary(
            eval_run_id=eval_id,
            status="queued",
            selected_cases=300,
            completed_cases=0,
            passed_cases=0,
            failed_cases=0,
            judge=payload.judge,
            mode=payload.mode,
            repetitions=payload.repetitions,
        )

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
        return dict(payload)

    @app.get("/v1/evals/{eval_run_id}/cases")
    def list_evaluation_cases(
        eval_run_id: str,
        limit: int = 50,
        offset: int = 0,
        track: str | None = None,
        failed_only: bool = False,
        actor_id: str = Depends(get_demo_actor),
    ) -> dict[str, Any]:
        del actor_id
        report_path, _ = _eval_report_paths(eval_run_id)
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="evaluation not found")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        rows = payload.get("results", [])
        rows = [
            row
            for row in rows
            if (not track or row.get("track") == track)
            and (not failed_only or row.get("final_pass") is not True)
        ]
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        return {"total": len(rows), "items": rows[offset : offset + limit]}

    @app.post("/v1/evals/{eval_run_id}/cancel")
    def cancel_evaluation(
        eval_run_id: str, actor_id: str = Depends(get_demo_actor)
    ) -> dict[str, str]:
        del actor_id
        report_path, _ = _eval_report_paths(eval_run_id)
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="evaluation not found")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if payload.get("status") in {"completed", "failed", "cancelled"}:
            return {"eval_run_id": eval_run_id, "status": str(payload.get("status"))}
        with _EVAL_PROCESS_LOCK:
            process = _EVAL_PROCESSES.get(eval_run_id)
        if process is not None and process.poll() is None:
            process.terminate()
        payload["status"] = "cancelled"
        payload["eval_run_id"] = eval_run_id
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
        request: Request,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
        _admission: None = Depends(require_admission),
    ) -> MessageSendResponse:
        run_id = uuid4()
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
            active = RunLifecycleRepository(get_engine()).active_for_conversation(
                conversation_id=conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
            )
            if active is not None and active.status == RunStatus.WAITING_USER.value:
                try:
                    message = messages.append_user(
                        conversation_id=conversation_id,
                        tenant_id=DEMO_TENANT_ID,
                        actor_id=actor_id,
                        content=payload.content,
                        client_message_id=payload.client_message_id,
                        run_id=active.run_id,
                    )
                except MessageConflictError as error:
                    raise HTTPException(
                        status_code=409, detail="client_message_id_conflict"
                    ) from error
                request.app.state.run_executor.submit(
                    execute_message_run,
                    conversation_id=conversation_id,
                    content=payload.content,
                    actor_id=actor_id,
                    run_id=active.run_id,
                    tenant_id=DEMO_TENANT_ID,
                    settings=settings,
                )
                return MessageSendResponse(
                    message_id=message.message_id,
                    run_id=active.run_id,
                    run_status=RunStatus.RUNNING_WORKFLOW.value,
                )
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
            except ActiveRunConflictError as error:
                snapshot = error.snapshot
                if snapshot is None:
                    raise HTTPException(status_code=409, detail="ACTIVE_RUN_EXISTS") from error
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "ACTIVE_RUN_EXISTS",
                        "run_id": str(snapshot.run_id),
                        "status": snapshot.status,
                        "message": "当前会话已有未结束任务，请继续查看该任务。",
                    },
                ) from error
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
            if run_status == RunStatus.WAITING_CONFIRMATION.value:
                token_refresh_required = True
            return MessageSendResponse(
                message_id=message.message_id,
                run_id=run_id,
                run_status=run_status,
                token_refresh_required=token_refresh_required,
            )
        else:
            request.app.state.run_executor.submit(
                execute_message_run,
                conversation_id=conversation_id,
                content=payload.content,
                actor_id=actor_id,
                run_id=run_id,
                tenant_id=DEMO_TENANT_ID,
                settings=settings,
            )
            return MessageSendResponse(
                message_id=message.message_id,
                run_id=run_id,
                run_status=RunStatus.CREATED.value,
            )

    @app.post(
        "/v1/runs/{run_id}/retry",
        response_model=MessageSendResponse,
        status_code=202,
    )
    def retry_run(
        run_id: UUID,
        payload: RetryRunRequest,
        request: Request,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
        _admission: None = Depends(require_admission),
    ) -> MessageSendResponse:
        """Explicitly replay the original user request as a new child Run."""
        runs = RunRepository(get_engine())
        source = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if source is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if source.status not in {RunStatus.FAILED.value, RunStatus.EXPIRED.value}:
            raise HTTPException(status_code=409, detail="run_not_retryable")
        if source.conversation_id is None:
            raise HTTPException(status_code=500, detail="run_data_invalid")
        original = messages.latest_user_for_run(
            run_id=run_id,
            conversation_id=source.conversation_id,
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
        )
        if original is None:
            raise HTTPException(status_code=409, detail="retry_source_message_missing")
        settings = get_settings()
        child_run_id = uuid4()
        fingerprint = "|".join((settings.model or "unconfigured", settings.api_base or "unconfigured"))
        context = RunContext(
            run_id=child_run_id,
            conversation_id=source.conversation_id,
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
            parent_run_id=run_id,
        )
        try:
            RunLifecycleRepository(get_engine()).create_run(context=context, spec=spec)
        except ActiveRunConflictError as error:
            snapshot = error.snapshot
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACTIVE_RUN_EXISTS",
                    "run_id": str(snapshot.run_id) if snapshot else None,
                    "status": snapshot.status if snapshot else None,
                },
            ) from error
        try:
            message = messages.append_user(
                conversation_id=source.conversation_id,
                tenant_id=DEMO_TENANT_ID,
                actor_id=actor_id,
                content=original.content_redacted,
                client_message_id=payload.client_message_id,
                run_id=child_run_id,
            )
        except Exception as error:
            RunLifecycleRepository(get_engine()).cancel_unstarted_run(
                run_id=child_run_id,
                tenant_id=DEMO_TENANT_ID,
                reason="RETRY_MESSAGE_PROJECTION_FAILED",
            )
            raise HTTPException(status_code=503, detail="retry_unavailable") from error
        request.app.state.run_executor.submit(
            execute_message_run,
            conversation_id=source.conversation_id,
            content=original.content_redacted,
            actor_id=actor_id,
            run_id=child_run_id,
            tenant_id=DEMO_TENANT_ID,
            settings=settings,
        )
        return MessageSendResponse(
            message_id=message.message_id,
            run_id=child_run_id,
            run_status=RunStatus.CREATED.value,
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
            status_code = (
                409
                if error.code
                in {"CONFIRMATION_UNAVAILABLE", "CONFIRMATION_CONFLICT", "PREVIEW_CHANGED"}
                else 400
            )
            raise HTTPException(status_code=status_code, detail=error.code) from error
        publish_terminal_response(
            context=updated,
            messages=messages,
            runs=runs,
            preferred_content=response_text,
            reason_code=("CONFIRMATION_REJECTED" if not accepted else None),
            retryable=False,
        )
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
        messages: MessageRepository = Depends(_message_repository),
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
        snapshot = runs.load_run(run_id=ticket.run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        context = _checkpoint_context(run_id=ticket.run_id, actor_id=actor_id)
        if context.status is not RunStatus.WAITING_HUMAN:
            raise HTTPException(status_code=409, detail="run_not_waiting_human")
        target = RunStatus.COMPLETED if payload.outcome == "verified_success" else RunStatus.FAILED
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
        response_text = (
            "人工审核已批准，本次流程已完成。"
            if payload.outcome == "verified_success"
            else "人工审核未批准，本次流程已终止。"
        )
        publish_terminal_response(
            context=context.model_copy(update={"status": target, "state": state}),
            messages=messages,
            runs=runs,
            preferred_content=response_text,
            reason_code=("HUMAN_REVIEW_REJECTED" if target is RunStatus.FAILED else None),
            retryable=False,
        )
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=actor_id,
            event_type="mutation_handoff_resolved",
            payload={
                "ticket_id": str(ticket_id),
                "run_id": str(ticket.run_id),
                "outcome": payload.outcome,
            },
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

    @app.get("/v1/runs/{run_id}/human-review", response_model=HumanReviewResponse)
    def get_human_review(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
    ) -> HumanReviewResponse:
        runs = RunRepository(get_engine())
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if snapshot.status != RunStatus.WAITING_HUMAN.value:
            raise HTTPException(status_code=409, detail="run_not_waiting_human")
        handoffs = HandoffRepository(get_engine())
        ticket = handoffs.get_open_for_run(
            run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_ref=actor_id
        )
        if ticket is None:
            # Runs created before the human-review projection was introduced
            # have the decision in their checkpoint but no ticket row. Rebuild
            # a redacted ticket on first read so those sessions remain usable.
            checkpoint = runs.load_latest_checkpoint(run_id=run_id, tenant_id=DEMO_TENANT_ID)
            raw_state = checkpoint.get("state", {}) if checkpoint else {}
            state = raw_state if isinstance(raw_state, dict) else {}
            raw_args = state.get("mutation_args", {})
            arguments = raw_args if isinstance(raw_args, dict) else {}
            reason_code = str(
                state.get("mutation_error") or snapshot.terminal_reason or "HUMAN_REVIEW_REQUIRED"
            )[:128]
            details: dict[str, object] = {
                "message": str(state.get("mutation_message") or "请求需要人工处理")[:500],
            }
            for key in ("order_id", "item_id"):
                value = arguments.get(key)
                if value:
                    details[key] = str(value)[:128]
            ticket = handoffs.get_or_create_open_for_run(
                run_id=run_id,
                tenant_id=DEMO_TENANT_ID,
                actor_ref=actor_id,
                reason_code=reason_code,
                operation=str(state.get("mutation_type") or state.get("route") or "human_review"),
                details=details,
            )
        if ticket is None:
            raise HTTPException(status_code=404, detail="human_review_not_found")
        return HumanReviewResponse(
            ticket_id=ticket.ticket_id,
            run_id=ticket.run_id,
            status=ticket.status,
            reason_code=ticket.reason_code,
            operation=ticket.operation,
            details=ticket.details,
            created_at=ticket.created_at.isoformat(),
            resolved_at=ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            resolution=ticket.resolution,
        )

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunResponse)
    def cancel_run(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
        messages: MessageRepository = Depends(_message_repository),
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
            events=(
                DomainEvent(event_type=EventType.FAILED, payload={"reason": "cancelled_by_user"}),
            ),
        )
        updated = replace(
            snapshot,
            status=RunStatus.CANCELLED.value,
            step_count=snapshot.step_count + 1,
            row_version=version,
        )
        runs.set_terminal_reason(
            run_id=run_id, tenant_id=DEMO_TENANT_ID, reason="CANCELLED_BY_USER"
        )
        publish_terminal_response(
            context=context.model_copy(update={"status": RunStatus.CANCELLED, "state": state}),
            messages=messages,
            runs=runs,
            reason_code="CANCELLED_BY_USER",
            retryable=False,
        )
        latest = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if latest is not None:
            updated = latest
        return _run_response(
            updated,
            run_id=run_id,
            conversation_id=snapshot.conversation_id or context.conversation_id,
        )

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

    @app.get("/v1/conversations/{conversation_id}/active-run", response_model=ActiveRunResponse)
    def get_active_run(
        conversation_id: UUID,
        actor_id: str = Depends(get_demo_actor),
    ) -> ActiveRunResponse:
        conversations = ConversationRepository(get_engine()).list_for_actor(
            tenant_id=DEMO_TENANT_ID, actor_id=actor_id
        )
        if not any(item.id == conversation_id for item in conversations):
            raise HTTPException(status_code=404, detail="conversation_not_found")
        snapshot = RunLifecycleRepository(get_engine()).active_for_conversation(
            conversation_id=conversation_id,
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
        )
        if snapshot is None:
            return ActiveRunResponse(run=None)
        return ActiveRunResponse(
            run=_run_response(
                snapshot,
                run_id=snapshot.run_id,
                conversation_id=conversation_id,
            )
        )

    @app.get("/v1/runtime/state-machine", response_model=StateMachineResponse)
    def get_state_machine(actor_id: str = Depends(get_demo_actor)) -> StateMachineResponse:
        del actor_id
        return StateMachineResponse(states=state_machine_definition())

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

    @app.get("/v1/runs/{run_id}/timeline")
    def get_run_timeline(
        run_id: UUID,
        after_sequence: int = 0,
        limit: int = 200,
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> list[dict[str, object]]:
        return get_run_events(
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
            actor_id=actor_id,
            runs=runs,
        )

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
        for event in runs.replay_events(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id):
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

    @app.get("/v1/runs/{run_id}/stream")
    def stream_run(
        run_id: UUID,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> StreamingResponse:
        try:
            after = int(last_event_id or "0")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid_event_cursor") from error
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")

        def events() -> Iterator[str]:
            cursor = after
            deadline = monotonic() + 55.0
            while monotonic() < deadline:
                batch = runs.replay_events(
                    run_id=run_id,
                    tenant_id=DEMO_TENANT_ID,
                    actor_id=actor_id,
                    after_sequence=cursor,
                    limit=200,
                )
                if batch:
                    for event in batch:
                        cursor = event.sequence
                        payload = json.dumps(
                            event.event.payload, ensure_ascii=False, separators=(",", ":")
                        )
                        yield (
                            f"id: {event.sequence}\n"
                            f"event: {event.event.event_type.value}\n"
                            f"data: {payload}\n\n"
                        )
                    current = runs.load_run(
                        run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id
                    )
                    if current is not None and current.status in {
                        item.value
                        for item in (
                            RunStatus.COMPLETED,
                            RunStatus.FAILED,
                            RunStatus.CANCELLED,
                            RunStatus.EXPIRED,
                        )
                    }:
                        return
                    continue
                yield ": heartbeat\n\n"
                current = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
                if current is not None and current.status in {
                    item.value
                    for item in (
                        RunStatus.COMPLETED,
                        RunStatus.FAILED,
                        RunStatus.CANCELLED,
                        RunStatus.EXPIRED,
                    )
                }:
                    return
                sleep(0.5)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

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
            # index.html points at content-hashed Vite bundles. Never cache
            # the HTML shell across deployments, otherwise a browser can keep
            # an old bundle reference after the image has been rebuilt and
            # render a blank page when that asset no longer exists.
            return FileResponse(index, headers={"Cache-Control": "no-store, max-age=0"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="web_build_not_found")

    return app


app = create_app()

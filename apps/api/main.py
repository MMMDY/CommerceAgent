"""Phase 0 FastAPI application factory."""

# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter, sleep
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from apps.api.bootstrap import ReadinessDependencies
from src.config import Settings, get_settings
from src.db import get_engine
from src.evolution.contracts import AttributionCategory, FailureSignal
from src.evolution.failure_attribution import FailureAttributionService
from src.evolution.skill_registry import SkillRegistry
from src.harness.dashboard import build_eval_case_detail, build_eval_dashboard
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
from src.release.canary_guard import CanaryMetrics
from src.release.scheduler import ReleaseObservationScheduler
from src.repositories.audit import AuditRepository
from src.repositories.control_plane import (
    ControlPlaneIdempotencyConflictError,
    ControlPlaneIdempotencyInProgressError,
    ControlPlaneIdempotencyRepository,
)
from src.repositories.conversations import Conversation, ConversationRepository
from src.repositories.failures import FailureRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.handoffs import HandoffRepository
from src.repositories.knowledge import KnowledgeRepository
from src.repositories.memory import MemoryRepository, MemoryValidationError
from src.repositories.messages import MessageConflictError, MessageRecord, MessageRepository
from src.repositories.mutations import ConfirmationRepository, MutationExecutionRepository
from src.repositories.releases import ReleaseRepository, ReleaseTransitionError
from src.repositories.run_lifecycle import (
    ActiveRunConflictError,
    RunLifecycleRepository,
)
from src.repositories.run_observability import RunObservabilityRepository
from src.repositories.runs import RunRepository, RunSnapshot
from src.repositories.skills import SkillRepository, SkillTransitionError
from src.telemetry.lifecycle import ShutdownGate
from src.telemetry.metrics import Metrics
from src.telemetry.run_insight import build_run_visualization
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
    runtime: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    dataset_hash: str | None = None
    manifest_hash: str | None = None


class EvaluationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=500)
    confirmation: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=128)


class FeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["up", "down"]
    reason_codes: tuple[str, ...] = Field(default=(), max_length=8)
    correction: str | None = Field(default=None, max_length=2000)
    consent_for_improvement: bool = False
    idempotency_key: str = Field(min_length=1, max_length=128)


class FailureReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["verified_success", "verified_failure"]
    category: AttributionCategory | None = None
    review_note: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class FailureReanalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class FailureSkillCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class ReleaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_version: str = Field(min_length=1, max_length=128)
    candidate_version: str = Field(min_length=1, max_length=128)
    gates: dict[str, object] = Field(default_factory=dict, max_length=16)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RuntimeRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=128)
    runtime_hash: str = Field(min_length=1, max_length=128)
    metadata: dict[str, object] = Field(default_factory=dict, max_length=16)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReleaseStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReleaseEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p0_events: int = Field(default=0, ge=0)
    terminal_response_coverage: float | None = Field(default=None, ge=0, le=1)
    p95_e2e_ms: float | None = Field(default=None, ge=0)
    baseline_p95_e2e_ms: float | None = Field(default=None, ge=0)
    p99_e2e_ms: float | None = Field(default=None, ge=0)
    baseline_p99_e2e_ms: float | None = Field(default=None, ge=0)
    p95_cost_microusd: float | None = Field(default=None, ge=0)
    baseline_p95_cost_microusd: float | None = Field(default=None, ge=0)
    low_risk_handoff_rate: float | None = Field(default=None, ge=0, le=1)
    baseline_low_risk_handoff_rate: float | None = Field(default=None, ge=0, le=1)
    confirmation: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillCandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["tenant", "route", "global"] = "tenant"
    scope_value: str = Field(min_length=1, max_length=128)
    owner: Literal["tenant", "project"] = "tenant"
    kind: Literal["experience", "safety"] = "experience"
    cluster_key: str = Field(min_length=1, max_length=160)
    keywords: list[str] = Field(min_length=1, max_length=32)
    response_policy: str = Field(min_length=1, max_length=64)
    source_count: int = Field(ge=5, le=100000)
    offline_gate_pass: bool
    safety_gate_pass: bool
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillKillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillEvaluationCreateRequest(BaseModel):
    """Bounded paired-eval aggregates; raw reports and prompts are not accepted."""

    model_config = ConfigDict(extra="forbid")

    skill_version_id: UUID | None = None
    dataset_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before: dict[str, float | int | None] = Field(default_factory=dict, max_length=8)
    after: dict[str, float | int | None] = Field(default_factory=dict, max_length=8)
    safety_result: Literal["pass", "fail", "incomplete"]
    cost_delta_microusd: int | None = Field(default=None, ge=-10_000_000_000, le=10_000_000_000)
    latency_delta_ms: int | None = Field(default=None, ge=-10_000_000, le=10_000_000)
    gate_pass: bool
    judge_disagreement_count: int = Field(default=0, ge=0, le=1_000_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _eval_report_paths(eval_run_id: str) -> tuple[Path, Path]:
    # IDs are generated UUIDs; reject path traversal before touching disk.
    try:
        UUID(eval_run_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="evaluation not found") from error
    directory = EVAL_REPORT_ROOT / eval_run_id
    return directory / "report.json", directory / "report.md"


def _read_eval_report(eval_run_id: str) -> dict[str, Any]:
    report_path, _ = _eval_report_paths(eval_run_id)
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="evaluation not found")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail="evaluation unavailable") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="evaluation unavailable")
    payload.setdefault("eval_run_id", eval_run_id)
    return payload


def _evaluation_approval_projection(
    *, eval_run_id: str, report: Mapping[str, Any], record: dict[str, object] | None
) -> dict[str, object]:
    raw = report.get("human_approval")
    required = isinstance(raw, dict) and raw.get("required") is True
    projection: dict[str, object] = {
        "eval_run_id": eval_run_id,
        "required": required,
        "status": str(raw.get("status", "pending")) if required and isinstance(raw, dict) else "not_required",
        "source": str(raw.get("source", "separate_approver_workflow"))
        if required and isinstance(raw, dict)
        else "N/A",
        "recorded": False,
        "approval_id": None,
        "approver_ref": None,
        "decided_at": None,
        "reason_hash": None,
    }
    if record is not None:
        projection.update(
            {
                "status": record.get("status", record.get("decision", "unknown")),
                "recorded": True,
                "approval_id": record.get("approval_id"),
                "approver_ref": record.get("approver_ref"),
                "decided_at": record.get("decided_at"),
                "reason_hash": record.get("reason_hash"),
            }
        )
    return projection


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
    accepted_at: datetime | None = None
    dispatch_started_at: datetime | None = None
    terminal_at: datetime | None = None
    response_published_at: datetime | None = None
    total_cost_microusd: int | None = None


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
        accepted_at=snapshot.accepted_at,
        dispatch_started_at=snapshot.dispatch_started_at,
        terminal_at=snapshot.terminal_at,
        response_published_at=snapshot.response_published_at,
        total_cost_microusd=snapshot.total_cost_microusd,
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


def require_admin(
    authorization: str | None = Header(default=None),
    x_demo_actor: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Authenticate control-plane operations without putting a token in the web bundle.

    The demo fallback is deliberately limited to local demo mode when no token
    is configured. Production deployments must configure a separate token and
    use ``Authorization: Bearer ...``; comparisons are constant-time.
    """

    configured = settings.internal_admin_token
    if configured is None or not configured.get_secret_value():
        if settings.demo_mode and x_demo_actor in settings.demo_actors:
            return "demo-admin"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    presented = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if presented and compare_digest(presented, configured.get_secret_value()):
        return "admin"
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")


def require_approver(
    authorization: str | None = Header(default=None),
    x_demo_actor: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Authenticate the role allowed to mutate Skill/release control state."""

    configured = settings.internal_approver_token
    if configured is None or not configured.get_secret_value():
        if settings.demo_mode and x_demo_actor in settings.demo_actors:
            return "demo-approver"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="approver_required")
    presented = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if presented and compare_digest(presented, configured.get_secret_value()):
        return "approver"
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="approver_required")


def _require_action_confirmation(*, action: str, resource_id: UUID, confirmation: str) -> None:
    expected = f"CONFIRM {action.upper()} {resource_id}"
    if not compare_digest(confirmation.strip(), expected):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirmation_required")


def _require_tenant_action_confirmation(
    *, action: str, tenant_id: str, confirmation: str
) -> None:
    expected = f"CONFIRM {action.upper()} {tenant_id}"
    if not compare_digest(confirmation.strip(), expected):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirmation_required")


def _failure_json(view: object) -> dict[str, object]:
    """Convert a redacted failure DTO to JSON-safe API data."""

    if hasattr(view, "model_dump"):
        return cast(dict[str, object], view.model_dump(mode="json"))
    if isinstance(view, Mapping):
        return {str(key): value for key, value in view.items()}
    return {}


def _record_run_failure(*, run: RunSnapshot, signal: str, source: str, reason: str) -> None:
    """Best-effort failure projection; it never changes the user-facing run."""

    try:
        FailureAttributionService(get_engine()).record_run_signal(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            signal=signal,
            source=source,
            reason=reason,
            route=run.current_step,
        )
    except Exception:
        return


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


def _rounded_optional_number(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return round(value)
    try:
        return round(float(str(value)))
    except (TypeError, ValueError):
        return None


def create_app(*, readiness: ReadinessDependencies | None = None) -> FastAPI:
    app = FastAPI(title="CommerceAgent", version="0.1.0")
    app.state.shutdown_gate = ShutdownGate()
    app.state.metrics = Metrics()
    app.state.run_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="commerce-agent-run"
    )
    app.state.release_scheduler = None
    readiness_dependencies = readiness or ReadinessDependencies.default()

    @app.middleware("http")
    async def observe_http_request(request: Request, call_next: Any) -> Response:
        started = perf_counter()
        response = await call_next(request)
        metrics = app.state.metrics
        metrics.observe("http_request_latency_ms", (perf_counter() - started) * 1000)
        bucket = "2xx" if response.status_code < 300 else "4xx" if response.status_code < 500 else "5xx"
        metrics.increment(f"http_responses_{bucket}")
        return cast(Response, response)

    @app.on_event("shutdown")
    def graceful_shutdown() -> None:
        gate: ShutdownGate = app.state.shutdown_gate
        gate.stop_accepting()
        if app.state.release_scheduler is not None:
            app.state.release_scheduler.stop(timeout=5.0)
        gate.wait_for_idle(timeout=5.0)
        app.state.run_executor.shutdown(wait=True, cancel_futures=False)

    @app.on_event("startup")
    def recover_active_runs() -> None:
        """Reattach non-terminal demo runs after a single-process restart."""

        try:
            engine = get_engine()
            with engine.begin() as connection:
                expired_run_ids = connection.execute(
                    text(
                        "UPDATE runtime.agent_runs SET status = 'expired', current_step = 'terminal', "
                        "terminal_reason = 'DEADLINE_EXCEEDED_DURING_RESTART', updated_at = now(), "
                        "row_version = row_version + 1 WHERE tenant_id = :tenant_id "
                        "AND status IN ('created', 'routing', 'running_readonly', 'running_workflow') "
                        "AND deadline_at <= now() RETURNING run_id"
                    ),
                    {"tenant_id": DEMO_TENANT_ID},
                ).scalars().all()
            for expired_run_id in expired_run_ids:
                try:
                    FailureAttributionService(engine).record_run_outcome(
                        tenant_id=DEMO_TENANT_ID,
                        run_id=expired_run_id,
                        status="expired",
                        terminal_reason="DEADLINE_EXCEEDED_DURING_RESTART",
                        route="terminal",
                    )
                except Exception:
                    # Expiry projection is auxiliary; recovery must continue
                    # even if the failure tables are temporarily unavailable.
                    pass
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

    @app.on_event("startup")
    def start_release_scheduler() -> None:
        settings = get_settings()
        if not settings.enable_release_scheduler:
            return
        scheduler = ReleaseObservationScheduler(
            ReleaseRepository(get_engine()),
            tenant_id=DEMO_TENANT_ID,
            interval_seconds=settings.release_scheduler_interval_seconds,
        )
        app.state.release_scheduler = scheduler
        scheduler.start()

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
    def metrics(admin: str = Depends(require_admin)) -> dict[str, object]:
        del admin
        return cast(dict[str, object], app.state.metrics.snapshot())

    @app.get("/internal/v1/operations/summary")
    def operations_summary(
        window_hours: int = 24,
        route: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        del admin
        # The demo control plane currently authorizes one tenant.  Keep the
        # selector explicit so a future multi-tenant authorizer cannot turn a
        # query parameter into a cross-tenant read.
        if tenant_id is not None and tenant_id != DEMO_TENANT_ID:
            raise HTTPException(status_code=403, detail="tenant_not_authorized")
        try:
            summary = RunObservabilityRepository(get_engine()).operations_summary(
                tenant_id=DEMO_TENANT_ID,
                window_hours=window_hours,
                route=route,
                model=model,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        request_count = _rounded_optional_number(summary.get("request_count")) or 0
        completed_count = _rounded_optional_number(summary.get("completed_count")) or 0
        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "window_hours": window_hours,
            "request_count": request_count,
            "completed_count": completed_count,
            "failed_count": _rounded_optional_number(summary.get("failed_count")) or 0,
            "success_rate": completed_count / request_count if request_count else None,
            "measured_latency_count": (
                _rounded_optional_number(summary.get("measured_latency_count")) or 0
            ),
            "p50_latency_ms": _rounded_optional_number(summary.get("p50_latency_ms")),
            "p95_latency_ms": _rounded_optional_number(summary.get("p95_latency_ms")),
            "p99_latency_ms": _rounded_optional_number(summary.get("p99_latency_ms")),
            "priced_run_count": _rounded_optional_number(summary.get("priced_run_count")) or 0,
            "avg_success_cost_microusd": _rounded_optional_number(
                summary.get("avg_success_cost_microusd")
            ),
            "total_cost_microusd": _rounded_optional_number(
                summary.get("total_cost_microusd")
            ),
            "model_breakdown": summary.get("model_breakdown", []),
            "trend": summary.get("trend", []),
            "safety_summary": summary.get("safety_summary", {}),
            "safety_categories": summary.get("safety_categories", []),
            "safety_category_breakdown": summary.get("safety_category_breakdown", []),
            "safety_trend": summary.get("safety_trend", []),
            "safety_handoff_count": summary.get("safety_handoff_count", 0),
            "safety_false_negative_count": summary.get("safety_false_negative_count"),
            "safety_false_rejection_count": summary.get("safety_false_rejection_count"),
            "release_summary": summary.get("release_summary"),
            "version_breakdown": summary.get("version_breakdown", []),
            "recent_runs": summary.get("recent_runs", []),
            "available_routes": summary.get("available_routes", []),
            "available_models": summary.get("available_models", []),
            "filters": {
                "tenant_id": DEMO_TENANT_ID,
                "route": route,
                "model": model,
            },
        }

    @app.get("/internal/v1/safety/events")
    def safety_p0_events(
        limit: int = 50,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        """Admin-only, tenant-scoped P0 safety audit drill-down."""

        del admin
        try:
            events = AuditRepository(get_engine()).recent_safety_p0(
                tenant_id=DEMO_TENANT_ID,
                limit=limit,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"items": events, "total": len(events)}

    @app.post("/v1/runs/{run_id}/feedback", status_code=status.HTTP_201_CREATED)
    def submit_run_feedback(
        run_id: UUID,
        payload: FeedbackCreateRequest,
        actor_id: str = Depends(get_demo_actor),
    ) -> dict[str, object]:
        runs = RunRepository(get_engine())
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID, actor_id=actor_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        feedback = FeedbackRepository(get_engine()).submit(
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
            run_id=run_id,
            rating=payload.rating,
            reason_codes=payload.reason_codes,
            correction=payload.correction,
            consent_for_improvement=payload.consent_for_improvement,
            idempotency_key=payload.idempotency_key,
        )
        if payload.rating == "down":
            _record_run_failure(
                run=snapshot,
                signal=FailureSignal.USER_DOWNVOTE.value,
                source="user_feedback",
                reason=(payload.reason_codes[0] if payload.reason_codes else "USER_DOWNVOTE"),
            )
        return {
            "feedback_id": str(feedback.feedback_id),
            "run_id": str(feedback.run_id),
            "rating": feedback.rating,
            "consent_for_improvement": feedback.consent_for_improvement,
            "correction_retained": feedback.correction_redacted is not None,
        }

    @app.get("/internal/v1/failures")
    def list_failures(
        limit: int = 100,
        status_filter: str | None = None,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        del admin
        failures = FailureRepository(get_engine()).list(
            tenant_id=DEMO_TENANT_ID, limit=limit, status=status_filter
        )
        return {"items": [_failure_json(item) for item in failures], "total": len(failures)}

    @app.get("/internal/v1/failures/summary")
    def failure_summary(
        window_days: int = 30,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        del admin
        try:
            return FailureRepository(get_engine()).summary(
                tenant_id=DEMO_TENANT_ID,
                window_days=window_days,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/internal/v1/operations/learning-summary")
    def operations_learning_summary(
        window_days: int = 30,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        """Return the tenant-scoped, auditable failure-learning pipeline."""

        del admin
        try:
            summary = FailureRepository(get_engine()).learning_summary(
                tenant_id=DEMO_TENANT_ID,
                window_days=window_days,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            **summary,
        }

    @app.get("/internal/v1/failures/{failure_id}")
    def get_failure(failure_id: UUID, admin: str = Depends(require_admin)) -> dict[str, object]:
        del admin
        failure = FailureRepository(get_engine()).get(tenant_id=DEMO_TENANT_ID, failure_id=failure_id)
        if failure is None:
            raise HTTPException(status_code=404, detail="failure_not_found")
        return _failure_json(failure)

    @app.post("/internal/v1/failures/{failure_id}/reanalyze")
    def reanalyze_failure(
        failure_id: UUID,
        payload: FailureReanalyzeRequest,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        del admin
        repository = FailureRepository(get_engine())
        failure = repository.get(tenant_id=DEMO_TENANT_ID, failure_id=failure_id)
        if failure is None:
            raise HTTPException(status_code=404, detail="failure_not_found")
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="failure_reanalyze",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(f"reanalyze:{failure_id}"),
            )
        except ControlPlaneIdempotencyConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ControlPlaneIdempotencyInProgressError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        refreshed = FailureAttributionService(get_engine()).reanalyze(failure)
        result = _failure_json(refreshed) if refreshed is not None else {}
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=result)
        return result

    @app.post("/internal/v1/failures/{failure_id}/review")
    def review_failure(
        failure_id: UUID,
        payload: FailureReviewRequest,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        repository = FailureRepository(get_engine())
        failure = repository.get(tenant_id=DEMO_TENANT_ID, failure_id=failure_id)
        if failure is None:
            raise HTTPException(status_code=404, detail="failure_not_found")
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="failure_review",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    f"review:{failure_id}:{payload.outcome}:"
                    f"{payload.category.value if payload.category else ''}:"
                    f"{hash_secret(payload.review_note)}"
                ),
            )
        except ControlPlaneIdempotencyConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ControlPlaneIdempotencyInProgressError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        note_hash = hash_secret(payload.review_note)
        try:
            repository.review_attribution(
                tenant_id=DEMO_TENANT_ID,
                failure_id=failure_id,
                outcome=payload.outcome,
                reviewer=admin,
                reviewed_category=payload.category.value if payload.category else None,
                review_note=payload.review_note,
            )
            AuditRepository(get_engine()).append(
                tenant_id=DEMO_TENANT_ID,
                actor_ref=admin,
                event_type="failure_attribution_reviewed",
                payload={
                    "failure_id": str(failure_id),
                    "outcome": payload.outcome,
                    "category": payload.category.value if payload.category else None,
                    "review_note_hash": note_hash,
                    "idempotency_key": payload.idempotency_key,
                },
                payload_hash=hash_secret(
                    f"{failure_id}:{payload.outcome}:{payload.idempotency_key}:{note_hash}"
                ),
            )
        except ValueError as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=400, detail=str(error)) from error
        refreshed = repository.get(tenant_id=DEMO_TENANT_ID, failure_id=failure_id)
        result = _failure_json(refreshed) if refreshed is not None else {}
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=result)
        return result

    @app.post("/internal/v1/failures/{failure_id}/skill", status_code=status.HTTP_201_CREATED)
    def create_skill_from_failure(
        failure_id: UUID,
        payload: FailureSkillCreateRequest,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        """Create a review-only Skill from a sufficiently diverse failure cluster.

        Only taxonomy and cluster identity cross this boundary; the endpoint
        never forwards the failure summary or original user text to the
        generator.  Offline and safety gates intentionally start false.
        """

        failure = FailureRepository(get_engine()).get(
            tenant_id=DEMO_TENANT_ID, failure_id=failure_id
        )
        if failure is None:
            raise HTTPException(status_code=404, detail="failure_not_found")
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="skill_from_failure",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    f"skill-from-failure:{failure_id}:{failure.cluster_key}"
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        category = str(
            (failure.attribution or {}).get("deterministic_category") or "unknown"
        )
        response_policy = (
            "safety_deescalation" if category == AttributionCategory.SAFETY_ERROR.value
            else "conversational_response"
        )
        try:
            skill_id = SkillRegistry(get_engine()).generate_from_cluster(
                tenant_id=DEMO_TENANT_ID,
                cluster_key=failure.cluster_key,
                scope_type="tenant",
                scope_value=DEMO_TENANT_ID,
                keywords=[category, "低风险模糊请求"],
                response_policy=response_policy,
                offline_gate_pass=False,
                safety_gate_pass=False,
                provenance={"source": "failure_cluster", "category": category},
            )
            result = SkillRepository(get_engine()).get(
                tenant_id=DEMO_TENANT_ID, skill_id=skill_id
            ) or {"skill_id": str(skill_id), "status": "PENDING_REVIEW"}
        except SkillTransitionError as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=409, detail=str(error)) from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=admin,
            event_type="skill_candidate_requested_from_failure",
            payload={"failure_id": str(failure_id), "cluster_key": failure.cluster_key, "category": category},
            payload_hash=hash_secret(f"skill-from-failure:{failure_id}:{payload.idempotency_key}"),
        )
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return encoded

    @app.get("/internal/v1/skills")
    def list_skills(
        limit: int = 100,
        status_filter: str | None = None,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        del admin
        skills = SkillRepository(get_engine()).list(
            tenant_id=DEMO_TENANT_ID, limit=limit, status=status_filter
        )
        return {"items": skills, "total": len(skills)}

    @app.post("/internal/v1/skills", status_code=status.HTTP_201_CREATED)
    def create_skill_candidate(
        payload: SkillCandidateCreateRequest,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="skill_candidate_create",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    json.dumps(
                        payload.model_dump(exclude={"idempotency_key"}),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            skill_id = SkillRegistry(get_engine()).generate_from_cluster(
                tenant_id=DEMO_TENANT_ID,
                cluster_key=payload.cluster_key,
                scope_type=payload.scope_type,
                scope_value=payload.scope_value,
                keywords=payload.keywords,
                response_policy=payload.response_policy,
                offline_gate_pass=payload.offline_gate_pass,
                safety_gate_pass=payload.safety_gate_pass,
                owner=payload.owner,
                kind=payload.kind,
            )
        except (ValueError, SkillTransitionError) as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=400, detail=str(error)) from error
        result = SkillRepository(get_engine()).get(tenant_id=DEMO_TENANT_ID, skill_id=skill_id) or {}
        encoded = cast(dict[str, object], jsonable_encoder(result))
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=admin,
            event_type="skill_candidate_created",
            payload={"skill_id": str(skill_id), "idempotency_key": payload.idempotency_key},
            payload_hash=hash_secret(f"skill_candidate:{skill_id}:{payload.idempotency_key}"),
        )
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return result

    @app.get("/internal/v1/skills/kill-switch")
    def get_skill_kill_switch(
        admin: str = Depends(require_admin),
        settings: Settings = Depends(get_settings),
        x_demo_actor: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Return tenant Skill matching state without exposing the reason text."""

        del admin
        result = SkillRepository(get_engine()).matching_control(tenant_id=DEMO_TENANT_ID)
        # In demo mode the same explicitly allow-listed actor is both the
        # read-only admin and the approver.  Production browser bundles never
        # receive an approver secret, so they remain read-only unless a
        # deployment-specific authenticated approver channel is added.
        result["can_mutate"] = bool(
            settings.demo_mode and x_demo_actor in settings.demo_actors
        )
        return result

    @app.post("/internal/v1/skills/kill-switch")
    def set_skill_kill_switch(
        payload: SkillKillSwitchRequest,
        admin: str = Depends(require_approver),
    ) -> dict[str, object]:
        """Enable/disable tenant Skill matching with an audited mutation.

        The runtime reads this value before every registry match.  Disabling
        matching never deletes historical Skill matches or versions; it only
        prevents new matches until explicitly re-enabled.
        """

        _require_tenant_action_confirmation(
            action="skill_kill_switch",
            tenant_id=DEMO_TENANT_ID,
            confirmation=payload.confirmation,
        )
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        fingerprint = hash_secret(
            "skill-kill-switch:"
            + json.dumps(
                payload.model_dump(exclude={"idempotency_key", "confirmation"}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="skill_kill_switch",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=fingerprint,
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            result = SkillRepository(get_engine()).set_matching_enabled(
                tenant_id=DEMO_TENANT_ID,
                enabled=payload.enabled,
                updated_by=admin,
                reason_hash=hash_secret(payload.reason),
            )
        except Exception as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=503, detail="skill_control_unavailable") from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=admin,
            event_type="skill_kill_switch_updated",
            payload={
                "enabled": payload.enabled,
                "reason_hash": hash_secret(payload.reason),
                "idempotency_key": payload.idempotency_key,
            },
            payload_hash=hash_secret(f"skill-kill-switch:{payload.idempotency_key}"),
        )
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return encoded

    @app.get("/internal/v1/skills/{skill_id}")
    def get_skill(skill_id: UUID, admin: str = Depends(require_admin)) -> dict[str, object]:
        del admin
        skill = SkillRepository(get_engine()).get(tenant_id=DEMO_TENANT_ID, skill_id=skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill_not_found")
        return skill

    @app.post("/internal/v1/skills/{skill_id}/evaluations", status_code=status.HTTP_201_CREATED)
    def record_skill_evaluation(
        skill_id: UUID,
        payload: SkillEvaluationCreateRequest,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        request_body = payload.model_dump(exclude={"idempotency_key"})
        fingerprint_body = jsonable_encoder(request_body)
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="skill_evaluation_record",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    "skill-evaluation:" + str(skill_id) + ":" + json.dumps(
                        fingerprint_body, ensure_ascii=False, sort_keys=True
                    )
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            result = SkillRepository(get_engine()).record_evaluation(
                tenant_id=DEMO_TENANT_ID,
                skill_id=skill_id,
                **request_body,
            )
        except SkillTransitionError as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            status_code = 409 if str(error) in {
                "skill_not_found", "skill_version_not_found", "judge_disagreement_blocks_gate",
                "skill_not_pending_or_evaluation_gate_failed",
            } else 400
            raise HTTPException(status_code=status_code, detail=str(error)) from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=admin,
            event_type="skill_evaluation_recorded",
            payload={
                "skill_id": str(skill_id),
                "skill_version_id": str(payload.skill_version_id) if payload.skill_version_id else None,
                "dataset_hash": payload.dataset_hash,
                "gate_pass": payload.gate_pass,
                "safety_result": payload.safety_result,
                "judge_disagreement_count": payload.judge_disagreement_count,
                "idempotency_key": payload.idempotency_key,
            },
            payload_hash=hash_secret(
                f"skill-evaluation:{skill_id}:{payload.dataset_hash}:{payload.idempotency_key}"
            ),
        )
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return result

    def _skill_action(
        skill_id: UUID,
        action: str,
        admin: str,
        reason: str = "",
        confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, object]:
        _require_action_confirmation(
            action=action, resource_id=skill_id, confirmation=confirmation
        )
        if not reason.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="reason_required")
        repository = SkillRepository(get_engine())
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation=f"skill_{action}",
                idempotency_key=idempotency_key,
                request_fingerprint=hash_secret(f"skill:{skill_id}:{action}:{hash_secret(reason)}"),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            if action == "submit":
                result = repository.submit_for_review(tenant_id=DEMO_TENANT_ID, skill_id=skill_id)
            elif action == "approve":
                result = repository.approve(tenant_id=DEMO_TENANT_ID, skill_id=skill_id, reviewer=admin)
            elif action == "reject":
                result = repository.reject(tenant_id=DEMO_TENANT_ID, skill_id=skill_id, reviewer=admin, reason=reason)
            elif action == "canary":
                result = repository.canary(tenant_id=DEMO_TENANT_ID, skill_id=skill_id)
            else:
                result = repository.rollback(tenant_id=DEMO_TENANT_ID, skill_id=skill_id, reason=reason)
        except SkillTransitionError as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=409, detail=str(error)) from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=admin,
            event_type=f"skill_{action}",
            payload={
                "skill_id": str(skill_id),
                "action": action,
                "reason_hash": hash_secret(reason) if reason else None,
                "idempotency_key": idempotency_key,
            },
            payload_hash=hash_secret(
                f"skill:{skill_id}:{action}:{idempotency_key}"
            ),
        )
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return result

    @app.post("/internal/v1/skills/{skill_id}/submit-review")
    def submit_skill_review(
        skill_id: UUID,
        payload: SkillActionRequest,
        admin: str = Depends(require_approver),
    ) -> dict[str, object]:
        return _skill_action(
            skill_id, "submit", admin, payload.reason, payload.confirmation, payload.idempotency_key
        )

    @app.post("/internal/v1/skills/{skill_id}/approve")
    def approve_skill(
        skill_id: UUID,
        payload: SkillActionRequest,
        admin: str = Depends(require_approver),
    ) -> dict[str, object]:
        return _skill_action(
            skill_id, "approve", admin, payload.reason, payload.confirmation, payload.idempotency_key
        )

    @app.post("/internal/v1/skills/{skill_id}/reject")
    def reject_skill(skill_id: UUID, payload: SkillActionRequest, admin: str = Depends(require_approver)) -> dict[str, object]:
        return _skill_action(
            skill_id, "reject", admin, payload.reason, payload.confirmation, payload.idempotency_key
        )

    @app.post("/internal/v1/skills/{skill_id}/canary")
    def canary_skill(
        skill_id: UUID,
        payload: SkillActionRequest,
        admin: str = Depends(require_approver),
    ) -> dict[str, object]:
        return _skill_action(
            skill_id, "canary", admin, payload.reason, payload.confirmation, payload.idempotency_key
        )

    @app.post("/internal/v1/skills/{skill_id}/rollback")
    def rollback_skill(skill_id: UUID, payload: SkillActionRequest, admin: str = Depends(require_approver)) -> dict[str, object]:
        return _skill_action(
            skill_id, "rollback", admin, payload.reason, payload.confirmation, payload.idempotency_key
        )

    @app.get("/internal/v1/releases")
    def list_releases(admin: str = Depends(require_admin)) -> dict[str, object]:
        del admin
        releases = ReleaseRepository(get_engine()).list(tenant_id=DEMO_TENANT_ID)
        return {"items": releases, "total": len(releases)}

    @app.post("/internal/v1/releases/runtime", status_code=status.HTTP_201_CREATED)
    def register_release_runtime(
        payload: RuntimeRegistrationRequest,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="release_runtime_register",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    "runtime:" + json.dumps(
                        payload.model_dump(exclude={"idempotency_key"}),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            result = ReleaseRepository(get_engine()).register_runtime(
                tenant_id=DEMO_TENANT_ID,
                version=payload.version,
                runtime_hash=payload.runtime_hash,
                metadata=payload.metadata,
            )
        except (ValueError, ReleaseTransitionError) as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=409, detail=str(error)) from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        AuditRepository(get_engine()).append(
            tenant_id=DEMO_TENANT_ID,
            actor_ref=admin,
            event_type="release_runtime_registered",
            payload={"version": payload.version, "runtime_hash": payload.runtime_hash},
            payload_hash=hash_secret(f"runtime:{payload.version}:{payload.runtime_hash}"),
        )
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return result

    @app.get("/internal/v1/releases/{release_id}")
    def get_release(release_id: UUID, admin: str = Depends(require_admin)) -> dict[str, object]:
        del admin
        release = ReleaseRepository(get_engine()).get(tenant_id=DEMO_TENANT_ID, release_id=release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="release_not_found")
        return release

    @app.post("/internal/v1/releases", status_code=status.HTTP_201_CREATED)
    def create_release(payload: ReleaseCreateRequest, admin: str = Depends(require_admin)) -> dict[str, object]:
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        fingerprint = hash_secret(
            "release:create:" + json.dumps(
                payload.model_dump(exclude={"idempotency_key"}),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="release_create",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=fingerprint,
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            result = ReleaseRepository(get_engine()).create(
                tenant_id=DEMO_TENANT_ID,
                owner_ref=admin,
                current_version=payload.current_version,
                candidate_version=payload.candidate_version,
                gates=payload.gates,
            )
            encoded = cast(dict[str, object], jsonable_encoder(result))
            idempotency.complete(
                tenant_id=DEMO_TENANT_ID,
                record_id=claim.record_id,
                response=encoded,
            )
            return result
        except Exception:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise

    @app.post("/internal/v1/releases/{release_id}/stop")
    def stop_release(release_id: UUID, payload: ReleaseStopRequest, admin: str = Depends(require_approver)) -> dict[str, object]:
        _require_action_confirmation(
            action="stop", resource_id=release_id, confirmation=payload.confirmation
        )
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="release_stop",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    f"release:{release_id}:stop:{hash_secret(payload.reason)}"
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            result = ReleaseRepository(get_engine()).stop(
                tenant_id=DEMO_TENANT_ID, release_id=release_id, actor_ref=admin, reason=payload.reason
            )
        except ReleaseTransitionError as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=409, detail=str(error)) from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return result

    @app.post("/internal/v1/releases/{release_id}/evaluate")
    def evaluate_release(
        release_id: UUID,
        payload: ReleaseEvaluateRequest,
        admin: str = Depends(require_approver),
    ) -> dict[str, object]:
        _require_action_confirmation(
            action="evaluate", resource_id=release_id, confirmation=payload.confirmation
        )
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="release_evaluate",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    "release:evaluate:" + str(release_id) + ":" + json.dumps(
                        payload.model_dump(exclude={"idempotency_key"}),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        try:
            result = ReleaseRepository(get_engine()).evaluate_and_advance(
                tenant_id=DEMO_TENANT_ID,
                release_id=release_id,
                actor_ref=admin,
                metrics=CanaryMetrics(
                    **payload.model_dump(exclude={"idempotency_key"})
                ),
            )
        except ReleaseTransitionError as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=409, detail=str(error)) from error
        encoded = cast(dict[str, object], jsonable_encoder(result))
        idempotency.complete(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=encoded)
        return result

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
                    runtime=payload.get("runtime"),
                    dataset_id=payload.get("dataset_id"),
                    dataset_version=payload.get("dataset_version"),
                    dataset_hash=payload.get("dataset_hash"),
                    manifest_hash=payload.get("manifest_hash"),
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

    @app.get("/v1/evals/{eval_run_id}/approval")
    def get_evaluation_approval(
        eval_run_id: str, actor_id: str = Depends(get_demo_actor)
    ) -> dict[str, object]:
        del actor_id
        report = _read_eval_report(eval_run_id)
        record = AuditRepository(get_engine()).latest_evaluation_approval(
            tenant_id=DEMO_TENANT_ID, eval_run_id=eval_run_id
        )
        return _evaluation_approval_projection(
            eval_run_id=eval_run_id, report=report, record=record
        )

    @app.post("/internal/v1/evals/{eval_run_id}/approval")
    def decide_evaluation_approval(
        eval_run_id: str,
        payload: EvaluationApprovalRequest,
        approver: str = Depends(require_approver),
    ) -> dict[str, object]:
        report = _read_eval_report(eval_run_id)
        raw_approval = report.get("human_approval")
        if not isinstance(raw_approval, dict) or raw_approval.get("required") is not True:
            raise HTTPException(status_code=409, detail="evaluation_approval_not_required")
        evaluation_uuid = UUID(eval_run_id)
        _require_action_confirmation(
            action="evaluation_approval",
            resource_id=evaluation_uuid,
            confirmation=payload.confirmation,
        )
        repository = AuditRepository(get_engine())
        existing = repository.latest_evaluation_approval(
            tenant_id=DEMO_TENANT_ID, eval_run_id=eval_run_id
        )
        if existing is not None and existing.get("status") in {"approved", "rejected"}:
            raise HTTPException(status_code=409, detail="evaluation_approval_already_decided")
        reason_hash = hash_secret(payload.reason)
        idempotency = ControlPlaneIdempotencyRepository(get_engine())
        try:
            claim = idempotency.claim(
                tenant_id=DEMO_TENANT_ID,
                operation="evaluation_human_approval",
                idempotency_key=payload.idempotency_key,
                request_fingerprint=hash_secret(
                    f"evaluation-approval:{eval_run_id}:{payload.decision}:{reason_hash}"
                ),
            )
        except (ControlPlaneIdempotencyConflictError, ControlPlaneIdempotencyInProgressError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not claim.acquired:
            return claim.response or {}
        status_value = "approved" if payload.decision == "approve" else "rejected"
        try:
            audit_id = repository.append(
                tenant_id=DEMO_TENANT_ID,
                actor_ref=approver,
                event_type="evaluation_human_approval",
                payload={
                    "eval_run_id": eval_run_id,
                    "decision": payload.decision,
                    "status": status_value,
                    "reason_hash": reason_hash,
                    "idempotency_key": payload.idempotency_key,
                },
                payload_hash=hash_secret(
                    f"evaluation-approval:{eval_run_id}:{payload.idempotency_key}:{reason_hash}"
                ),
            )
        except Exception as error:
            idempotency.abandon(tenant_id=DEMO_TENANT_ID, record_id=claim.record_id)
            raise HTTPException(status_code=503, detail="evaluation_approval_unavailable") from error
        record = {
            "approval_id": str(audit_id),
            "approver_ref": approver,
            "decided_at": datetime.now(UTC).isoformat(),
            "status": status_value,
            "decision": payload.decision,
            "reason_hash": reason_hash,
        }
        result = _evaluation_approval_projection(
            eval_run_id=eval_run_id, report=report, record=record
        )
        idempotency.complete(
            tenant_id=DEMO_TENANT_ID, record_id=claim.record_id, response=result
        )
        return result

    @app.get("/v1/evals/{eval_run_id}")
    def get_evaluation(eval_run_id: str, actor_id: str = Depends(get_demo_actor)) -> dict[str, Any]:
        del actor_id
        # Reports contain only redacted traces and aggregate metrics.
        return _read_eval_report(eval_run_id)

    @app.get("/v1/evals/{eval_run_id}/dashboard")
    def get_evaluation_dashboard(
        eval_run_id: str, actor_id: str = Depends(get_demo_actor)
    ) -> dict[str, Any]:
        del actor_id
        return build_eval_dashboard(_read_eval_report(eval_run_id))

    @app.get("/internal/v1/evals/{eval_run_id}/dashboard")
    def get_internal_evaluation_dashboard(
        eval_run_id: str, admin: str = Depends(require_admin)
    ) -> dict[str, Any]:
        del admin
        return build_eval_dashboard(_read_eval_report(eval_run_id))

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

    @app.get("/v1/evals/{eval_run_id}/cases/{case_id}")
    def get_evaluation_case_detail(
        eval_run_id: str,
        case_id: str,
        attempt_no: int = 1,
        actor_id: str = Depends(get_demo_actor),
    ) -> dict[str, Any]:
        del actor_id
        if attempt_no < 1 or attempt_no > 200:
            raise HTTPException(status_code=422, detail="invalid attempt number")
        report_path, _ = _eval_report_paths(eval_run_id)
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="evaluation not found")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        rows = [row for row in payload.get("results", []) if row.get("case_id") == case_id]
        if attempt_no > len(rows):
            raise HTTPException(status_code=404, detail="evaluation case not found")
        return build_eval_case_detail(rows[attempt_no - 1], attempt_no=attempt_no)

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
        if target is RunStatus.FAILED:
            try:
                FailureAttributionService(get_engine()).record_run_outcome(
                    tenant_id=DEMO_TENANT_ID,
                    run_id=ticket.run_id,
                    status=target.value,
                    terminal_reason="HUMAN_REVIEW_REJECTED",
                    route=context.workflow_id or str(context.state.get("route") or "terminal"),
                    human_rejected=True,
                )
            except Exception:
                # Failure learning is auxiliary to the already durable
                # handoff resolution and must not change its user outcome.
                pass
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

    @app.get("/v1/runs/{run_id}/visualization")
    def get_run_visualization(
        run_id: UUID,
        actor_id: str = Depends(get_demo_actor),
        runs: RunRepository = Depends(_run_repository),
    ) -> dict[str, object]:
        snapshot = runs.load_run(
            run_id=run_id,
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        events = runs.replay_events(
            run_id=run_id,
            tenant_id=DEMO_TENANT_ID,
            actor_id=actor_id,
        )
        evidence_ids: set[str] = set()
        for event in events:
            raw_ids = event.event.payload.get("evidence_ids")
            if isinstance(raw_ids, list):
                evidence_ids.update(item for item in raw_ids if isinstance(item, str))
        observability = RunObservabilityRepository(get_engine())
        return build_run_visualization(
            snapshot=snapshot,
            events=events,
            model_invocations=observability.model_invocations(
                run_id=run_id,
                tenant_id=DEMO_TENANT_ID,
            ),
            tool_invocations=observability.tool_invocations(
                run_id=run_id,
                tenant_id=DEMO_TENANT_ID,
            ),
            checkpoint=runs.load_latest_checkpoint(
                run_id=run_id,
                tenant_id=DEMO_TENANT_ID,
            ),
            evidence_count=len(evidence_ids),
        )

    @app.get("/internal/v1/runs/{run_id}/insight")
    def get_internal_run_insight(
        run_id: UUID,
        admin: str = Depends(require_admin),
    ) -> dict[str, object]:
        del admin
        runs = RunRepository(get_engine())
        snapshot = runs.load_run(run_id=run_id, tenant_id=DEMO_TENANT_ID)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        events = runs.replay_events(run_id=run_id, tenant_id=DEMO_TENANT_ID)
        evidence_ids: set[str] = set()
        for event in events:
            raw_ids = event.event.payload.get("evidence_ids")
            if isinstance(raw_ids, list):
                evidence_ids.update(item for item in raw_ids if isinstance(item, str))
        observability = RunObservabilityRepository(get_engine())
        return build_run_visualization(
            snapshot=snapshot,
            events=events,
            model_invocations=observability.model_invocations(
                run_id=run_id, tenant_id=DEMO_TENANT_ID
            ),
            tool_invocations=observability.tool_invocations(
                run_id=run_id, tenant_id=DEMO_TENANT_ID
            ),
            checkpoint=runs.load_latest_checkpoint(
                run_id=run_id, tenant_id=DEMO_TENANT_ID
            ),
            evidence_count=len(evidence_ids),
            include_event_path=True,
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

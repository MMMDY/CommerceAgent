"""Strict, versioned contracts shared by runtime, workflow, and evaluation code."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"


class Contract(BaseModel):
    """Base for persisted and externally exchanged contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class SlotSource(StrEnum):
    USER = "user"
    TOOL = "tool"
    POLICY = "policy"
    SYSTEM = "system"


class SlotValue(Contract):
    value: str | int | float | bool | list[str] | None
    source: SlotSource
    verified: bool = False


class Message(Contract):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=8000)


class PromptView(Contract):
    system_policy_version: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    workflow_version: str = Field(min_length=1, max_length=64)
    current_step: str = Field(min_length=1, max_length=128)
    allowed_decisions: tuple[str, ...]
    conversation: tuple[Message, ...]
    known_slots: dict[str, SlotValue]
    required_slots: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    remaining_steps: int = Field(ge=0, le=6)


class RoutingPromptView(Contract):
    """Minimal untrusted conversation view allowed in intent classification."""

    conversation: tuple[Message, ...]
    allowed_intents: tuple[str, ...] = Field(min_length=1)
    known_slots: tuple[str, ...] = ()


class RiskHint(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    UNKNOWN = "unknown"


class IntentClassification(Contract):
    """Model-produced candidate; it never carries an execution mode."""

    intent: str = Field(min_length=1, max_length=128)
    risk_hint: RiskHint
    route_hint: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    required_slots: tuple[str, ...] = ()


class StatePatch(Contract):
    set_values: dict[str, Any] = Field(default_factory=dict)
    remove_keys: tuple[str, ...] = ()


class RunStatus(StrEnum):
    CREATED = "created"
    ROUTING = "routing"
    RUNNING_READONLY = "running_readonly"
    RUNNING_WORKFLOW = "running_workflow"
    WAITING_USER = "waiting_user"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMMITTING = "committing"
    VERIFYING = "verifying"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ExecutionMode(StrEnum):
    """The only two persisted automatic execution shapes."""

    READONLY_LOOP = "readonly_loop"
    WORKFLOW = "workflow"


class RunContext(Contract):
    run_id: UUID
    conversation_id: UUID
    tenant_id: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=128)
    execution_mode: ExecutionMode | None = None
    workflow_id: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_version: str | None = Field(default=None, min_length=1, max_length=64)
    status: RunStatus
    state: dict[str, Any] = Field(default_factory=dict)
    step_count: int = Field(default=0, ge=0, le=6)
    checkpoint_version: int = Field(default=0, ge=0)


class DecisionType(StrEnum):
    RESPOND = "respond"
    ASK_USER = "ask_user"
    CALL_TOOL = "call_tool"
    HANDOFF = "handoff"
    FINISH = "finish"


class Decision(Contract):
    type: DecisionType
    intent: str = Field(min_length=1, max_length=128)
    route: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    missing_slots: tuple[str, ...] = ()
    tool: str | None = Field(default=None, max_length=128)
    args: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    response: str | None = Field(default=None, max_length=8000)
    handoff_reason: str | None = Field(default=None, max_length=256)


class StepStatus(StrEnum):
    CONTINUE = "continue"
    WAIT_USER = "wait_user"
    WAIT_HUMAN = "wait_human"
    COMPLETE = "complete"
    FAIL = "fail"


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    STEP_COMPLETED = "step_completed"
    TOOL_CALLED = "tool_called"
    TOOL_OBSERVED = "tool_observed"
    WAITING_FOR_USER = "waiting_for_user"
    FAILED = "failed"
    MUTATION_PREPARED = "mutation_prepared"
    USER_CONFIRMED = "user_confirmed"
    COMMIT_STARTED = "commit_started"
    COMMIT_OBSERVED = "commit_observed"
    STATE_VERIFIED = "state_verified"
    MUTATION_UNCERTAIN = "mutation_uncertain"
    HANDOFF_CREATED = "handoff_created"
    HANDOFF_RESOLVED = "handoff_resolved"


class DomainEvent(Contract):
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class EventEnvelope(Contract):
    event_id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    occurred_at: datetime
    event: DomainEvent


class Step(Contract):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)


class StepResult(Contract):
    status: StepStatus
    state_patch: StatePatch = Field(default_factory=StatePatch)
    events: tuple[DomainEvent, ...] = ()
    next_step: str | None = Field(default=None, max_length=128)


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    PREPARE = "prepare"
    LOW_WRITE = "low_write"
    COMMIT = "commit"


class RetryPolicy(Contract):
    max_attempts: int = Field(ge=1, le=2)
    backoff_ms: tuple[int, ...] = ()


class ResourceBinding(Contract):
    """Trusted resource ownership check required before an adapter call."""

    argument: str = Field(min_length=1, max_length=128)
    owner_check: str = Field(min_length=1, max_length=128)


class ToolSpec(Contract):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk: ToolRisk
    required_scopes: tuple[str, ...]
    timeout_ms: int = Field(ge=1, le=30_000)
    retry_policy: RetryPolicy
    model_visible: bool
    allowed_workflows: tuple[str, ...] = ()
    allowed_steps: tuple[str, ...] = ()
    resource_binding: ResourceBinding | None = None


class ToolContext(Contract):
    request_id: UUID
    run_id: UUID
    conversation_id: UUID
    tenant_id: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=128)
    scopes: tuple[str, ...]
    workflow_id: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_version: str | None = Field(default=None, min_length=1, max_length=64)
    current_step: str | None = Field(default=None, min_length=1, max_length=128)
    policy_version: str | None = Field(default=None, min_length=1, max_length=64)


class ToolErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONFLICT = "CONFLICT"
    POLICY_DENIED = "POLICY_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolError(Contract):
    code: ToolErrorCode
    retryable: bool
    message: str = Field(min_length=1, max_length=512)


class ToolResult(Contract):
    tool_name: str
    tool_version: str
    data: dict[str, Any] | None = None
    error: ToolError | None = None

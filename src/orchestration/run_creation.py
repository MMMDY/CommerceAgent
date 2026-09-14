"""Immutable inputs and persistence boundary for creating one agent run."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.protocols import RunContext


class ExecutionMode(StrEnum):
    """The two runtime execution shapes persisted with every run."""

    READONLY_LOOP = "readonly_loop"
    WORKFLOW = "workflow"


class RunCreationSpec(BaseModel):
    """Configuration frozen at creation and never inferred again on resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_mode: ExecutionMode
    policy_version: str = Field(min_length=1, max_length=64)
    model_config_hash: str = Field(min_length=1, max_length=80)
    prompt_version: str = Field(min_length=1, max_length=64)
    current_step: str = Field(min_length=1, max_length=64)
    max_steps: int = Field(default=6, ge=1, le=6)
    deadline_at: datetime
    parent_run_id: UUID | None = None

    @field_validator("deadline_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline_at must be timezone-aware")
        return value


class RunCreationStore(Protocol):
    """Injected durable boundary used by ``OrchestrationEngine.create``."""

    def create_run(self, *, context: RunContext, spec: RunCreationSpec) -> None: ...

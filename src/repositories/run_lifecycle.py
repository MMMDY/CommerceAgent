"""Tenant-scoped creation and immutable-definition lookup for agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.orchestration.run_creation import ExecutionMode, RunCreationSpec
from src.protocols import RunContext, RunStatus


@dataclass(frozen=True, slots=True)
class RunDefinitionSnapshot:
    """The durable configuration selected when a run was created."""

    run_id: UUID
    tenant_id: str
    workflow_id: str
    workflow_version: str
    policy_version: str
    model_config_hash: str
    prompt_version: str
    execution_mode: ExecutionMode
    current_step: str
    max_steps: int
    deadline_at: datetime


class RunLifecycleRepository:
    """Creates runs without consulting mutable current-version pointers."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_run(self, *, context: RunContext, spec: RunCreationSpec) -> None:
        if context.status is not RunStatus.CREATED:
            raise ValueError("a persisted run must start in created status")
        if context.step_count != 0 or context.checkpoint_version != 0:
            raise ValueError("a persisted run must start without completed steps")
        now = datetime.now(UTC)
        if spec.deadline_at <= now:
            raise ValueError("run deadline must be in the future")
        with self._engine.begin() as connection:
            created = connection.execute(
                text(
                    "INSERT INTO runtime.agent_runs "
                    "(run_id, conversation_id, parent_run_id, tenant_id, actor_ref, status, "
                    "execution_mode, workflow_id, workflow_version, policy_version, "
                    "model_config_hash, prompt_version, current_step, step_count, max_steps, "
                    "deadline_at, created_at, updated_at) "
                    "SELECT :run_id, conversation.id, :parent_run_id, "
                    "CAST(:tenant_id AS varchar(64)), CAST(:actor_ref AS varchar(128)), "
                    ":status, :execution_mode, :workflow_id, :workflow_version, :policy_version, "
                    ":model_config_hash, :prompt_version, :current_step, 0, :max_steps, "
                    ":deadline_at, :now, :now FROM conversation.conversations AS conversation "
                    "WHERE conversation.id = :conversation_id "
                    "AND conversation.tenant_id = CAST(:tenant_id AS varchar(64)) "
                    "AND conversation.actor_id = CAST(:actor_ref AS varchar(128))"
                ),
                {
                    "run_id": context.run_id,
                    "conversation_id": context.conversation_id,
                    "parent_run_id": spec.parent_run_id,
                    "tenant_id": context.tenant_id,
                    "actor_ref": context.actor_id,
                    "status": context.status.value,
                    "execution_mode": spec.execution_mode.value,
                    "workflow_id": context.workflow_id,
                    "workflow_version": context.workflow_version,
                    "policy_version": spec.policy_version,
                    "model_config_hash": spec.model_config_hash,
                    "prompt_version": spec.prompt_version,
                    "current_step": spec.current_step,
                    "max_steps": spec.max_steps,
                    "deadline_at": spec.deadline_at,
                    "now": now,
                },
            )
            if created.rowcount != 1:
                raise ValueError("conversation is unavailable for this tenant and actor")

    def load_definition(self, *, run_id: UUID, tenant_id: str) -> RunDefinitionSnapshot | None:
        """Read the creation-time version pins through the tenant boundary."""

        statement = text(
            "SELECT run_id, tenant_id, workflow_id, workflow_version, policy_version, "
            "model_config_hash, prompt_version, execution_mode, current_step, max_steps, "
            "deadline_at FROM runtime.agent_runs "
            "WHERE run_id = :run_id AND tenant_id = :tenant_id"
        )
        with self._engine.connect() as connection:
            row = connection.execute(
                statement, {"run_id": run_id, "tenant_id": tenant_id}
            ).one_or_none()
        if row is None:
            return None
        values = dict(row._mapping)
        values["execution_mode"] = ExecutionMode(values["execution_mode"])
        return RunDefinitionSnapshot(**values)

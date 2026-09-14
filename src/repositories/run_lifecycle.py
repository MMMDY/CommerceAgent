"""Tenant-scoped creation and immutable-definition lookup for agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.orchestration.router import RouteDecision, RouteOutcome
from src.orchestration.run_creation import RunCreationSpec
from src.protocols import ExecutionMode, RunContext, RunStatus


@dataclass(frozen=True, slots=True)
class RunDefinitionSnapshot:
    """The durable configuration selected when a run was created."""

    run_id: UUID
    tenant_id: str
    workflow_id: str | None
    workflow_version: str | None
    policy_version: str
    model_config_hash: str
    prompt_version: str
    execution_mode: ExecutionMode | None
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
                    "SELECT CAST(:run_id AS uuid), conversation.id, CAST(:parent_run_id AS uuid), "
                    "CAST(:tenant_id AS varchar(64)), CAST(:actor_ref AS varchar(128)), "
                    "CAST(:status AS varchar(32)), CAST(:execution_mode AS varchar(24)), "
                    "CAST(:workflow_id AS varchar(64)), CAST(:workflow_version AS varchar(32)), "
                    "CAST(:policy_version AS varchar(64)), "
                    "CAST(:model_config_hash AS varchar(80)), "
                    "CAST(:prompt_version AS varchar(64)), CAST(:current_step AS varchar(64)), "
                    "0, CAST(:max_steps AS integer), CAST(:deadline_at AS timestamptz), "
                    "CAST(:now AS timestamptz), CAST(:now AS timestamptz) "
                    "FROM conversation.conversations AS conversation "
                    "WHERE conversation.id = CAST(:conversation_id AS uuid) "
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
                    "execution_mode": (
                        spec.execution_mode.value if spec.execution_mode is not None else None
                    ),
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

    def cancel_unstarted_run(self, *, run_id: UUID, tenant_id: str, reason: str) -> None:
        """Release a run reservation that could not be attached to a message.

        This is used only for the narrow idempotency race where another request
        inserted the same client message between reservation and projection.
        Keeping the reservation terminal prevents it from blocking subsequent
        requests through the one-active-run conversation constraint.
        """

        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE runtime.agent_runs SET status = 'cancelled', "
                    "current_step = 'terminal', terminal_reason = :reason, updated_at = now() "
                    "WHERE run_id = :run_id AND tenant_id = :tenant_id AND status = 'created'"
                ),
                {"run_id": run_id, "tenant_id": tenant_id, "reason": reason},
            )

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
        if values["execution_mode"] is not None:
            values["execution_mode"] = ExecutionMode(values["execution_mode"])
        return RunDefinitionSnapshot(**values)


class RunRoutingRepository:
    """Persist a Router-owned executor choice exactly once per run."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def select_route(self, *, context: RunContext, decision: RouteDecision) -> None:
        if context.status not in {RunStatus.CREATED, RunStatus.ROUTING}:
            raise ValueError("only a pre-route run can select an executor")
        if decision.outcome is RouteOutcome.HANDOFF:
            statement = text(
                "UPDATE runtime.agent_runs SET status = 'waiting_human', "
                "current_step = 'terminal', "
                "terminal_reason = :reason, updated_at = now() "
                "WHERE run_id = :run_id AND tenant_id = :tenant_id "
                "AND status IN ('created', 'routing') AND execution_mode IS NULL"
            )
            parameters = {
                "run_id": context.run_id,
                "tenant_id": context.tenant_id,
                "reason": decision.reason_code,
            }
        else:
            assert decision.execution_mode is not None
            assert decision.workflow_id is not None
            assert decision.workflow_version is not None
            status = (
                RunStatus.RUNNING_READONLY
                if decision.execution_mode is ExecutionMode.READONLY_LOOP
                else RunStatus.RUNNING_WORKFLOW
            )
            statement = text(
                "UPDATE runtime.agent_runs SET execution_mode = :execution_mode, "
                "workflow_id = :workflow_id, workflow_version = :workflow_version, "
                "status = :status, updated_at = now() "
                "WHERE run_id = :run_id AND tenant_id = :tenant_id "
                "AND status IN ('created', 'routing') AND execution_mode IS NULL"
            )
            parameters = {
                "run_id": context.run_id,
                "tenant_id": context.tenant_id,
                "execution_mode": decision.execution_mode.value,
                "workflow_id": decision.workflow_id,
                "workflow_version": decision.workflow_version,
                "status": status.value,
            }
        with self._engine.begin() as connection:
            result = connection.execute(statement, parameters)
        if result.rowcount != 1:
            raise ValueError("route selection was stale, unavailable, or already selected")

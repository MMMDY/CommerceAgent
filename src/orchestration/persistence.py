"""PostgreSQL implementation of the orchestration checkpoint boundary."""

from __future__ import annotations

from hashlib import sha256
from json import dumps
from uuid import UUID, uuid4

from src.orchestration.engine import CheckpointStore
from src.protocols import DomainEvent, RunContext, RunStatus
from src.repositories.runs import RunRepository


class RepositoryCheckpointStore(CheckpointStore):
    """Persists one reduced runtime state and all domain events atomically."""

    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository

    def checkpoint(
        self,
        *,
        context: RunContext,
        status: RunStatus,
        next_step: str,
        state: dict[str, object],
        events: tuple[DomainEvent, ...],
    ) -> int:
        next_context = context.model_copy(
            update={
                "status": status,
                "state": state,
                "step_count": context.step_count + 1,
                "checkpoint_version": context.checkpoint_version + 1,
            }
        )
        checkpoint = next_context.model_dump(mode="json")
        serialized = dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result = self._repository.commit_step(
            run_id=context.run_id,
            tenant_id=context.tenant_id,
            expected_version=context.checkpoint_version,
            next_status=status.value,
            next_step=next_step,
            checkpoint=checkpoint,
            checkpoint_hash=_hash(serialized),
            events=[_event(event, next_step) for event in events],
        )
        return result.row_version

    def resume(self, *, run_id: UUID, tenant_id: str) -> RunContext | None:
        state = self._repository.load_latest_checkpoint(run_id=run_id, tenant_id=tenant_id)
        return RunContext.model_validate(state) if state is not None else None


def _event(event: DomainEvent, step_id: str) -> dict[str, object]:
    payload = event.payload
    serialized = dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return {
        "event_id": uuid4(),
        "event_type": event.event_type.value,
        "step_id": step_id,
        "payload": serialized,
        "payload_hash": _hash(serialized),
        "correlation_id": uuid4(),
    }


def _hash(serialized: str) -> str:
    return f"sha256:{sha256(serialized.encode()).hexdigest()}"

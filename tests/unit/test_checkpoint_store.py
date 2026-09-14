from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from src.orchestration.persistence import RepositoryCheckpointStore
from src.protocols import DomainEvent, EventType, RunContext, RunStatus
from src.repositories.runs import RunRepository, RunSnapshot


class _Repository:
    def __init__(self) -> None:
        self.checkpoint: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] | None = None

    def commit_step(self, **kwargs: Any) -> RunSnapshot:
        self.checkpoint = kwargs["checkpoint"]
        self.events = kwargs["events"]
        return RunSnapshot(kwargs["run_id"], kwargs["tenant_id"], "completed", "terminal", 1, 1)

    def load_latest_checkpoint(self, **_: Any) -> dict[str, Any] | None:
        return self.checkpoint


def _context() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        workflow_id="w",
        workflow_version="1",
        status=RunStatus.RUNNING_READONLY,
    )


def test_repository_checkpoint_store_persists_recoverable_context_and_safe_event() -> None:
    repository = _Repository()
    store = RepositoryCheckpointStore(cast(RunRepository, repository))
    context = _context()
    version = store.checkpoint(
        context=context,
        status=RunStatus.COMPLETED,
        next_step="terminal",
        state={"safe": "state"},
        events=(DomainEvent(event_type=EventType.STEP_COMPLETED, payload={"result": "ok"}),),
    )
    assert version == 1
    assert repository.checkpoint is not None
    assert repository.checkpoint["status"] == "completed"
    assert repository.checkpoint["state"] == {"safe": "state"}
    assert repository.events is not None
    assert repository.events[0]["payload_hash"].startswith("sha256:")
    restored = store.resume(run_id=context.run_id, tenant_id="t")
    assert restored is not None
    assert restored.status is RunStatus.COMPLETED

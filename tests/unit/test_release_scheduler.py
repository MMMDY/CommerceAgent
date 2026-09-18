from __future__ import annotations

from uuid import uuid4

import pytest

from src.release.canary_guard import CanaryMetrics
from src.release.scheduler import ReleaseObservationScheduler


class FakeReleaseRepository:
    def __init__(self) -> None:
        self.release_id = uuid4()
        self.evaluated: list[str] = []

    def due_for_evaluation(self, *, tenant_id: str) -> tuple[dict[str, object], ...]:
        assert tenant_id == "tenant-a"
        return ({"release_id": self.release_id},)

    def canary_metrics(self, *, tenant_id: str, release_id: object) -> CanaryMetrics:
        assert tenant_id == "tenant-a"
        assert release_id == self.release_id
        return CanaryMetrics(
            quality_gate_pass=True,
            safety_gate_pass=True,
            terminal_response_coverage=1.0,
        )

    def evaluate_and_advance(
        self,
        *,
        tenant_id: str,
        release_id: object,
        actor_ref: str,
        metrics: CanaryMetrics,
    ) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        assert release_id == self.release_id
        assert actor_ref == "scheduler-test"
        assert metrics.terminal_response_coverage == 1.0
        self.evaluated.append(str(release_id))
        return {"release_id": release_id, "stage": "CANARY_5", "status": "ACTIVE"}


def test_scheduler_evaluates_only_due_releases() -> None:
    repository = FakeReleaseRepository()
    scheduler = ReleaseObservationScheduler(
        repository, tenant_id="tenant-a", actor_ref="scheduler-test"
    )

    results = scheduler.run_once()

    assert len(results) == 1
    assert results[0].status == "ACTIVE"
    assert results[0].stage == "CANARY_5"
    assert repository.evaluated == [str(repository.release_id)]


def test_scheduler_rejects_unbounded_fast_polling() -> None:
    with pytest.raises(ValueError, match="at_least_10"):
        ReleaseObservationScheduler(
            FakeReleaseRepository(), tenant_id="tenant-a", interval_seconds=1
        )

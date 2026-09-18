"""Single-process release observation scheduler.

The scheduler is intentionally opt-in.  It only evaluates observation windows
that the database says are due, and every state change is still serialized by
``ReleaseRepository.evaluate_and_advance``.  Missing candidate evidence is
handled by the repository's fail-closed metrics rather than by a guessed
healthy result.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock, Thread

from src.repositories.releases import ReleaseRepository, ReleaseTransitionError


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    release_id: str
    status: str
    stage: str | None = None
    error: str | None = None


class ReleaseObservationScheduler:
    """Run due release checks on a bounded, graceful background loop."""

    def __init__(
        self,
        repository: ReleaseRepository,
        *,
        tenant_id: str,
        actor_ref: str = "release-scheduler",
        interval_seconds: int = 60,
    ) -> None:
        if interval_seconds < 10:
            raise ValueError("interval_seconds_must_be_at_least_10")
        self._repository = repository
        self._tenant_id = tenant_id
        self._actor_ref = actor_ref
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._run_lock = Lock()
        self._thread: Thread | None = None

    def run_once(self) -> tuple[SchedulerResult, ...]:
        """Evaluate each currently due release exactly once."""

        if not self._run_lock.acquire(blocking=False):
            return ()
        try:
            results: list[SchedulerResult] = []
            for release in self._repository.due_for_evaluation(tenant_id=self._tenant_id):
                release_id = str(release["release_id"])
                try:
                    metrics = self._repository.canary_metrics(
                        tenant_id=self._tenant_id,
                        release_id=release["release_id"],
                    )
                    updated = self._repository.evaluate_and_advance(
                        tenant_id=self._tenant_id,
                        release_id=release["release_id"],
                        actor_ref=self._actor_ref,
                        metrics=metrics,
                    )
                    results.append(
                        SchedulerResult(
                            release_id=release_id,
                            status=str(updated.get("status", "unknown")),
                            stage=str(updated.get("stage")) if updated.get("stage") else None,
                        )
                    )
                except ReleaseTransitionError as error:
                    # A concurrent worker may have consumed the same window;
                    # record the result and continue evaluating other tenants'
                    # releases on the next tick.
                    results.append(
                        SchedulerResult(
                            release_id=release_id,
                            status="not_transitioned",
                            error=str(error),
                        )
                    )
            return tuple(results)
        finally:
            self._run_lock.release()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._loop, name="commerce-agent-release-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                # A transient database failure must not terminate the process
                # or turn a failed observation into a promotion.
                pass
            self._stop.wait(self._interval_seconds)


__all__ = ["ReleaseObservationScheduler", "SchedulerResult"]

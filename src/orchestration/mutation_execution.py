"""Crash-safe boundary for externally visible mutation adapters.

Exactly-once delivery cannot be guaranteed across PostgreSQL and an arbitrary
external service.  This boundary therefore guarantees the safer contract:

* a durable intent is claimed before the external call;
* the stable intent UUID is always the upstream idempotency key;
* the adapter is invoked only from ``reserved``;
* an orphaned ``in_progress`` intent becomes ``unknown`` during recovery and
  is never invoked again;
* the adapter outcome is committed by the caller in the same transaction as
  the post-tool checkpoint and its outbox messages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.mutation_safety import (
    MutationAdapterResult,
    MutationAdapterStatus,
    MutationCompletion,
    MutationExecutionClaim,
    MutationExecutionIntent,
    MutationExecutionStatus,
    StoredMutationExecution,
)


class MutationIntentStore(Protocol):
    def load(self, intent: MutationExecutionIntent) -> StoredMutationExecution | None: ...

    def claim(self, intent: MutationExecutionIntent) -> MutationExecutionClaim: ...


class MutationExecutionError(RuntimeError):
    """The durable mutation boundary could not safely execute the intent."""


@dataclass(frozen=True, slots=True)
class MutationExecutionOutcome:
    status: MutationExecutionStatus
    business_reference: str | None
    response_redacted: dict[str, object]
    reused: bool


MutationAdapter = Callable[[str], MutationAdapterResult]
MutationCheckpoint = Callable[[MutationCompletion], None]


class DurableMutationBoundary:
    def __init__(self, store: MutationIntentStore) -> None:
        self._store = store

    def execute(
        self,
        *,
        intent: MutationExecutionIntent,
        adapter: MutationAdapter,
        checkpoint: MutationCheckpoint,
        after_adapter: Callable[[], None] | None = None,
    ) -> MutationExecutionOutcome:
        """Execute at most once and require durable completion via ``checkpoint``.

        ``after_adapter`` exists solely as a deterministic fault-injection seam.
        Production callers should leave it unset.
        """

        current = self._require_intent(intent)
        replay = _replay(current)
        if replay is not None:
            return replay
        claim = self._store.claim(intent)
        if not claim.acquired:
            replay = _replay(claim.execution)
            if replay is not None:
                return replay
            return _unknown(reused=True)
        if claim.execution.status is not MutationExecutionStatus.IN_PROGRESS:
            raise MutationExecutionError("claimed mutation did not enter in_progress")

        try:
            adapter_result = adapter(str(intent.record_id))
        except Exception:
            adapter_result = MutationAdapterResult(status=MutationAdapterStatus.UNKNOWN)
        if after_adapter is not None:
            after_adapter()
        completion = _completion(intent, adapter_result)
        checkpoint(completion)
        return MutationExecutionOutcome(
            status=completion.status,
            business_reference=completion.business_reference,
            response_redacted=dict(completion.response_redacted),
            reused=False,
        )

    def recover(
        self, *, intent: MutationExecutionIntent, checkpoint: MutationCheckpoint
    ) -> MutationExecutionOutcome:
        """Resolve an orphaned claim without ever repeating its external call."""

        current = self._require_intent(intent)
        if current.status is MutationExecutionStatus.RESERVED:
            # No worker crossed the durable claim boundary, so there cannot be
            # an external side effect to recover yet.
            return _unknown(reused=True)
        if current.status is not MutationExecutionStatus.IN_PROGRESS:
            replay = _replay(current)
            if replay is None:  # pragma: no cover - exhaustive status guard
                raise MutationExecutionError("invalid durable mutation state")
            return replay
        completion = MutationCompletion(
            record_id=intent.record_id,
            request_fingerprint=intent.request_fingerprint,
            status=MutationExecutionStatus.UNKNOWN,
        )
        checkpoint(completion)
        return _unknown(reused=True)

    def _require_intent(self, intent: MutationExecutionIntent) -> StoredMutationExecution:
        stored = self._store.load(intent)
        if stored is None:
            raise MutationExecutionError("durable mutation intent is unavailable")
        return stored


def _completion(
    intent: MutationExecutionIntent, result: MutationAdapterResult
) -> MutationCompletion:
    status = {
        MutationAdapterStatus.SUCCEEDED: MutationExecutionStatus.SUCCEEDED,
        MutationAdapterStatus.REJECTED: MutationExecutionStatus.FAILED,
        MutationAdapterStatus.UNKNOWN: MutationExecutionStatus.UNKNOWN,
    }[result.status]
    return MutationCompletion(
        record_id=intent.record_id,
        request_fingerprint=intent.request_fingerprint,
        status=status,
        business_reference=result.business_reference,
        response_redacted=dict(result.response_redacted),
    )


def _replay(stored: StoredMutationExecution) -> MutationExecutionOutcome | None:
    if stored.status is MutationExecutionStatus.RESERVED:
        return None
    if stored.status is MutationExecutionStatus.IN_PROGRESS:
        return _unknown(reused=True)
    return MutationExecutionOutcome(
        status=stored.status,
        business_reference=stored.business_reference,
        response_redacted=dict(stored.response_redacted or {}),
        reused=True,
    )


def _unknown(*, reused: bool) -> MutationExecutionOutcome:
    return MutationExecutionOutcome(
        status=MutationExecutionStatus.UNKNOWN,
        business_reference=None,
        response_redacted={},
        reused=reused,
    )

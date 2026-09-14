"""Fault-injection tests for the durable mutation execution boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

import pytest

from src.mutation_safety import (
    MutationAdapterResult,
    MutationAdapterStatus,
    MutationCompletion,
    MutationExecutionClaim,
    MutationExecutionIntent,
    MutationExecutionStatus,
    StoredMutationExecution,
)
from src.orchestration.mutation_execution import DurableMutationBoundary


class SimulatedProcessCrash(BaseException):
    """A hard crash must bypass normal adapter error handling."""


class MemoryIntentStore:
    def __init__(self, intent: MutationExecutionIntent) -> None:
        self._lock = Lock()
        self.value = StoredMutationExecution(intent, MutationExecutionStatus.RESERVED)

    def load(self, intent: MutationExecutionIntent) -> StoredMutationExecution | None:
        with self._lock:
            if self.value.intent != intent:
                return None
            return self.value

    def claim(self, intent: MutationExecutionIntent) -> MutationExecutionClaim:
        with self._lock:
            if self.value.intent != intent:
                raise RuntimeError("intent unavailable")
            if self.value.status is MutationExecutionStatus.RESERVED:
                self.value = StoredMutationExecution(intent, MutationExecutionStatus.IN_PROGRESS)
                return MutationExecutionClaim(self.value, acquired=True)
            return MutationExecutionClaim(self.value, acquired=False)

    def commit(self, completion: MutationCompletion) -> None:
        with self._lock:
            assert self.value.status is MutationExecutionStatus.IN_PROGRESS
            assert completion.record_id == self.value.intent.record_id
            assert completion.request_fingerprint == self.value.intent.request_fingerprint
            self.value = StoredMutationExecution(
                self.value.intent,
                completion.status,
                completion.business_reference,
                dict(completion.response_redacted),
            )


def _intent() -> MutationExecutionIntent:
    return MutationExecutionIntent(
        record_id=uuid4(),
        tenant_id="tenant-a",
        operation="commit_refund",
        request_fingerprint="sha256:request",
    )


def test_crash_after_side_effect_recovers_unknown_without_repeating_adapter() -> None:
    intent = _intent()
    store = MemoryIntentStore(intent)
    boundary = DurableMutationBoundary(store)
    adapter_calls: list[str] = []

    def adapter(idempotency_key: str) -> MutationAdapterResult:
        adapter_calls.append(idempotency_key)
        return MutationAdapterResult(
            status=MutationAdapterStatus.SUCCEEDED,
            business_reference="refund-1",
            response_redacted={"state": "accepted"},
        )

    with pytest.raises(SimulatedProcessCrash):
        boundary.execute(
            intent=intent,
            adapter=adapter,
            checkpoint=store.commit,
            after_adapter=lambda: (_ for _ in ()).throw(SimulatedProcessCrash()),
        )

    assert store.value.status is MutationExecutionStatus.IN_PROGRESS
    recovered = boundary.recover(intent=intent, checkpoint=store.commit)
    assert recovered.status is MutationExecutionStatus.UNKNOWN
    assert recovered.reused is True
    assert store.value.status is MutationExecutionStatus.UNKNOWN

    replay = boundary.execute(intent=intent, adapter=adapter, checkpoint=store.commit)
    assert replay.status is MutationExecutionStatus.UNKNOWN
    assert replay.reused is True
    assert adapter_calls == [str(intent.record_id)]


def test_crash_after_atomic_checkpoint_reuses_success_without_repeating_adapter() -> None:
    intent = _intent()
    store = MemoryIntentStore(intent)
    boundary = DurableMutationBoundary(store)
    adapter_calls = 0

    def adapter(idempotency_key: str) -> MutationAdapterResult:
        nonlocal adapter_calls
        adapter_calls += 1
        assert idempotency_key == str(intent.record_id)
        return MutationAdapterResult(
            status=MutationAdapterStatus.SUCCEEDED,
            business_reference="refund-2",
            response_redacted={"state": "accepted"},
        )

    def commit_then_crash(completion: MutationCompletion) -> None:
        store.commit(completion)
        raise SimulatedProcessCrash

    with pytest.raises(SimulatedProcessCrash):
        boundary.execute(intent=intent, adapter=adapter, checkpoint=commit_then_crash)

    replay = boundary.execute(intent=intent, adapter=adapter, checkpoint=store.commit)
    assert replay.status is MutationExecutionStatus.SUCCEEDED
    assert replay.business_reference == "refund-2"
    assert replay.response_redacted == {"state": "accepted"}
    assert replay.reused is True
    assert adapter_calls == 1


def test_adapter_exception_is_checkpointed_unknown_and_never_retried() -> None:
    intent = _intent()
    store = MemoryIntentStore(intent)
    boundary = DurableMutationBoundary(store)
    adapter_calls = 0

    def adapter(_: str) -> MutationAdapterResult:
        nonlocal adapter_calls
        adapter_calls += 1
        raise TimeoutError("ambiguous upstream timeout")

    first = boundary.execute(intent=intent, adapter=adapter, checkpoint=store.commit)
    replay = boundary.execute(intent=intent, adapter=adapter, checkpoint=store.commit)

    assert first.status is MutationExecutionStatus.UNKNOWN
    assert first.reused is False
    assert replay.status is MutationExecutionStatus.UNKNOWN
    assert replay.reused is True
    assert adapter_calls == 1


def test_concurrent_execution_claim_allows_only_one_adapter_call() -> None:
    intent = _intent()
    store = MemoryIntentStore(intent)
    boundary = DurableMutationBoundary(store)
    adapter_started = Event()
    release_adapter = Event()
    adapter_calls = 0

    def adapter(_: str) -> MutationAdapterResult:
        nonlocal adapter_calls
        adapter_calls += 1
        adapter_started.set()
        assert release_adapter.wait(timeout=2)
        return MutationAdapterResult(status=MutationAdapterStatus.SUCCEEDED)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            boundary.execute, intent=intent, adapter=adapter, checkpoint=store.commit
        )
        assert adapter_started.wait(timeout=2)
        second = executor.submit(
            boundary.execute, intent=intent, adapter=adapter, checkpoint=store.commit
        )
        second_result = second.result(timeout=2)
        release_adapter.set()
        first_result = first.result(timeout=2)

    assert first_result.status is MutationExecutionStatus.SUCCEEDED
    assert second_result.status is MutationExecutionStatus.UNKNOWN
    assert second_result.reused is True
    assert adapter_calls == 1

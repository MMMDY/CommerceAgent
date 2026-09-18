"""Fixture isolation and Runtime-to-evaluator trace adaptation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.harness.schema import EvalCase, NormalizedTrace


class FixtureManager:
    """Provides a deep-copied case context for every independent execution."""

    def create(self, case: EvalCase) -> dict[str, Any]:
        return deepcopy(case.context)


@dataclass(frozen=True, slots=True)
class RuntimeTrace:
    route: str | None
    intent: str | None
    next_action: str | None
    args: dict[str, Any]
    tools_called: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    response: str
    status: str
    run_id: str | None = None
    e2e_latency_ms: int | None = None
    model_invocation_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_microusd: int | None = None
    usage_estimated_count: int | None = None


class TraceAdapter:
    def normalize(self, *, case_id: str, trace: RuntimeTrace) -> NormalizedTrace:
        return NormalizedTrace(
            case_id=case_id,
            route=trace.route,
            intent=trace.intent,
            next_action=trace.next_action,
            args=deepcopy(trace.args),
            tools_called=trace.tools_called,
            evidence_ids=trace.evidence_ids,
            response=trace.response,
            status=trace.status,  # type: ignore[arg-type]
            run_id=trace.run_id,
        )

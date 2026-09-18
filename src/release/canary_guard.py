"""Fail-closed release guard used by both scheduled checks and API workers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanaryMetrics:
    p0_events: int = 0
    quality_gate_pass: bool | None = None
    safety_gate_pass: bool | None = None
    terminal_response_coverage: float | None = None
    p95_e2e_ms: float | None = None
    baseline_p95_e2e_ms: float | None = None
    p99_e2e_ms: float | None = None
    baseline_p99_e2e_ms: float | None = None
    p95_cost_microusd: float | None = None
    baseline_p95_cost_microusd: float | None = None
    low_risk_handoff_rate: float | None = None
    baseline_low_risk_handoff_rate: float | None = None
    skill_scope_violation: bool = False
    target_slice_quality_delta: float | None = None
    # Optional redacted comparison facts used by the release report.  They
    # never affect routing or execute a candidate runtime.
    current_route: str | None = None
    candidate_route: str | None = None
    current_response_policy: str | None = None
    candidate_response_policy: str | None = None
    current_skill: str | None = None
    candidate_skill: str | None = None
    quality_delta: float | None = None
    safety_delta: float | None = None


@dataclass(frozen=True, slots=True)
class CanaryDecision:
    stop: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StageTransition:
    """The only automatic release transition allowed by the control plane."""

    stage: str
    status: str
    traffic_percent: int
    rollback_version: str | None
    reasons: tuple[str, ...]


_STAGES: tuple[tuple[str, int], ...] = (
    ("SHADOW", 0),
    ("CANARY_5", 5),
    ("CANARY_25", 25),
    ("CANARY_50", 50),
    ("FULL", 100),
)


def evaluate_canary(metrics: CanaryMetrics) -> CanaryDecision:
    """Apply fixed thresholds; missing critical metrics stop evaluation, not release silently."""

    reasons: list[str] = []
    if metrics.quality_gate_pass is not True:
        reasons.append(
            "quality_gate_failed"
            if metrics.quality_gate_pass is False
            else "quality_gate_incomplete"
        )
    if metrics.safety_gate_pass is not True:
        reasons.append(
            "safety_gate_failed"
            if metrics.safety_gate_pass is False
            else "safety_gate_incomplete"
        )
    if metrics.p0_events > 0:
        reasons.append("p0_safety_event")
    if metrics.terminal_response_coverage is None or metrics.terminal_response_coverage < 1:
        reasons.append("terminal_response_coverage_below_100_percent")
    if _above(metrics.p95_e2e_ms, metrics.baseline_p95_e2e_ms, 1.15):
        reasons.append("p95_e2e_above_15_percent")
    if _above(metrics.p99_e2e_ms, metrics.baseline_p99_e2e_ms, 1.25):
        reasons.append("p99_e2e_above_25_percent")
    if _above(metrics.p95_cost_microusd, metrics.baseline_p95_cost_microusd, 1.10):
        reasons.append("p95_cost_above_10_percent")
    if (
        metrics.low_risk_handoff_rate is not None
        and metrics.baseline_low_risk_handoff_rate is not None
        and metrics.low_risk_handoff_rate > metrics.baseline_low_risk_handoff_rate * 1.20
    ):
        reasons.append("low_risk_handoff_rate_regression")
    if metrics.skill_scope_violation:
        reasons.append("skill_scope_violation")
    if metrics.target_slice_quality_delta is not None and metrics.target_slice_quality_delta < 0:
        reasons.append("skill_target_slice_quality_regression")
    return CanaryDecision(stop=bool(reasons), reasons=tuple(reasons))


def transition_stage(
    *, current_stage: str, current_version: str, metrics: CanaryMetrics
) -> StageTransition:
    """Promote one stage only when all available gates are green.

    A missing terminal coverage metric is already a stop condition.  The
    transition function additionally keeps an unknown/invalid stage paused and
    never jumps over an intermediate observation window.
    """

    decision = evaluate_canary(metrics)
    if decision.stop:
        return StageTransition(
            stage="STOPPED",
            status="STOPPED",
            traffic_percent=0,
            rollback_version=current_version,
            reasons=decision.reasons,
        )
    try:
        index = next(index for index, item in enumerate(_STAGES) if item[0] == current_stage)
    except StopIteration:
        return StageTransition(
            stage="STOPPED",
            status="STOPPED",
            traffic_percent=0,
            rollback_version=current_version,
            reasons=("unknown_release_stage",),
        )
    if current_stage == "FULL":
        return StageTransition(
            stage="FULL",
            status="COMPLETED",
            traffic_percent=100,
            rollback_version=None,
            reasons=(),
        )
    next_stage, traffic = _STAGES[index + 1]
    return StageTransition(
        stage=next_stage,
        status="ACTIVE",
        traffic_percent=traffic,
        rollback_version=None,
        reasons=(),
    )


def _above(value: float | None, baseline: float | None, multiplier: float) -> bool:
    return value is not None and baseline is not None and value > baseline * multiplier


__all__ = [
    "CanaryDecision",
    "CanaryMetrics",
    "StageTransition",
    "evaluate_canary",
    "transition_stage",
]

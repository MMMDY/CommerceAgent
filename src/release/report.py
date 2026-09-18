"""Safe Markdown projection for one progressive-release observation window."""

from __future__ import annotations

from datetime import UTC, datetime

from src.release.canary_guard import CanaryDecision, CanaryMetrics


def build_release_markdown(
    *,
    release_id: str,
    current_version: str,
    candidate_version: str,
    stage: str,
    decision: CanaryDecision,
    metrics: CanaryMetrics,
) -> str:
    """Render current/candidate deltas and automatic-stop evidence only."""

    stop = "STOPPED" if decision.stop else "GREEN / OBSERVE"
    lines = [
        "# Progressive Release Observation Report",
        "",
        f"- Generated: `{datetime.now(UTC).isoformat()}`",
        f"- Release: `{release_id}`",
        f"- Stage: `{stage}`",
        f"- Current: `{current_version}`",
        f"- Candidate: `{candidate_version}`",
        f"- Automatic stop: **{stop}**",
        f"- Stop reasons: `{', '.join(decision.reasons) if decision.reasons else 'none'}`",
        "",
        "## Current / Candidate delta",
        "",
        "| Dimension | Current | Candidate | Delta / status |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        (
            f"| Route | {_text(metrics.current_route)} | "
            f"{_text(metrics.candidate_route)} | "
            f"{_delta_text(metrics.current_route, metrics.candidate_route)} |",
            f"| Response policy | {_text(metrics.current_response_policy)} | "
            f"{_text(metrics.candidate_response_policy)} | "
            f"{_delta_text(metrics.current_response_policy, metrics.candidate_response_policy)} |",
            f"| Skill | {_text(metrics.current_skill)} | "
            f"{_text(metrics.candidate_skill)} | "
            f"{_delta_text(metrics.current_skill, metrics.candidate_skill)} |",
            f"| Quality delta | N/A | N/A | {_number(metrics.quality_delta)} |",
            f"| Safety pass-rate delta | N/A | N/A | {_number(metrics.safety_delta)} |",
            f"| P95 E2E | {_number(metrics.baseline_p95_e2e_ms, ' ms')} | "
            f"{_number(metrics.p95_e2e_ms, ' ms')} | "
            f"{_ratio(metrics.p95_e2e_ms, metrics.baseline_p95_e2e_ms)} |",
            f"| P95 cost | {_number(metrics.baseline_p95_cost_microusd, ' μUSD')} | "
            f"{_number(metrics.p95_cost_microusd, ' μUSD')} | "
            f"{_ratio(metrics.p95_cost_microusd, metrics.baseline_p95_cost_microusd)} |",
            f"| Terminal response coverage | N/A | "
            f"{_number(metrics.terminal_response_coverage)} | "
            f"{'pass' if metrics.terminal_response_coverage == 1 else 'incomplete/failed'} |",
        )
    )
    lines.extend(_gate_lines(metrics))
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This report contains redacted aggregate release facts only; it does not "
            "contain prompts, model reasoning, tool arguments, user text, or credentials.",
        ]
    )
    return "\n".join(lines) + "\n"


def _text(value: str | None) -> str:
    return value if value else "N/A"


def _number(value: float | None, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value:g}{suffix}"


def _delta_text(current: str | None, candidate: str | None) -> str:
    if current is None or candidate is None:
        return "N/A"
    return "unchanged" if current == candidate else "changed"


def _ratio(value: float | None, baseline: float | None) -> str:
    if value is None or baseline is None:
        return "N/A"
    if baseline == 0:
        return "N/A (baseline=0)"
    return f"{(value - baseline):g} ({(value / baseline - 1) * 100:+.2f}%)"


def _status(passed: bool) -> str:
    return "PASS" if passed else "STOP / INCOMPLETE"


def _gate_lines(metrics: CanaryMetrics) -> list[str]:
    handoff_status = _ratio_status(
        metrics.low_risk_handoff_rate,
        metrics.baseline_low_risk_handoff_rate,
        1.20,
    )
    quality_status = _status(
        metrics.target_slice_quality_delta is not None
        and metrics.target_slice_quality_delta >= 0
    )
    return [
        "",
        "## Gate details",
        "",
        "| Gate | Observed | Threshold / baseline | Status |",
        "|---|---:|---:|---|",
        "| Quality Gate | "
        f"{_gate_observed(metrics.quality_gate_pass)} | independent quality pass | "
        f"{_gate_status(metrics.quality_gate_pass)} |",
        "| Safety Gate | "
        f"{_gate_observed(metrics.safety_gate_pass)} | independent safety pass | "
        f"{_gate_status(metrics.safety_gate_pass)} |",
        "| P0 safety events | "
        f"{_number(float(metrics.p0_events))} | 0 | {_status(metrics.p0_events == 0)} |",
        "| Terminal response coverage | "
        f"{_number(metrics.terminal_response_coverage)} | 1.0 | "
        f"{_status(metrics.terminal_response_coverage == 1)} |",
        "| P95 E2E | "
        f"{_number(metrics.p95_e2e_ms, ' ms')} | "
        f"{_threshold(metrics.baseline_p95_e2e_ms, 1.15, ' ms')} | "
        f"{_ratio_status(metrics.p95_e2e_ms, metrics.baseline_p95_e2e_ms, 1.15)} |",
        "| P99 E2E | "
        f"{_number(metrics.p99_e2e_ms, ' ms')} | "
        f"{_threshold(metrics.baseline_p99_e2e_ms, 1.25, ' ms')} | "
        f"{_ratio_status(metrics.p99_e2e_ms, metrics.baseline_p99_e2e_ms, 1.25)} |",
        "| P95 cost | "
        f"{_number(metrics.p95_cost_microusd, ' μUSD')} | "
        f"{_threshold(metrics.baseline_p95_cost_microusd, 1.10, ' μUSD')} | "
        f"{_ratio_status(metrics.p95_cost_microusd, metrics.baseline_p95_cost_microusd, 1.10)} |",
        "| Low-risk handoff rate | "
        f"{_number(metrics.low_risk_handoff_rate)} | "
        f"{_threshold(metrics.baseline_low_risk_handoff_rate, 1.20)} | "
        f"{handoff_status} |",
        "| Skill scope | "
        f"{'violation' if metrics.skill_scope_violation else 'no violation'} | "
        f"no violation | {_status(not metrics.skill_scope_violation)} |",
        "| Target-slice quality delta | "
        f"{_number(metrics.target_slice_quality_delta)} | ≥ 0 | "
        f"{quality_status} |",
    ]


def _threshold(value: float | None, multiplier: float, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"≤ {value * multiplier:g}{suffix}"


def _ratio_status(value: float | None, baseline: float | None, multiplier: float) -> str:
    if value is None or baseline is None:
        return "INCOMPLETE"
    return "PASS" if value <= baseline * multiplier else "STOP"


def _gate_observed(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "true" if value else "false"


def _gate_status(value: bool | None) -> str:
    if value is None:
        return "INCOMPLETE"
    return "PASS" if value else "STOP"


__all__ = ["build_release_markdown"]

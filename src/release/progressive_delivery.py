"""Stable, safety-aware traffic assignment for Shadow and Canary releases.

This module is deliberately side-effect free.  It decides which version would
serve a request, but the caller remains responsible for fetching the release
record and persisting the assignment.  Stable bucketing binds tenant, actor,
and conversation identities so every Run in one conversation stays on the
same release bucket without exposing any of those identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from src.protocols import RequestRiskLevel, RiskHint

_CANARY_PERCENT: dict[str, int] = {
    "SHADOW": 0,
    "CANARY_5": 5,
    "CANARY_25": 25,
    "CANARY_50": 50,
    "FULL": 100,
}


@dataclass(frozen=True, slots=True)
class TrafficAssignment:
    current_version: str
    candidate_version: str
    selected_version: str
    mode: str
    bucket: int
    traffic_percent: int
    reason: str
    candidate_execution_allowed: bool


def build_release_comparison(
    *,
    current_route: str | None,
    candidate_route: str | None,
    current_response_policy: str | None,
    candidate_response_policy: str | None,
    current_skill: str | None = None,
    candidate_skill: str | None = None,
    estimated_cost_delta_microusd: float | None = None,
    candidate_runtime_available: bool = False,
    candidate_execution_allowed: bool = False,
) -> dict[str, object]:
    """Build a redacted, observation-only Current/Candidate comparison.

    The function deliberately accepts facts rather than a candidate runtime.
    Shadow records route/policy/Skill identities and an explicit unknown cost
    delta; the execution flag makes the boundary visible when the same DTO is
    later used for a low-risk Canary assignment.
    """

    return {
        "current_route": current_route,
        "candidate_route": candidate_route,
        "current_response_policy": current_response_policy,
        "candidate_response_policy": candidate_response_policy,
        "current_skill": current_skill,
        "candidate_skill": candidate_skill,
        "estimated_cost_delta_microusd": estimated_cost_delta_microusd,
        "candidate_runtime_available": candidate_runtime_available,
        "candidate_execution_allowed": candidate_execution_allowed,
        "observation_only": not candidate_execution_allowed,
    }


def stable_bucket(
    *, tenant_id: str, actor_id: str, run_id: str, conversation_id: str
) -> int:
    """Return a deterministic tenant/actor/conversation bucket in ``[0, 99]``.

    ``run_id`` remains in the signature for assignment/audit compatibility,
    but is intentionally excluded from the bucket material.  A new message
    in the same conversation must not jump between Current and Candidate.
    """

    del run_id
    material = "|".join((tenant_id, actor_id, conversation_id))
    return int.from_bytes(sha256(material.encode()).digest()[:8], "big") % 100


def assign_traffic(
    *,
    tenant_id: str,
    actor_id: str,
    run_id: str,
    conversation_id: str,
    current_version: str,
    candidate_version: str,
    stage: str,
    status: str,
    risk_level: RequestRiskLevel,
    risk_hint: RiskHint = RiskHint.READ_ONLY,
    candidate_runtime_available: bool = True,
    candidate_skill_approved: bool | None = None,
) -> TrafficAssignment:
    """Assign current/candidate versions while enforcing safety boundaries.

    Shadow never changes the user-visible version.  High/unknown risk and
    write-capable requests are pinned to the approved current version even if
    the release is in a canary stage.
    """

    bucket = stable_bucket(
        tenant_id=tenant_id,
        actor_id=actor_id,
        run_id=run_id,
        conversation_id=conversation_id,
    )
    percent = _CANARY_PERCENT.get(stage, 0)
    if status != "ACTIVE":
        return _current(
            current_version,
            candidate_version,
            bucket,
            percent,
            "release_not_active",
        )
    if stage == "SHADOW":
        return TrafficAssignment(
            current_version=current_version,
            candidate_version=candidate_version,
            selected_version=current_version,
            mode="shadow",
            bucket=bucket,
            traffic_percent=percent,
            reason="shadow_never_changes_user_visible_result",
            candidate_execution_allowed=False,
        )
    if not candidate_runtime_available:
        return _current(
            current_version,
            candidate_version,
            bucket,
            percent,
            "candidate_runtime_unavailable",
        )
    if candidate_skill_approved is False:
        return _current(
            current_version,
            candidate_version,
            bucket,
            percent,
            "candidate_skill_not_approved",
        )
    if risk_level is not RequestRiskLevel.LOW or risk_hint is RiskHint.WRITE:
        return _current(
            current_version,
            candidate_version,
            bucket,
            percent,
            "risk_boundary_pins_current_version",
        )
    if candidate_version and bucket < percent:
        return TrafficAssignment(
            current_version=current_version,
            candidate_version=candidate_version,
            selected_version=candidate_version,
            mode="canary",
            bucket=bucket,
            traffic_percent=percent,
            reason="stable_canary_bucket_selected",
            candidate_execution_allowed=True,
        )
    return _current(
        current_version,
        candidate_version,
        bucket,
        percent,
        "stable_canary_bucket_kept_current",
    )


def _current(
    current_version: str,
    candidate_version: str,
    bucket: int,
    percent: int,
    reason: str,
) -> TrafficAssignment:
    return TrafficAssignment(
        current_version=current_version,
        candidate_version=candidate_version,
        selected_version=current_version,
        mode="current",
        bucket=bucket,
        traffic_percent=percent,
        reason=reason,
        candidate_execution_allowed=False,
    )


__all__ = [
    "TrafficAssignment",
    "assign_traffic",
    "build_release_comparison",
    "stable_bucket",
]

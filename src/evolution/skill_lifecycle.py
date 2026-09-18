"""Pure lifecycle policy for experience Skills.

Keeping this policy separate makes it usable by batch evaluators and API
handlers, and makes the key safety invariant easy to test: automation may
prepare evidence, but it cannot cross the human-review boundary.
"""

# ruff: noqa: E501

from __future__ import annotations

from src.evolution.contracts import SkillStatus

_TRANSITIONS: dict[SkillStatus, frozenset[SkillStatus]] = {
    SkillStatus.CANDIDATE: frozenset({SkillStatus.PENDING_REVIEW, SkillStatus.EXPIRED}),
    SkillStatus.PENDING_REVIEW: frozenset({SkillStatus.APPROVED, SkillStatus.REJECTED, SkillStatus.EXPIRED}),
    SkillStatus.APPROVED: frozenset({SkillStatus.CANARY, SkillStatus.ROLLED_BACK, SkillStatus.EXPIRED}),
    SkillStatus.CANARY: frozenset({SkillStatus.ACTIVE, SkillStatus.ROLLED_BACK, SkillStatus.EXPIRED}),
    SkillStatus.ACTIVE: frozenset({SkillStatus.ROLLED_BACK, SkillStatus.EXPIRED}),
    SkillStatus.REJECTED: frozenset(), SkillStatus.EXPIRED: frozenset(), SkillStatus.ROLLED_BACK: frozenset(),
}


def can_transition(current: SkillStatus, target: SkillStatus, *, reviewer: str | None = None) -> bool:
    if target in {SkillStatus.APPROVED, SkillStatus.REJECTED} and not reviewer:
        return False
    return target in _TRANSITIONS[current]


def automation_may_activate(status: SkillStatus) -> bool:
    """False for every automated path; activation requires a human decision."""

    return False if status in {SkillStatus.CANDIDATE, SkillStatus.PENDING_REVIEW} else status in {SkillStatus.APPROVED, SkillStatus.CANARY}


__all__ = ["automation_may_activate", "can_transition"]

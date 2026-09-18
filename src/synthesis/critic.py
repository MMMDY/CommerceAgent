"""Independent, deterministic quality critic for synthetic evaluation cases.

The critic is deliberately separate from :mod:`generator`: it checks whether
the generated label and risk metadata agree with the text and whether the
prompt is usable as an evaluation case.  It never changes a candidate or
marks a high-risk case as human approved.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from src.synthesis.contracts import SyntheticCaseCandidate

CRITIC_VERSION = "synthetic-critic-v1"
CRITIC_CONFIG_HASH = "sha256:" + hashlib.sha256(CRITIC_VERSION.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CriticIssue:
    case_id: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class CriticReport:
    critic_version: str
    critic_config_hash: str
    checked_count: int
    issues: tuple[CriticIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def review_candidates(candidates: Iterable[SyntheticCaseCandidate]) -> CriticReport:
    """Check label/risk consistency and basic prompt naturalness."""

    issues: list[CriticIssue] = []
    items = tuple(candidates)
    for candidate in items:
        text = " ".join(message.content.strip() for message in candidate.messages).strip()
        if not 4 <= len(text) <= 240:
            issues.append(
                CriticIssue(candidate.id, "unnatural_length", "prompt length is out of bounds")
            )
        if any(marker in text for marker in ("<|", "{{", "}}", "[MASK]", "TODO")):
            issues.append(
                CriticIssue(
                    candidate.id,
                    "unnatural_placeholder",
                    "prompt contains a template placeholder",
                )
            )
        if candidate.task_type == "safety_response_v2":
            if candidate.risk_level != "high":
                issues.append(
                    CriticIssue(
                        candidate.id, "risk_label_mismatch", "safety track must be high risk"
                    )
                )
            if not candidate.forbidden_tools:
                issues.append(
                    CriticIssue(
                        candidate.id,
                        "missing_safety_boundary",
                        "safety case has no forbidden tool boundary",
                    )
                )
        elif candidate.task_type == "long_tail_response_v1":
            if candidate.risk_level != "low":
                issues.append(
                    CriticIssue(
                        candidate.id, "risk_label_mismatch", "long-tail track must be low risk"
                    )
                )
            if candidate.expected.get("outcome") != "bounded_response":
                issues.append(
                    CriticIssue(
                        candidate.id,
                        "label_mismatch",
                        "long-tail label is not bounded_response",
                    )
                )
    return CriticReport(CRITIC_VERSION, CRITIC_CONFIG_HASH, len(items), tuple(issues))


__all__ = [
    "CRITIC_CONFIG_HASH",
    "CRITIC_VERSION",
    "CriticIssue",
    "CriticReport",
    "review_candidates",
]

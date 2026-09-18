"""Independent, conservative confidence calibration for routing dimensions.

The classifier's overall score is not a safe proxy for both domain and risk.
This module keeps the two dimensions separate, applies an explicit versioned
policy profile, and gives unknown dimensions zero usable confidence.  A future
offline reliability fit can replace the profiles without changing the router
contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.protocols import IntentClassification, RequestDomain, RequestRiskLevel

CALIBRATION_VERSION = "risk-domain-conservative-v1"


@dataclass(frozen=True, slots=True)
class CalibratedConfidence:
    overall: float
    domain: float
    risk: float
    version: str = CALIBRATION_VERSION


def _conservative_curve(raw: float, *, dimension: str) -> float:
    """Map provider confidence to a bounded conservative policy score.

    The curves are intentionally monotonic and shrink high scores.  They are
    policy calibration defaults, not a claim of live-model accuracy; the
    version is surfaced in events so a fitted profile can be audited later.
    """

    points = (
        ((0.0, 0.0), (0.5, 0.40), (0.7, 0.60), (0.8, 0.72), (0.9, 0.84), (0.95, 0.91), (1.0, 0.97))
        if dimension == "domain"
        else (
            (0.0, 0.0),
            (0.5, 0.35),
            (0.7, 0.58),
            (0.8, 0.70),
            (0.9, 0.84),
            (0.95, 0.92),
            (1.0, 0.98),
        )
    )
    value = min(1.0, max(0.0, raw))
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:], strict=True):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return round(left_y + fraction * (right_y - left_y), 6)
    return points[-1][1]


def calibrate_classification(candidate: IntentClassification) -> CalibratedConfidence:
    """Return separate usable confidence for domain and content risk."""

    domain_raw = candidate.domain_confidence
    risk_raw = candidate.risk_confidence
    if domain_raw is None:
        domain_raw = candidate.confidence
    if risk_raw is None:
        risk_raw = candidate.confidence

    domain = (
        0.0
        if candidate.domain is RequestDomain.UNKNOWN
        else _conservative_curve(domain_raw, dimension="domain")
    )
    risk = (
        0.0
        if candidate.request_risk_level is RequestRiskLevel.UNKNOWN
        else _conservative_curve(risk_raw, dimension="risk")
    )
    return CalibratedConfidence(overall=candidate.confidence, domain=domain, risk=risk)


__all__ = ["CALIBRATION_VERSION", "CalibratedConfidence", "calibrate_classification"]

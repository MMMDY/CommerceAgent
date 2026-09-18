from src.orchestration.confidence import CALIBRATION_VERSION, calibrate_classification
from src.orchestration.route_catalog import intent_route_rules
from src.orchestration.router import IntentRouter, RouteOutcome
from src.protocols import (
    IntentClassification,
    RequestDomain,
    RequestRiskLevel,
    RiskHint,
)


def _candidate(**updates: object) -> IntentClassification:
    values: dict[str, object] = {
        "intent": "social_chat",
        "risk_hint": RiskHint.READ_ONLY,
        "route_hint": "untrusted",
        "confidence": 0.95,
        "domain": RequestDomain.SOCIAL,
        "request_risk_level": RequestRiskLevel.LOW,
    }
    values.update(updates)
    return IntentClassification(**values)


def test_domain_and_risk_are_calibrated_independently() -> None:
    scores = calibrate_classification(
        _candidate(domain_confidence=0.95, risk_confidence=0.70)
    )

    assert scores.version == CALIBRATION_VERSION
    assert scores.domain > scores.risk
    assert scores.overall == 0.95
    assert scores.domain < 0.95
    assert scores.risk < 0.70


def test_unknown_dimensions_have_no_usable_confidence() -> None:
    scores = calibrate_classification(
        _candidate(domain=RequestDomain.UNKNOWN, request_risk_level=RequestRiskLevel.UNKNOWN)
    )

    assert scores.domain == 0
    assert scores.risk == 0


def test_conversational_route_checks_domain_and_risk_thresholds_separately() -> None:
    rules = intent_route_rules(routing_v2=True, conversational_fallback=True)
    router = IntentRouter(rules)

    low_domain = router.decide(_candidate(domain_confidence=0.70, risk_confidence=0.99))
    low_risk = router.decide(_candidate(domain_confidence=0.99, risk_confidence=0.70))

    assert low_domain.outcome is RouteOutcome.ASK_USER
    assert low_domain.reason_code == "LOW_DOMAIN_CONFIDENCE"
    assert low_risk.outcome is RouteOutcome.HANDOFF
    assert low_risk.reason_code == "LOW_RISK_CONFIDENCE"

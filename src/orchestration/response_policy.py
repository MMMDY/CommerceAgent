"""Code-owned response policy checks shared by routing and execution."""

from __future__ import annotations

from src.protocols import RequestDomain, RequestRiskLevel, ResponsePolicy


def policy_is_conversational(policy: ResponsePolicy) -> bool:
    return policy in {
        ResponsePolicy.CONVERSATIONAL_RESPONSE,
        ResponsePolicy.GRACEFUL_UNSUPPORTED,
    }


def conversational_route_allowed(
    *,
    policy: ResponsePolicy,
    domain: RequestDomain,
    risk_level: RequestRiskLevel,
) -> bool:
    """Require both low content risk and a matching non-commerce domain."""

    if not policy_is_conversational(policy):
        return True
    return risk_level is RequestRiskLevel.LOW and domain in {
        RequestDomain.SOCIAL,
        RequestDomain.CAPABILITY,
        RequestDomain.UNSUPPORTED,
    }


__all__ = ["conversational_route_allowed", "policy_is_conversational"]

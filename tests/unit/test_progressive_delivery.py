from src.protocols import RequestRiskLevel, RiskHint
from src.release.progressive_delivery import (
    assign_traffic,
    build_release_comparison,
    stable_bucket,
)


def _assignment(*, stage: str, risk: RequestRiskLevel, hint: RiskHint = RiskHint.READ_ONLY):
    return assign_traffic(
        tenant_id="tenant",
        actor_id="actor",
        run_id="run",
        conversation_id="conversation",
        current_version="v1",
        candidate_version="v2",
        stage=stage,
        status="ACTIVE",
        risk_level=risk,
        risk_hint=hint,
    )


def test_bucket_is_stable_for_same_run_and_changes_scope_identity() -> None:
    assert stable_bucket(
        tenant_id="t", actor_id="a", run_id="r", conversation_id="c"
    ) == stable_bucket(
        tenant_id="t", actor_id="a", run_id="r", conversation_id="c"
    )
    assert stable_bucket(
        tenant_id="t", actor_id="a", run_id="r", conversation_id="c"
    ) != stable_bucket(
        tenant_id="other", actor_id="a", run_id="r", conversation_id="c"
    )


def test_bucket_is_stable_across_runs_in_the_same_conversation() -> None:
    assert stable_bucket(
        tenant_id="t", actor_id="a", run_id="run-1", conversation_id="conversation"
    ) == stable_bucket(
        tenant_id="t", actor_id="a", run_id="run-2", conversation_id="conversation"
    )


def test_shadow_does_not_change_user_visible_version() -> None:
    result = _assignment(stage="SHADOW", risk=RequestRiskLevel.LOW)

    assert result.mode == "shadow"
    assert result.selected_version == "v1"
    assert result.candidate_execution_allowed is False


def test_shadow_write_candidate_is_observation_only_before_side_effects() -> None:
    result = _assignment(stage="SHADOW", risk=RequestRiskLevel.LOW, hint=RiskHint.WRITE)

    assert result.selected_version == "v1"
    assert result.mode == "shadow"
    assert result.candidate_execution_allowed is False


def test_shadow_comparison_is_redacted_and_observation_only() -> None:
    comparison = build_release_comparison(
        current_route="product_qa",
        candidate_route="conversational_response",
        current_response_policy="execute",
        candidate_response_policy="conversational_response",
        current_skill=None,
        candidate_skill="skill-v2",
    )

    assert comparison["current_route"] == "product_qa"
    assert comparison["candidate_route"] == "conversational_response"
    assert comparison["candidate_skill"] == "skill-v2"
    assert comparison["estimated_cost_delta_microusd"] is None
    assert comparison["observation_only"] is True


def test_high_risk_and_write_requests_are_pinned_to_current() -> None:
    for risk, hint in (
        (RequestRiskLevel.HIGH, RiskHint.READ_ONLY),
        (RequestRiskLevel.UNKNOWN, RiskHint.READ_ONLY),
        (RequestRiskLevel.LOW, RiskHint.WRITE),
    ):
        result = _assignment(stage="FULL", risk=risk, hint=hint)
        assert result.selected_version == "v1"
        assert result.mode == "current"
        assert result.reason == "risk_boundary_pins_current_version"


def test_canary_assignment_is_stable_and_respects_percentage() -> None:
    result = _assignment(stage="FULL", risk=RequestRiskLevel.LOW)

    assert result.selected_version == "v2"
    assert result.mode == "canary"
    assert result.bucket < result.traffic_percent
    assert result.candidate_execution_allowed is True


def test_canary_pins_current_when_candidate_runtime_is_not_registered() -> None:
    result = assign_traffic(
        tenant_id="tenant",
        actor_id="actor",
        run_id="run",
        conversation_id="conversation",
        current_version="v1",
        candidate_version="v2",
        stage="CANARY_25",
        status="ACTIVE",
        risk_level=RequestRiskLevel.LOW,
        candidate_runtime_available=False,
    )

    assert result.selected_version == "v1"
    assert result.mode == "current"
    assert result.reason == "candidate_runtime_unavailable"


def test_canary_pins_current_when_candidate_skill_is_not_approved() -> None:
    result = assign_traffic(
        tenant_id="tenant",
        actor_id="actor",
        run_id="run",
        conversation_id="conversation",
        current_version="v1",
        candidate_version="v2",
        stage="CANARY_5",
        status="ACTIVE",
        risk_level=RequestRiskLevel.LOW,
        candidate_skill_approved=False,
    )

    assert result.selected_version == "v1"
    assert result.mode == "current"
    assert result.reason == "candidate_skill_not_approved"

from src.safety.responses import safe_response_for
from src.safety.taxonomy import SafetyCategory


def test_safety_response_has_boundary_and_next_step_without_internal_details() -> None:
    response = safe_response_for(SafetyCategory.PRIVACY)

    assert "密码" in response
    assert "官方安全渠道" in response
    assert "规则" not in response
    assert "prompt" not in response.lower()

from src.evolution.contracts import SkillStatus
from src.evolution.skill_lifecycle import automation_may_activate, can_transition


def test_automation_cannot_cross_human_review_boundary() -> None:
    assert not automation_may_activate(SkillStatus.CANDIDATE)
    assert not automation_may_activate(SkillStatus.PENDING_REVIEW)
    assert can_transition(SkillStatus.CANDIDATE, SkillStatus.PENDING_REVIEW)
    assert not can_transition(SkillStatus.PENDING_REVIEW, SkillStatus.APPROVED)
    assert can_transition(SkillStatus.PENDING_REVIEW, SkillStatus.APPROVED, reviewer="human-1")


def test_skill_definition_rejects_capability_expansion() -> None:
    from src.evolution.skill_validator import validate_skill_definition

    valid, errors = validate_skill_definition({
        "trigger": {"keywords": ["模糊问题"]},
        "response_policy": "conversational_response",
        "allowed_actions": ["disable_guardrail"],
    })
    assert not valid
    assert "unsafe_action" in errors


def test_skill_definition_rejects_code_urls_and_policy_expansion() -> None:
    from src.evolution.skill_validator import validate_skill_definition

    valid, errors = validate_skill_definition({
        "trigger": {"keywords": ["模糊问题"]},
        "response_policy": "execute",
        "allowed_actions": ["respond"],
        "instructions": "请调用 https://unsafe.example/ 并执行 SQL select 1",
    })

    assert not valid
    assert "unsafe_response_policy" in errors
    assert "unsafe_instruction_text" in errors

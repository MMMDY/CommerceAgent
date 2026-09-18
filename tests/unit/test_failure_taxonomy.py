import pytest

from src.evolution.attribution_rules import deterministic_category
from src.evolution.contracts import AttributionCategory

POSITIVE_CASES = {
    AttributionCategory.INTENT_ERROR: ("LOW_CLASSIFICATION_CONFIDENCE", ()),
    AttributionCategory.POLICY_ERROR: ("CONFIRMATION_EXPIRED", ()),
    AttributionCategory.TOOL_ERROR: ("TOOL_TIMEOUT", ()),
    AttributionCategory.RETRIEVAL_ERROR: ("RETRIEVAL_EMPTY", ()),
    AttributionCategory.SAFETY_ERROR: ("PROMPT_INJECTION_BLOCKED", ()),
    AttributionCategory.MODEL_ERROR: ("MODEL_TIMEOUT", ()),
    AttributionCategory.RESPONSE_ERROR: ("RESPONSE_PUBLISH_FAILED", ()),
    AttributionCategory.UNKNOWN: ("UNCLASSIFIED_RUNTIME_SIGNAL", ()),
}


@pytest.mark.parametrize("category,case", tuple(POSITIVE_CASES.items()))
def test_every_taxonomy_category_has_a_positive_case(
    category: AttributionCategory, case: tuple[str, tuple[str, ...]]
) -> None:
    reason, events = case
    assert deterministic_category(reason_code=reason, event_types=events) is category


@pytest.mark.parametrize("category,case", tuple(POSITIVE_CASES.items()))
def test_every_taxonomy_category_has_a_negative_case(
    category: AttributionCategory, case: tuple[str, tuple[str, ...]]
) -> None:
    reason, events = case
    negative_reason = "UNRELATED_CONTROL_SIGNAL"
    if category is AttributionCategory.UNKNOWN:
        negative_reason = "MODEL_TIMEOUT"
    assert deterministic_category(reason_code=negative_reason, event_types=events) is not category

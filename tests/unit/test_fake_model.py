from __future__ import annotations

import pytest

from src.models.gateway import DeterministicFakeModel, ModelGatewayError
from src.protocols import Decision, DecisionType, PromptView


def _prompt() -> PromptView:
    return PromptView(
        system_policy_version="p1",
        workflow_id="readonly",
        workflow_version="1",
        current_step="start",
        allowed_decisions=("respond",),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=1,
    )


def test_fake_model_returns_decisions_in_exact_order() -> None:
    decisions = [
        Decision(type=DecisionType.RESPOND, intent="x", route="r", confidence=1, response="one"),
        Decision(type=DecisionType.FINISH, intent="x", route="r", confidence=1, response="two"),
    ]
    model = DeterministicFakeModel(decisions)
    assert model.decide(_prompt()).decision.response == "one"
    assert model.decide(_prompt()).decision.response == "two"
    with pytest.raises(ModelGatewayError):
        model.decide(_prompt())

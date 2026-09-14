"""Opt-in smoke test for the configured model endpoint."""

from __future__ import annotations

import os

import pytest

from src.config import get_settings
from src.models.gateway import OpenAICompatibleGateway
from src.protocols import DecisionType, PromptView


@pytest.mark.live
def test_live_gateway_returns_a_structured_decision() -> None:
    if os.environ.get("RUN_LIVE_MODEL_TEST") != "1":
        pytest.skip("set RUN_LIVE_MODEL_TEST=1 to call the configured model")
    prompt = PromptView(
        system_policy_version="smoke",
        workflow_id="smoke",
        workflow_version="1",
        current_step="respond",
        allowed_decisions=("respond",),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=1,
    )
    result = OpenAICompatibleGateway(get_settings()).decide(prompt)
    assert result.latency_ms >= 0
    assert isinstance(result.decision.type, DecisionType)

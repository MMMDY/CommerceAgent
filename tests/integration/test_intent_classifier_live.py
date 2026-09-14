"""Opt-in live smoke for the constrained intent-classification profile."""

from __future__ import annotations

import os

import pytest

from src.config import get_settings
from src.models.gateway import OpenAICompatibleGateway
from src.protocols import IntentClassification, Message, RoutingPromptView


@pytest.mark.live
def test_live_classifier_returns_a_candidate_without_executor_selection() -> None:
    if os.environ.get("RUN_LIVE_MODEL_TEST") != "1":
        pytest.skip("set RUN_LIVE_MODEL_TEST=1 to call the configured model")
    settings = get_settings()
    gateway = OpenAICompatibleGateway(settings)
    result = gateway.classify(
        RoutingPromptView(
            conversation=(Message(role="user", content="查询我的订单物流"),),
            allowed_intents=("order_status", "refund_request"),
        )
    )
    assert isinstance(result, IntentClassification)
    assert result.intent
    assert gateway.classifier_config_hash.startswith("sha256:")

from __future__ import annotations

import json

import httpx
import pytest

from src.harness.multiturn_schema import AgendaItem, ScenarioSpec
from src.harness.user_simulator import (
    OpenAICompatibleUserSimulatorProvider,
    RuleUserSimulator,
    SimulatorError,
    UserSimulator,
    UserSimulatorConfig,
    parse_user_action,
    validate_user_action,
)


def _scenario() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="order_demo_v1",
        domain="order_delivery",
        intent_agenda=(AgendaItem(intent="查询物流状态"),),
        behavior_facts={"订单号": "ORD-DEMO-001"},
        reference_solution={"gold_response": "隐藏标准答案"},
    )


def test_user_action_json_is_structured_and_bounded() -> None:
    action = parse_user_action(
        '{"action":"ask_followup","message":"请继续说明","target_intents":["查询物流状态"],"reason_code":"pending"}'
    )
    validate_user_action(action, scenario=_scenario())
    assert action.action == "ask_followup"


def test_user_simulator_rejects_hidden_gold_leak_and_unknown_fact() -> None:
    with pytest.raises(SimulatorError, match="leaks_hidden_solution"):
        validate_user_action(
            parse_user_action(
                {"action": "ask_followup", "message": "隐藏标准答案", "reason_code": "x"}
            ),
            scenario=_scenario(),
        )
    with pytest.raises(SimulatorError, match="outside_behavior_facts"):
        validate_user_action(
            parse_user_action(
                {
                    "action": "provide_fact",
                    "message": "补充信息",
                    "revealed_facts": ["账户余额"],
                    "reason_code": "x",
                }
            ),
            scenario=_scenario(),
        )


def test_rule_simulator_only_repeats_allowed_agenda_intent() -> None:
    action = UserSimulator(RuleUserSimulator()).next_action(
        scenario=_scenario(), history=(), pending_intents=("查询物流状态",)
    )
    assert action.target_intents == ("查询物流状态",)
    assert action.action == "initial_request"


def test_rule_simulator_releases_behavior_fact_without_profile() -> None:
    scenario = _scenario()
    simulator = UserSimulator(RuleUserSimulator())
    initial = simulator.next_action(
        scenario=scenario,
        history=(),
        pending_intents=("查询物流状态",),
    )

    follow_up = simulator.next_action(
        scenario=scenario,
        history=(initial,),
        agent_response="为了查询物流，请先提供订单号。",
        pending_intents=("查询物流状态",),
    )

    assert follow_up.action == "provide_fact"
    assert follow_up.revealed_facts == ("订单号",)
    assert "ORD-DEMO-001" in follow_up.message


def test_simulator_config_is_recordable_and_resist_is_a_valid_action() -> None:
    simulator = UserSimulator(RuleUserSimulator(), UserSimulatorConfig(model="simulator-test"))
    assert simulator.config.metadata()["model"] == "simulator-test"
    action = parse_user_action(
        {"action": "resist", "message": "我不提供不必要的信息", "reason_code": "unnecessary_fact"}
    )
    validate_user_action(action, scenario=_scenario())


def test_openai_simulator_provider_sends_only_public_context() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                                "content": (
                                    '{"action":"ask_followup","message":"请继续说明物流",'
                                    '"target_intents":["查询物流状态"],"reason_code":"pending"}'
                                )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleUserSimulatorProvider(
        base_url="https://simulator.test/v1",
        api_key="simulator-secret",
        model="simulator-model",
        client=client,
    )
    action = UserSimulator(provider, provider.config).next_action(
        scenario=_scenario(), history=(), pending_intents=("查询物流状态",)
    )

    assert action.action == "ask_followup"
    content = str(seen["messages"])
    assert "reference_solution" not in content
    assert "隐藏标准答案" not in content
    assert "ORD-DEMO-001" in content
    assert provider.config.metadata()["provider"] == "openai_compatible"


def test_openai_simulator_provider_fails_closed_on_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    provider = OpenAICompatibleUserSimulatorProvider(
        base_url="https://simulator.test/v1",
        api_key="simulator-secret",
        model="simulator-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SimulatorError, match="simulator_provider_unavailable"):
        provider(
            scenario=_scenario(),
            history=(),
            agent_response="",
            pending_intents=("查询物流状态",),
        )

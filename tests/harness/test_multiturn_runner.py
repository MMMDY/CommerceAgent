from __future__ import annotations

from src.harness.multiturn_runner import MultiTurnRunner
from src.harness.multiturn_schema import AgendaItem, ScenarioSpec
from src.harness.schema import EvalMessage, NormalizedTrace


def test_multiturn_runner_separates_covered_intent_from_agent_answer() -> None:
    scenario = ScenarioSpec(
        scenario_id="pilot_order_v1",
        domain="order_delivery",
        intent_agenda=(AgendaItem(intent="查询物流状态"),),
    )

    def agent(case, _turn_id):
        return NormalizedTrace(
            case_id=case.case_id,
            intent="查询物流状态",
            next_action="respond",
            response="已说明物流状态。",
            status="complete",
        )

    report = MultiTurnRunner(agent=agent).run(scenario)
    assert report.status == "completed"
    assert report.intent_coverage == 1.0
    assert report.task_success is True
    assert report.turns[0].agent_trace.response == "已说明物流状态。"


def test_multiturn_runner_does_not_duplicate_user_messages() -> None:
    scenario = ScenarioSpec(
        scenario_id="pilot_message_v1",
        domain="order_delivery",
        intent_agenda=(AgendaItem(intent="查询物流状态"),),
    )
    seen: list[tuple[str, ...]] = []

    def agent(case, _turn_id):
        seen.append(tuple(message.content for message in case.messages if message.role == "user"))
        return NormalizedTrace(
            case_id=case.case_id,
            intent="查询物流状态",
            next_action="respond",
            response="已说明物流状态。",
            status="complete",
        )

    MultiTurnRunner(agent=agent).run(scenario)
    assert seen == [("我想咨询一个问题。",)]


def test_multiturn_runner_preserves_public_initial_messages() -> None:
    scenario = ScenarioSpec(
        scenario_id="pilot_initial_context_v1",
        domain="product_recommendation",
        intent_agenda=(AgendaItem(intent="商品推荐"),),
        initial_messages=(EvalMessage(role="user", content="候选卡片上下文"),),
    )
    seen: list[tuple[str, ...]] = []

    def agent(case, _turn_id):
        seen.append(tuple(message.content for message in case.messages))
        return NormalizedTrace(
            case_id=case.case_id,
            intent="商品推荐",
            next_action="respond",
            response="已根据候选卡片说明。",
            status="complete",
        )

    report = MultiTurnRunner(agent=agent).run(scenario)
    assert report.task_success is True
    assert seen == [("候选卡片上下文",)]


def test_multiturn_runner_fails_closed_on_agent_turn_failure() -> None:
    scenario = ScenarioSpec(
        scenario_id="pilot_agent_failure_v1",
        domain="product_recommendation",
        intent_agenda=(AgendaItem(intent="商品推荐"),),
    )

    def agent(case, _turn_id):
        return NormalizedTrace(
            case_id=case.case_id,
            next_action="agent_configuration_unavailable",
            response="",
            status="fail",
        )

    report = MultiTurnRunner(agent=agent).run(scenario)
    assert report.status == "incomplete"
    assert report.termination_reason == "agent_configuration_unavailable"
    assert report.task_success is None


def test_multiturn_runner_preserves_timeout_failure_reason() -> None:
    scenario = ScenarioSpec(
        scenario_id="pilot_timeout_failure_v1",
        domain="product_recommendation",
        intent_agenda=(AgendaItem(intent="商品推荐"),),
    )

    def agent(_case, _turn_id):
        raise TimeoutError("provider timeout must not cross the report boundary")

    report = MultiTurnRunner(agent=agent).run(scenario)
    assert report.status == "incomplete"
    assert report.termination_reason == "agent_turn_timeout"
    assert report.turns[0].agent_trace.next_action == "agent_turn_timeout"
    assert report.turns[0].agent_trace.termination_reason == "agent_turn_timeout"

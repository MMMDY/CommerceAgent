"""Bounded orchestration of a constrained user simulator and an agent runtime."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from src.harness.multiturn_schema import MultiTurnReport, ScenarioSpec, TurnTrace, UserAction
from src.harness.multiturn_verifier import MultiTurnVerifier
from src.harness.schema import EvalMessage, NormalizedTrace, RuntimeCaseInput
from src.harness.user_simulator import RuleUserSimulator, SimulatorError, UserSimulator

AgentTurn = Callable[[RuntimeCaseInput, int], NormalizedTrace]


@dataclass(frozen=True, slots=True)
class MultiTurnConfig:
    max_turns: int = 8
    max_repeated_action: int = 2
    max_agent_steps_per_turn: int = 4
    simulation_timeout_seconds: float = 60.0
    scenario_timeout_seconds: float = 300.0
    allow_mutation: bool = False

    def __post_init__(self) -> None:
        if self.max_turns < 1 or self.max_turns > 32:
            raise ValueError("max_turns must be between 1 and 32")
        if self.max_repeated_action < 1:
            raise ValueError("max_repeated_action must be positive")
        if self.allow_mutation:
            raise ValueError("multi-turn evaluation cannot enable mutation")


class MultiTurnRunner:
    def __init__(
        self,
        *,
        agent: AgentTurn,
        simulator: UserSimulator | None = None,
        verifier: MultiTurnVerifier | None = None,
        config: MultiTurnConfig | None = None,
    ) -> None:
        self._agent = agent
        self._simulator = simulator or UserSimulator(RuleUserSimulator())
        self._verifier = verifier or MultiTurnVerifier()
        self._config = config or MultiTurnConfig()

    def run(
        self,
        scenario: ScenarioSpec,
        *,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> MultiTurnReport:
        started = datetime.now(UTC)
        dialogue_id = str(uuid5(NAMESPACE_URL, f"commerce-agent:dialogue:{scenario.scenario_id}"))
        actions: list[UserAction] = []
        turns: list[TurnTrace] = []
        messages: list[EvalMessage] = list(scenario.initial_messages)
        state = __import__(
            "src.harness.intent_state", fromlist=["IntentStateMachine"]
        ).IntentStateMachine(
            scenario.key_intents
            + tuple(item.intent for item in scenario.intent_agenda if item.priority == "minor")
        )
        termination = "scenario_completed"
        status = "completed"

        max_turns = min(self._config.max_turns, scenario.termination.max_turns)
        for turn_id in range(1, max_turns + 1):
            if cancelled():
                termination, status = "cancelled", "incomplete"
                break
            elapsed = (datetime.now(UTC) - started).total_seconds()
            if elapsed >= self._config.scenario_timeout_seconds:
                termination, status = "scenario_timeout", "incomplete"
                break
            pending = tuple(
                intent
                for intent in scenario.key_intents
                if not state.all_addressed((intent,))
            )
            try:
                action = self._simulator.next_action(
                    scenario=scenario,
                    history=tuple(actions),
                    agent_response=turns[-1].agent_trace.response if turns else "",
                    pending_intents=pending,
                )
            except SimulatorError as error:
                termination, status = str(error), "incomplete"
                break
            actions.append(action)
            if _repeat_count(actions, action) >= self._config.max_repeated_action:
                termination, status = "simulator_no_progress", "incomplete"
                break
            history_start = len(state.history)
            try:
                state.raise_intents(
                    action.target_intents,
                    turn_id=turn_id,
                    evidence=(f"user:turn_{turn_id}",),
                )
            except Exception:
                termination, status = "simulator_intent_contract_error", "incomplete"
                break
            if not (
                messages
                and messages[-1].role == "user"
                and messages[-1].content == action.message
            ):
                messages.append(EvalMessage(role="user", content=action.message))
            trace = self._invoke_agent(
                scenario=scenario,
                messages=tuple(messages),
                turn_id=turn_id,
                cancelled=cancelled,
            )
            addressed = self._verifier.addressed_intents(action=action, trace=trace)
            try:
                state.address_intents(
                    addressed,
                    turn_id=turn_id,
                    evidence=_trace_evidence(trace, turn_id),
                )
            except Exception:
                termination, status = "agent_intent_contract_error", "incomplete"
                break
            transitions = tuple(state.history[history_start:])
            turn = TurnTrace(
                scenario_id=scenario.scenario_id,
                dialogue_id=dialogue_id,
                turn_id=turn_id,
                user_action=action,
                agent_trace=trace,
                raised_intents=tuple(action.target_intents),
                addressed_intents=addressed,
                intent_states=state.states,
                transitions=transitions,
                verifier_pass=bool(addressed) or not action.target_intents,
                version_hash=_version_hash(scenario),
            )
            turns.append(turn)
            if trace.status == "fail":
                termination = trace.next_action or "agent_turn_failed"
                status = "incomplete"
                break
            if trace.response.strip():
                messages.append(EvalMessage(role="assistant", content=trace.response))
            if action.action == "abandon":
                termination, status = "user_abandoned", "abandoned"
                break
            if state.all_addressed(scenario.key_intents):
                termination, status = "all_key_intents_addressed", "completed"
                break
        else:
            termination, status = "max_turns_reached", "incomplete"

        report = self._verifier.verify(
            scenario=scenario,
            dialogue_id=dialogue_id,
            turns=tuple(turns),
            termination_reason=termination,
            status=status,
        )
        simulator_config = getattr(self._simulator, "config", None)
        if simulator_config is not None and hasattr(simulator_config, "metadata"):
            report = report.model_copy(
                update={"metadata": {**report.metadata, "simulator": simulator_config.metadata()}}
            )
        return report

    def _invoke_agent(
        self,
        *,
        scenario: ScenarioSpec,
        messages: tuple[EvalMessage, ...],
        turn_id: int,
        cancelled: Callable[[], bool],
    ) -> NormalizedTrace:
        if cancelled():
            return _failed_trace(scenario.scenario_id, "cancelled")
        case = RuntimeCaseInput(case_id=scenario.scenario_id, locale="zh-CN", messages=messages)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="multiturn-agent")
        future = executor.submit(self._agent, case, turn_id)
        try:
            trace = future.result(timeout=self._config.simulation_timeout_seconds)
            if trace.case_id != scenario.scenario_id:
                return trace.model_copy(update={"case_id": scenario.scenario_id})
            return trace
        except FutureTimeout:
            future.cancel()
            return _failed_trace(scenario.scenario_id, "agent_turn_timeout")
        except Exception:
            return _failed_trace(scenario.scenario_id, "agent_turn_failed")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def run_scenarios(
    scenarios: Iterable[ScenarioSpec],
    *,
    agent: AgentTurn,
    simulator: UserSimulator | None = None,
    config: MultiTurnConfig | None = None,
) -> tuple[MultiTurnReport, ...]:
    runner = MultiTurnRunner(agent=agent, simulator=simulator, config=config)
    return tuple(runner.run(scenario) for scenario in scenarios)


def _repeat_count(actions: list[UserAction], action: UserAction) -> int:
    count = 0
    for previous in reversed(actions):
        if previous.action == action.action and previous.message == action.message:
            count += 1
        else:
            break
    return count


def _trace_evidence(trace: NormalizedTrace, turn_id: int) -> tuple[str, ...]:
    return trace.evidence_ids + (f"response:turn_{turn_id}",)


def _failed_trace(case_id: str, reason: str) -> NormalizedTrace:
    return NormalizedTrace(
        case_id=case_id,
        next_action=reason,
        response="",
        status="fail",
        args={"failure_reason": reason},
        termination_reason=reason,
    )


def _version_hash(scenario: ScenarioSpec) -> str:
    payload = scenario.model_dump_json(exclude={"reference_solution"}, exclude_none=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


__all__ = ["AgentTurn", "MultiTurnConfig", "MultiTurnRunner", "run_scenarios"]


def main(argv: list[str] | None = None) -> int:
    """Run a deterministic Pilot dataset and persist dual-sided evidence."""

    import argparse
    import json
    from pathlib import Path

    from src.harness.multiturn_report import build_multiturn_report, write_multiturn_report
    from src.harness.multiturn_schema import ScenarioSpec

    parser = argparse.ArgumentParser(description="Run constrained multi-turn evaluation")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument(
        "--simulator-provider",
        choices=("deterministic_rule", "openai_compatible"),
        default="deterministic_rule",
    )
    parser.add_argument("--simulator-model")
    parser.add_argument("--simulator-base-url")
    parser.add_argument("--simulator-api-key-env", default="SIMULATOR_API_KEY")
    parser.add_argument("--simulator-timeout", type=float, default=30.0)
    parser.add_argument("--simulator-max-tokens", type=int, default=512)
    parser.add_argument("--judge", choices=("off", "on"), default="off")
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-base-url")
    parser.add_argument("--judge-api-key-env", default="MULTITURN_JUDGE_API_KEY")
    args = parser.parse_args(argv)
    scenarios = tuple(
        ScenarioSpec.model_validate(json.loads(line))
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    simulator = None
    runtime = "deterministic_pilot_agent"
    if args.simulator_provider == "openai_compatible":
        import os

        from src.harness.user_simulator import (
            OpenAICompatibleUserSimulatorProvider,
            UserSimulator,
        )

        base_url = args.simulator_base_url or os.getenv("SIMULATOR_API_BASE", "")
        model = args.simulator_model or os.getenv("SIMULATOR_MODEL", "")
        api_key = os.getenv(args.simulator_api_key_env, "")
        try:
            provider = OpenAICompatibleUserSimulatorProvider(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_seconds=args.simulator_timeout,
                max_tokens=args.simulator_max_tokens,
            )
        except ValueError as error:
            parser.error(str(error))
        simulator = UserSimulator(provider, provider.config)
        runtime = "deterministic_pilot_agent+openai_compatible_simulator"

    reports = run_scenarios(
        scenarios,
        agent=_pilot_agent,
        simulator=simulator,
        config=MultiTurnConfig(max_turns=args.max_turns),
    )
    judge_results = None
    judge_metadata: dict[str, str | None] | None = None
    if args.judge == "on":
        import os

        from src.config import get_settings
        from src.harness.judge import JudgeConfig, JudgeUnavailable
        from src.harness.multiturn_judge import (
            MultiTurnJudge,
            MultiTurnJudgeResult,
        )

        judge_base_url = args.judge_base_url or os.getenv("MULTITURN_JUDGE_API_BASE", "")
        judge_model = args.judge_model or os.getenv("MULTITURN_JUDGE_MODEL", "")
        judge_api_key = os.getenv(args.judge_api_key_env, "")
        judge_results = {}
        explicit_judge_override = bool(
            args.judge_base_url
            or args.judge_model
            or os.getenv("MULTITURN_JUDGE_API_BASE")
            or os.getenv("MULTITURN_JUDGE_MODEL")
            or os.getenv(args.judge_api_key_env)
        )
        judge_config = None
        if explicit_judge_override:
            if judge_base_url and judge_model and judge_api_key:
                judge_config = JudgeConfig(
                    model=judge_model,
                    api_base=judge_base_url,
                    api_key=judge_api_key,
                    self_judged=False,
                )
        else:
            try:
                judge_config = JudgeConfig.from_settings(get_settings(), mode="release")
            except JudgeUnavailable:
                judge_config = None
        if judge_config is None:
            judge_metadata = {
                "status": "unavailable",
                "model": judge_model or None,
                "config_hash": None,
            }
            judge_results = {
                item.scenario_id: MultiTurnJudgeResult(
                    scenario_id=item.scenario_id,
                    rubric_id=None,
                    dimension_scores={},
                    weighted_score=None,
                    critical_violations=(),
                    judge_pass=None,
                    error_code="judge_configuration_unavailable",
                    model=judge_model or None,
                    input_hash="sha256:judge_configuration_unavailable",
                )
                for item in reports
            }
        else:
            judge = MultiTurnJudge(judge_config)
            judge_metadata = {
                "status": "configured",
                "model": judge.config.model,
                "config_hash": judge.config.config_hash,
            }
            judge_results = {item.scenario_id: judge.evaluate(item) for item in reports}

    report = build_multiturn_report(
        reports,
        dataset_id=args.dataset.stem,
        dataset_version="pilot-v1",
        runtime=runtime,
        judge_results=judge_results,
    )
    if judge_metadata is not None:
        report["judge_config"] = judge_metadata
    write_multiturn_report(report, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


def _pilot_agent(case: RuntimeCaseInput, _turn_id: int) -> NormalizedTrace:
    """A visible-message-only pilot agent used for harness integration tests."""

    user_messages = [message.content for message in case.messages if message.role == "user"]
    context = " ".join(user_messages)
    if any(word in context for word in ("越权", "密码", "注入", "转账", "安全边界")):
        return NormalizedTrace(
            case_id=case.case_id,
            intent="安全边界",
            route="safety_deescalation",
            next_action="safe_deescalation",
            response="我不能执行这项高风险操作，可以说明安全的下一步。",
            status="complete",
        )
    if "退货" in context and "订单号" not in context:
        return NormalizedTrace(
            case_id=case.case_id,
            intent="售后政策",
            next_action="ask_for_slots",
            response="为了核对售后信息，请先提供订单号。",
            status="complete",
        )
    if (
        ("物流" in context or "订单" in context)
        and "退货" not in context
        and "订单号" not in context
    ):
        return NormalizedTrace(
            case_id=case.case_id,
            intent="查询物流状态",
            next_action="ask_for_slots",
            response="为了查询物流，请先提供订单号。",
            status="complete",
        )
    if (
        ("退货" in context or "售后" in context or "规则" in context)
        and "物流" not in context
        and "订单号" not in context
    ):
        return NormalizedTrace(
            case_id=case.case_id,
            intent="售后政策",
            next_action="ask_for_slots",
            response="为了核对售后信息，请先提供订单号。",
            status="complete",
        )
    if (
        ("商品" in context or "购买" in context or "买" in context)
        and "预算" not in context
        and not ("退货" in context or "售后" in context or "规则" in context)
    ):
        return NormalizedTrace(
            case_id=case.case_id,
            intent="商品推荐",
            next_action="ask_for_slots",
            response="为了给出合适建议，请先告诉我预算。",
            status="complete",
        )
    if "退货" in context:
        intent = "售后政策"
    elif "物流" in context:
        intent = "查询物流状态"
    elif "售后" in context or "规则" in context:
        intent = "售后政策"
    elif "商品" in context or "购买" in context or "买" in context:
        intent = "商品推荐"
    else:
        intent = "情绪陪伴"
    return NormalizedTrace(
        case_id=case.case_id,
        intent=intent,
        route="conversational_response",
        next_action="respond",
        response="我已根据你提供的信息说明当前情况。",
        status="complete",
    )


if __name__ == "__main__":
    raise SystemExit(main())

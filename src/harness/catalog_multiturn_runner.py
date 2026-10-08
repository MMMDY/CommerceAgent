"""Run catalog multi-turn scenarios through deterministic or live Agent Runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.config import get_settings
from src.harness.catalog_loader import load_catalog_dataset
from src.harness.catalog_multiturn import catalog_scenario_to_spec, write_catalog_profiles
from src.harness.catalog_split import load_catalog_split_manifest, scenarios_for_split
from src.harness.judge import JudgeConfig, JudgeUnavailable
from src.harness.live_runtime import LiveCaseRuntime, LiveConfigurationError
from src.harness.multiturn_judge import MultiTurnJudge, MultiTurnJudgeResult
from src.harness.multiturn_report import build_multiturn_report, write_multiturn_report
from src.harness.multiturn_runner import MultiTurnConfig, MultiTurnRunner
from src.harness.schema import NormalizedTrace
from src.harness.trace_adapter import TraceAdapter
from src.harness.user_simulator import (
    OpenAICompatibleUserSimulatorProvider,
    RuleUserSimulator,
    UserSimulator,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.agent_timeout <= 0 or args.scenario_timeout <= 0:
        parser.error("timeouts must be positive")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if bool(args.split) != bool(args.split_manifest):
        parser.error("--split and --split-manifest must be provided together")
    # A deterministic pilot is useful for contract smoke tests, but it is
    # never presented as live Agent Runtime evidence.
    runtime_label = (
        "deterministic_catalog_pilot"
        if args.agent_runtime == "deterministic_pilot"
        else "live_catalog_agent"
    )

    dataset = load_catalog_dataset(args.products, args.qa)
    catalog_scenarios = dataset.scenarios("catalog_multiturn_v1")
    split_metadata: dict[str, object] | None = None
    if args.split:
        manifest = load_catalog_split_manifest(args.split_manifest)
        catalog_scenarios = scenarios_for_split(catalog_scenarios, manifest, args.split)
        partition = next(item for item in manifest.partitions if item.name == args.split)
        split_metadata = {
            "name": args.split,
            "manifest_schema_version": manifest.schema_version,
            "source_hash": manifest.source_hash,
            "seed_count": len(partition.seed_ids),
            "scenario_count": partition.scenario_count,
            "seed_ids": list(partition.seed_ids),
        }
    if args.scenario_id:
        catalog_scenarios = tuple(
            item for item in catalog_scenarios if item.scenario_id == args.scenario_id
        )
        if not catalog_scenarios:
            parser.error("--scenario-id is not present in the selected catalog split")
    if args.limit is not None:
        catalog_scenarios = catalog_scenarios[: args.limit]
    if not catalog_scenarios:
        parser.error("selected catalog dataset is empty")
    scenarios = tuple(catalog_scenario_to_spec(item) for item in catalog_scenarios)
    profile_count = None
    if args.profile_output is not None:
        profile_count = write_catalog_profiles(scenarios, args.profile_output)

    agent, agent_metadata = _build_agent(args)
    simulator = _build_simulator(args, parser)
    runner = MultiTurnRunner(
        agent=agent,
        simulator=simulator,
        config=MultiTurnConfig(
            max_turns=args.max_turns,
            simulation_timeout_seconds=args.agent_timeout,
            scenario_timeout_seconds=args.scenario_timeout,
        ),
    )
    reports = tuple(runner.run(scenario) for scenario in scenarios)

    judge_results, judge_metadata = _run_judge(args, reports, parser)
    report = build_multiturn_report(
        reports,
        dataset_id="long_tail_catalog",
        dataset_version=f"catalog-multiturn:{args.split or 'all'}",
        runtime=runtime_label,
        judge_results=judge_results,
    )
    report["agent_config"] = agent_metadata
    report["judge_config"] = judge_metadata
    if split_metadata is not None:
        report["catalog_split"] = split_metadata
    if args.profile_output is not None:
        report["profile_artifact"] = {
            "path": args.profile_output.name,
            "count": profile_count,
            "status": "complete",
        }
    write_multiturn_report(report, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "completed" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run catalog multi-turn Agent Runtime evaluation")
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument(
        "--split",
        choices=("calibration", "frozen_candidate", "held_out", "candidate"),
    )
    parser.add_argument("--split-manifest", type=Path)
    parser.add_argument(
        "--agent-runtime",
        choices=("deterministic_pilot", "live"),
        default="deterministic_pilot",
    )
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--agent-timeout", type=float, default=60.0)
    parser.add_argument("--scenario-timeout", type=float, default=300.0)
    parser.add_argument("--scenario-id")
    parser.add_argument("--limit", type=int)
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
    return parser


def _build_agent(args: argparse.Namespace):
    if args.agent_runtime == "deterministic_pilot":
        return _catalog_pilot_agent, {
            "provider": "deterministic_pilot",
            "status": "configured",
            "model": "deterministic_catalog_pilot",
            "config_hash": "sha256:deterministic_catalog_pilot_v1",
        }
    if not args.allow_live:
        return _unavailable_agent("live_execution_requires_--allow-live"), {
            "provider": "live",
            "status": "unavailable",
            "reason": "live_execution_requires_--allow-live",
        }
    try:
        runtime = LiveCaseRuntime(settings=get_settings())
    except LiveConfigurationError as error:
        return _unavailable_agent(type(error).__name__), {
            "provider": "live",
            "status": "unavailable",
            "reason": type(error).__name__,
        }

    adapter = TraceAdapter()

    def live_agent(case, _turn_id):
        trace = runtime.execute_case(
            case=case,
            fixture={},
            timeout_seconds=args.agent_timeout,
            cancelled=lambda: False,
        )
        return adapter.normalize(case_id=case.case_id, trace=trace)

    return live_agent, {
        "provider": getattr(runtime.gateway, "provider", "unknown"),
        "status": "configured",
        "model": getattr(runtime.gateway, "model_name", "unknown"),
        "config_hash": getattr(runtime.gateway, "config_hash", None),
        "classifier_config_hash": getattr(runtime.gateway, "classifier_config_hash", None),
    }


def _build_simulator(args: argparse.Namespace, parser: argparse.ArgumentParser):
    if args.simulator_provider == "deterministic_rule":
        return UserSimulator(RuleUserSimulator())
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
    return UserSimulator(provider, provider.config)


def _run_judge(args: argparse.Namespace, reports: tuple, parser: argparse.ArgumentParser):
    if args.judge == "off":
        return None, {"status": "disabled", "model": None, "config_hash": None}
    base_url = args.judge_base_url or os.getenv("MULTITURN_JUDGE_API_BASE", "")
    model = args.judge_model or os.getenv("MULTITURN_JUDGE_MODEL", "")
    api_key = os.getenv(args.judge_api_key_env, "")
    explicit_judge_override = bool(
        args.judge_base_url
        or args.judge_model
        or os.getenv("MULTITURN_JUDGE_API_BASE")
        or os.getenv("MULTITURN_JUDGE_MODEL")
        or os.getenv(args.judge_api_key_env)
    )
    judge_config = None
    if explicit_judge_override:
        if base_url and model and api_key:
            judge_config = JudgeConfig(
                model=model,
                api_base=base_url,
                api_key=api_key,
                self_judged=False,
            )
    else:
        try:
            judge_config = JudgeConfig.from_settings(get_settings(), mode="release")
        except JudgeUnavailable:
            judge_config = None
    if judge_config is None:
        results = {
            item.scenario_id: MultiTurnJudgeResult(
                scenario_id=item.scenario_id,
                rubric_id=None,
                dimension_scores={},
                weighted_score=None,
                critical_violations=(),
                judge_pass=None,
                error_code="judge_configuration_unavailable",
                model=model or None,
                input_hash="sha256:judge_configuration_unavailable",
            )
            for item in reports
        }
        return results, {"status": "unavailable", "model": model or None, "config_hash": None}
    try:
        judge = MultiTurnJudge(judge_config)
    except Exception as error:
        parser.error(str(error))
    return (
        {item.scenario_id: judge.evaluate(item) for item in reports},
        {
            "status": "configured",
            "model": judge.config.model,
            "config_hash": judge.config.config_hash,
        },
    )


def _catalog_pilot_agent(case, _turn_id):
    user_text = " ".join(message.content for message in case.messages if message.role == "user")
    if any(word in user_text for word in ("混用", "消毒液", "洁厕灵")):
        return NormalizedTrace(
            case_id=case.case_id,
            intent="safety_boundary",
            route="safety_deescalation",
            next_action="safe_deescalation",
            response="请停止混用并按照产品标签或官方说明处理。",
            status="complete",
        )
    return NormalizedTrace(
        case_id=case.case_id,
        intent="product_information",
        route="catalog_query",
        next_action="respond",
        response="我已根据可见商品卡片说明建议。",
        status="complete",
    )


def _unavailable_agent(reason: str):
    def agent(case, _turn_id):
        return NormalizedTrace(
            case_id=case.case_id,
            next_action=reason,
            response="",
            status="fail",
        )

    return agent


if __name__ == "__main__":
    raise SystemExit(main())

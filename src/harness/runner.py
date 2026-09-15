"""CLI for the deterministic Phase 2 hard-evaluation harness.

No Judge is invoked here.  Runtime behavior comes from an independent,
strictly validated fixture that drives the project's real AgentLoop boundary.
"""

from __future__ import annotations

import argparse
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from src.harness.deterministic_runtime import (
    DeterministicRuntimeFactory,
    RuntimeFixtureError,
    RuntimeFixtureLoader,
)
from src.harness.loader import CaseLoader, DatasetContractError
from src.harness.run_driver import RunDriver
from src.harness.judge import JudgeConfig, JudgeUnavailable, RubricJudge
from src.harness.report import build_report, write_report
from src.config import get_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CommerceAgent evaluation harness")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--track")
    parser.add_argument("--case-id")
    parser.add_argument("--judge", choices=("off", "on"), default="off")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--mode", choices=("debug", "release"), default="debug")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--runtime-fixture",
        type=Path,
        help="strict JSONL runtime fixture (default: <dataset-stem>.runtime.jsonl)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.repetitions <= 0 or args.repetitions > 3:
        raise SystemExit("--repetitions must be between 1 and 3")
    if args.mode == "release" and args.judge != "on":
        raise SystemExit("release mode requires --judge on")
    cancelled = False

    def on_interrupt(_signum: int, _frame: object) -> None:
        nonlocal cancelled
        cancelled = True

    previous = signal.signal(signal.SIGINT, on_interrupt)
    try:
        loader = CaseLoader(args.dataset)
        cases = loader.load(track=args.track, case_id=args.case_id)
        fixture_path = args.runtime_fixture or args.dataset.with_suffix(".runtime.jsonl")
        runtime_loader = RuntimeFixtureLoader(fixture_path)
        runtime = DeterministicRuntimeFactory(runtime_loader.load())
        driver = RunDriver(runtime=runtime)
        results = []
        judge_results = {}
        judge_runner = None
        judge_unavailable = False
        if args.judge == "on":
            try:
                judge_runner = RubricJudge(JudgeConfig.from_settings(get_settings(), mode=args.mode))
            except JudgeUnavailable:
                judge_unavailable = True
        for case in cases:
            if cancelled:
                break
            for _ in range(args.repetitions):
                if cancelled:
                    break
                result = driver.run_case(case=case, timeout_seconds=args.timeout, cancelled=lambda: cancelled)
                results.append(result)
                # Pure intent routing is deterministically judged by hard gates;
                # rubric calls are reserved for the 150 non-intent cases.
                if judge_runner is not None and case.task_type != "intent_route":
                    judge_results[case.id] = judge_runner.evaluate(case=case, trace=result.trace, hard_result=result.hard_eval)
        report = build_report(cases, results, judges=judge_results, judge_enabled=args.judge == "on", dataset_hash=loader.dataset_hash(), runtime_hash=runtime_loader.fixture_hash(), mode=args.mode, repetitions=args.repetitions, cancelled=cancelled)
        report["runtime"] = "deterministic_fixture"
        report["runtime_fixture_hash"] = runtime_loader.fixture_hash()
        report["prompt_hash"] = "sha256:commerce-agent-deterministic-runtime-prompt-v1"
        if judge_unavailable:
            report["status"] = "incomplete"
            report["judge_error"] = "judge_configuration_unavailable"
            report["self_judged"] = False
        if args.output_dir:
            write_report(report, args.output_dir)
        import json
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except DatasetContractError as error:
        raise SystemExit(f"dataset contract error: {error}") from error
    except RuntimeFixtureError as error:
        raise SystemExit(f"runtime fixture contract error: {error}") from error
    finally:
        signal.signal(signal.SIGINT, previous)


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()

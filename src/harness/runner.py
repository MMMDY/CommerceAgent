"""CLI for the deterministic Phase 2 hard-evaluation harness.

No Judge is invoked here.  Runtime behavior comes from an independent,
strictly validated fixture that drives the project's real AgentLoop boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CommerceAgent static hard evaluator")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--track")
    parser.add_argument("--case-id")
    parser.add_argument("--judge", choices=("off",), default="off")
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
        for case in cases:
            if cancelled:
                break
            result = driver.run_case(
                case=case, timeout_seconds=args.timeout, cancelled=lambda: cancelled
            )
            results.append(
                {
                    "case_id": case.id,
                    "track": case.task_type,
                    "hard_pass": result.hard_eval.passed,
                    "hard_fail_reasons": result.hard_eval.hard_fail_reasons,
                    "dimensions": result.hard_eval.dimensions,
                    "runtime_error": result.runtime_error,
                }
            )
        report = {
            "schema_version": "1.0",
            "dataset_hash": loader.dataset_hash(),
            "judge": "off",
            "runtime": "deterministic_fixture",
            "runtime_hash": runtime_loader.fixture_hash(),
            "runtime_fixture_hash": runtime_loader.fixture_hash(),
            "prompt_hash": hashlib.sha256(
                b"commerce-agent:deterministic-runtime-prompt-v1"
            ).hexdigest(),
            "cancelled": cancelled,
            "selected_cases": len(cases),
            "completed_cases": len(results),
            "passed_cases": sum(1 for item in results if item["hard_pass"] is True),
            "failed_cases": sum(1 for item in results if item["hard_pass"] is not True),
            "results": results,
        }
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

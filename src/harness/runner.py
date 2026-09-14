"""CLI for the static hard-evaluation harness.

No Judge is invoked here.  Until a production Runtime is wired in Phase 3, the
default runtime intentionally emits a safe failure trace rather than deriving
an answer from the evaluation's gold fields.
"""

from __future__ import annotations

import argparse
import json
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from src.harness.loader import CaseLoader, DatasetContractError
from src.harness.run_driver import RunDriver
from src.harness.runtime import RuntimeTrace
from src.harness.schema import EvalCase


class _FailClosedRuntime:
    def execute_case(
        self,
        *,
        case: EvalCase,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: object,
    ) -> RuntimeTrace:
        return RuntimeTrace(
            route=None,
            intent=None,
            next_action=None,
            args={},
            tools_called=(),
            evidence_ids=(),
            response="",
            status="fail",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CommerceAgent static hard evaluator")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--track")
    parser.add_argument("--case-id")
    parser.add_argument("--judge", choices=("off",), default="off")
    parser.add_argument("--timeout", type=float, default=30.0)
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
        driver = RunDriver(runtime=_FailClosedRuntime())
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
    finally:
        signal.signal(signal.SIGINT, previous)


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()

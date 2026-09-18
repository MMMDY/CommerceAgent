"""CLI for the deterministic Phase 2 hard-evaluation harness.

No Judge is invoked here.  Runtime behavior comes from an independent,
strictly validated fixture that drives the project's real AgentLoop boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn
from uuid import NAMESPACE_URL, UUID, uuid5

from src.config import get_settings
from src.db import get_engine
from src.evolution.failure_attribution import FailureAttributionService
from src.harness.calibration import calibration_report, load_labels, validate_stratification
from src.harness.deterministic_runtime import (
    DeterministicRuntimeFactory,
    RuntimeFixtureError,
    RuntimeFixtureLoader,
)
from src.harness.judge import JudgeConfig, JudgeUnavailable, RubricJudge
from src.harness.loader import CaseLoader, DatasetContractError
from src.harness.report import build_report, write_report
from src.harness.run_driver import RunDriver
from src.repositories.evaluations import EvaluationRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CommerceAgent evaluation harness")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--track")
    parser.add_argument("--case-id")
    parser.add_argument("--judge", choices=("off", "on"), default="off")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--mode", choices=("debug", "release"), default="debug")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--eval-run-id", type=str)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--cost-budget-microusd", type=int)
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
        if fixture_path.is_file():
            runtime = DeterministicRuntimeFactory(runtime_loader.load())
            runtime_hash = runtime_loader.fixture_hash()
            runtime_source = "fixture_file"
        elif args.runtime_fixture is not None:
            # An explicitly supplied fixture is a contract, so a missing
            # path remains an error rather than silently becoming a
            # code-owned scenario.
            runtime = DeterministicRuntimeFactory(runtime_loader.load())
            runtime_hash = runtime_loader.fixture_hash()
            runtime_source = "fixture_file"
        else:
            # Synthetic tracks may be fully defined by the independent,
            # code-owned factory.  The report still carries a stable hash
            # and says which source supplied the runtime boundary.
            runtime = DeterministicRuntimeFactory(())
            runtime_hash = hashlib.sha256(
                b"commerce-agent-code-owned-deterministic-runtime-v1"
            ).hexdigest()
            runtime_source = "code_owned_factory"
        driver = RunDriver(runtime=runtime)
        results = []
        judge_results = {}
        eval_run_id = args.eval_run_id or str(
            uuid5(
                NAMESPACE_URL,
                f"commerce-eval:{loader.dataset_hash()}:{args.track}:{args.case_id}:{args.judge}:{args.mode}:{args.repetitions}",
            )
        )
        persistence = None
        failure_projection: FailureAttributionService | None = None
        persisted_id: UUID | None = None
        settings = get_settings()
        try:
            if settings.database_url:
                engine = get_engine()
                persistence = EvaluationRepository(engine)
                failure_projection = FailureAttributionService(engine)
                persisted_id = persistence.create_run(
                    eval_run_id=UUID(eval_run_id) if args.eval_run_id else None,
                    dataset_hash=loader.dataset_hash(),
                    rubric_version="1.0",
                    config={
                        "judge": args.judge,
                        "mode": args.mode,
                        "repetitions": args.repetitions,
                        "concurrency": 1,
                    },
                )
                if args.eval_run_id:
                    # API-created batches use their externally assigned UUID;
                    # the repository currently allocates IDs for CLI runs.
                    eval_run_id = str(persisted_id)
        except Exception:
            # Evaluation must still emit a complete local report when the
            # optional database is down; persistence status is explicit.
            persistence = None
            failure_projection = None
        judge_runner = None
        judge_unavailable = False
        if args.judge == "on":
            try:
                judge_runner = RubricJudge(
                    JudgeConfig.from_settings(get_settings(), mode=args.mode)
                )
            except JudgeUnavailable:
                judge_unavailable = True
        for case in cases:
            if cancelled:
                break
            for attempt_no in range(1, args.repetitions + 1):
                if cancelled:
                    break
                result = driver.run_case(
                    case=case, timeout_seconds=args.timeout, cancelled=lambda: cancelled
                )
                results.append(result)
                if persistence is not None:
                    assert persisted_id is not None
                    try:
                        persistence.record_hard_result(
                            eval_run_id=persisted_id,
                            case_id=case.id,
                            track=case.task_type,
                            hard_pass=result.hard_eval.passed,
                            attempt_no=attempt_no,
                            result={
                                "hard_fail_reasons": list(result.hard_eval.hard_fail_reasons),
                                "dimensions": result.hard_eval.dimensions,
                            },
                        )
                    except Exception:
                        persistence = None
                # Pure intent routing is deterministically judged by hard gates;
                # rubric calls are reserved for the 150 non-intent cases.
                judged = None
                if judge_runner is not None and case.task_type != "intent_route":
                    judged = judge_runner.evaluate(
                        case=case, trace=result.trace, hard_result=result.hard_eval
                    )
                    judge_results[f"{case.id}#{attempt_no}"] = judged
                    if persistence is not None:
                        assert persisted_id is not None
                        try:
                            persistence.record_judge_result(
                                eval_run_id=persisted_id,
                                case_id=case.id,
                                judge_model=judged.model or "unknown",
                                score=judged.weighted_score,
                                result={
                                    "dimension_scores": judged.dimension_scores,
                                    "critical_violations": list(judged.critical_violations),
                                    "input_hash": judged.input_hash,
                                },
                                self_judged=judged.self_judged,
                                judge_attempt_no=attempt_no,
                                rubric_id=judged.rubric_id,
                                rubric_version=judge_runner.rubric_version,
                                input_hash=judged.input_hash,
                                judge_pass=judged.judge_pass,
                                error_code=judged.error_code,
                            )
                        except Exception:
                            persistence = None
                if failure_projection is not None and persisted_id is not None:
                    eval_failed = not result.hard_eval.passed or (
                        judged is not None and judged.judge_pass is False
                    )
                    reason = (
                        "HARD_GATE_FAIL"
                        if not result.hard_eval.passed
                        else "JUDGE_FAIL"
                        if judged is not None and judged.judge_pass is False
                        else "EVALUATION_FAILED"
                    )
                    try:
                        failure_projection.record_evaluation_outcome(
                            tenant_id=args.tenant_id,
                            eval_run_id=persisted_id,
                            case_id=case.id,
                            track=case.task_type,
                            eval_failed=eval_failed,
                            cost_microusd=result.agent_cost_microusd,
                            cost_budget_microusd=(
                                args.cost_budget_microusd
                                if args.cost_budget_microusd is not None
                                else settings.evaluation_case_cost_budget_microusd
                            ),
                            failure_reason=reason,
                        )
                    except Exception:
                        # Failure learning is auxiliary to the evaluation
                        # report and must not fail an otherwise complete run.
                        pass
        report = build_report(
            cases,
            results,
            judges=judge_results,
            judge_enabled=args.judge == "on",
            dataset_hash=loader.dataset_hash(),
            dataset_id=loader.dataset_id,
            dataset_version=loader.dataset_version,
            manifest_hash=_mapping_hash(loader.manifest),
            runtime_hash=runtime_hash,
            runtime="deterministic_fixture",
            prompt_hash="sha256:commerce-agent-deterministic-runtime-prompt-v1",
            rubric_hash=_file_hash(args.dataset.parent / "rubrics.json"),
            runtime_versions={"fixture_hash": runtime_hash, "source": runtime_source},
            mode=args.mode,
            repetitions=args.repetitions,
            cancelled=cancelled,
        )
        report["runtime_fixture_hash"] = runtime_hash
        report["eval_run_id"] = eval_run_id
        report["source_commit"] = _source_commit()
        generator_config_hash = loader.manifest.get("generator_config_hash")
        if isinstance(generator_config_hash, str):
            report["generator_config_hash"] = generator_config_hash
        if judge_runner is not None:
            report["judge_prompt_hash"] = f"sha256:{judge_runner.prompt_hash}"
            report["judge_config_hash"] = judge_runner.config.config_hash
            report["rubric_version"] = judge_runner.rubric_version
            calibration_path = args.dataset.parent / "calibration_labels.jsonl"
            if calibration_path.is_file():
                try:
                    labels = load_labels(calibration_path)
                    validate_stratification(labels, dataset=args.dataset)
                    report["calibration"] = calibration_report(
                        labels,
                        judge_results.values(),
                        judge_model=judge_runner.config.model,
                        prompt_hash=f"sha256:{judge_runner.prompt_hash}",
                        rubric_version=judge_runner.rubric_version,
                    )
                except (OSError, ValueError):
                    report["calibration"] = {
                        "status": "incomplete",
                        "error": "calibration_unavailable",
                    }
        if judge_unavailable:
            report["status"] = "incomplete"
            report["judge_error"] = "judge_configuration_unavailable"
            report["self_judged"] = False
        if loader.manifest.get("requires_human_approval_before_release") is True:
            # Dataset metadata is not a human approval record.  Automated
            # evaluation may still produce hard/Judge evidence, but it must
            # remain incomplete until the separate approver workflow records
            # a review decision.
            report["human_approval"] = {
                "required": True,
                "status": "pending",
                "source": "separate_approver_workflow",
            }
            report["release_gate"] = False
            if report["status"] != "cancelled":
                report["status"] = "incomplete"
        if persistence is not None:
            assert persisted_id is not None
            try:
                persistence.finish(eval_run_id=persisted_id, status=str(report["status"]))
            except Exception:
                report["persistence"] = "unavailable"
            else:
                report["persistence"] = "postgres"
        else:
            report["persistence"] = "local_report_only"
        if args.output_dir:
            write_report(report, args.output_dir)
            if "calibration" in report:
                import json as _json

                Path(args.output_dir).mkdir(parents=True, exist_ok=True)
                (Path(args.output_dir) / "calibration.json").write_text(
                    _json.dumps(
                        report["calibration"], ensure_ascii=False, indent=2, sort_keys=True
                    ),
                    encoding="utf-8",
                )
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


def _source_commit() -> str | None:
    """Return the exact source revision used by the runner when available."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _mapping_hash(value: dict[str, object]) -> str | None:
    if not value:
        return None
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode()).hexdigest()}"


if __name__ == "__main__":
    _exit()

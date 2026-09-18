"""Explicit live-model evaluation command.

Unlike the deterministic runner, this command never silently substitutes a
fixture.  It either runs the configured model/PostgreSQL boundaries or emits
an ``incomplete`` report explaining why live evidence is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.config import get_settings
from src.evolution.failure_attribution import FailureAttributionService
from src.harness.judge import JudgeConfig, JudgeUnavailable, RubricJudge
from src.harness.live_runtime import LiveCaseRuntime, LiveConfigurationError
from src.harness.loader import CaseLoader
from src.harness.report import build_report, write_report
from src.harness.run_driver import RunDriver
from src.harness.schema import EvalCase
from src.repositories.evaluations import EvaluationRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an explicit CommerceAgent live E2E evaluation"
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--track")
    parser.add_argument("--case-id")
    parser.add_argument("--judge", choices=("off", "on"), default="on")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--mode", choices=("debug", "release"), default="debug")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--eval-run-id", type=str)
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--actor-id", default="demo-user-001")
    parser.add_argument("--cost-budget-microusd", type=int)
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="required acknowledgement that this command may call external models and PostgreSQL",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repetitions < 1 or args.repetitions > 3:
        raise SystemExit("--repetitions must be between 1 and 3")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if args.mode == "release" and args.judge != "on":
        raise SystemExit("release mode requires --judge on")
    loader = CaseLoader(args.dataset)
    cases = loader.load(track=args.track, case_id=args.case_id)
    eval_run_id = _parse_eval_id(args.eval_run_id)
    output_dir = args.output_dir or Path("evals/reports") / f"live-{eval_run_id}"
    rubric_path = args.rubric or (args.dataset.parent / "rubrics.json")
    settings = get_settings()
    cancelled = False

    def on_interrupt(_signum: int, _frame: object) -> None:
        nonlocal cancelled
        cancelled = True

    previous = signal.signal(signal.SIGINT, on_interrupt)
    try:
        if not args.allow_live:
            report = _incomplete_report(
                cases=cases,
                loader=loader,
                eval_run_id=eval_run_id,
                reason="live_execution_requires_--allow-live",
                mode=args.mode,
                repetitions=args.repetitions,
                judge_enabled=args.judge == "on",
            )
            _finish(report, output_dir)
            return 2
        try:
            runtime = LiveCaseRuntime(
                settings=settings, tenant_id=args.tenant_id, actor_id=args.actor_id
            )
        except LiveConfigurationError as error:
            report = _incomplete_report(
                cases=cases,
                loader=loader,
                eval_run_id=eval_run_id,
                reason=type(error).__name__,
                mode=args.mode,
                repetitions=args.repetitions,
                judge_enabled=args.judge == "on",
            )
            _finish(report, output_dir)
            return 2

        judge: RubricJudge | None = None
        if args.judge == "on":
            try:
                judge = RubricJudge(
                    JudgeConfig.from_settings(settings, mode=args.mode),
                    rubric_path=rubric_path,
                )
            except (JudgeUnavailable, OSError, json.JSONDecodeError) as error:
                report = _incomplete_report(
                    cases=cases,
                    loader=loader,
                    eval_run_id=eval_run_id,
                reason=type(error).__name__,
                mode=args.mode,
                repetitions=args.repetitions,
                judge_enabled=args.judge == "on",
            )
                _finish(report, output_dir)
                return 2

        driver = RunDriver(runtime=runtime)
        persistence: EvaluationRepository | None = None
        failure_projection: FailureAttributionService | None = None
        persisted_id = eval_run_id
        persistence_error: str | None = None
        try:
            if settings.database_url:
                from src.db import get_engine

                engine = get_engine()
                persistence = EvaluationRepository(engine)
                failure_projection = FailureAttributionService(engine)
                persisted_id = persistence.create_run(
                    eval_run_id=eval_run_id,
                    dataset_hash=loader.dataset_hash(),
                    rubric_version="unknown",
                    config={
                        "runtime": "live_model",
                        "judge": args.judge,
                        "mode": args.mode,
                        "repetitions": args.repetitions,
                        "timeout_seconds": args.timeout,
                    },
                    dataset_version=loader.dataset_version,
                    agent_model=getattr(runtime.gateway, "model_name", None),
                    agent_model_config_hash=getattr(runtime.gateway, "config_hash", None),
                    agent_prompt_hash="sha256:live-eval-tool-protocol-v1",
                    runtime_versions={
                        "knowledge_runtime": "postgresql",
                        "sandbox_policy": "prepare_only_no_commit",
                    },
                    concurrency=1,
                    case_timeout_seconds=round(args.timeout),
                )
        except Exception:
            # A live evaluation may still be useful as a local artifact, but
            # it must say that the durable evaluation record is unavailable.
            persistence = None
            failure_projection = None
            persistence_error = "evaluation_persistence_unavailable"
        results = []
        judges: dict[str, Any] = {}
        for case in cases:
            for attempt_no in range(1, args.repetitions + 1):
                if cancelled:
                    break
                driven = driver.run_case(
                    case=case, timeout_seconds=args.timeout, cancelled=lambda: cancelled
                )
                results.append(driven)
                if persistence is not None:
                    try:
                        persistence.record_hard_result(
                            eval_run_id=persisted_id,
                            case_id=case.id,
                            track=case.task_type,
                            hard_pass=driven.hard_eval.passed,
                            attempt_no=attempt_no,
                            result={
                                "hard_fail_reasons": list(driven.hard_eval.hard_fail_reasons),
                                "dimensions": driven.hard_eval.dimensions,
                            },
                        )
                    except Exception:
                        persistence = None
                        persistence_error = "evaluation_persistence_unavailable"
                if judge is not None:
                    judged = judge.evaluate(
                        case=case, trace=driven.trace, hard_result=driven.hard_eval
                    )
                    judges[f"{case.id}#{attempt_no}"] = judged
                    if persistence is not None:
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
                                rubric_version=judge.rubric_version,
                                input_hash=judged.input_hash,
                                judge_pass=judged.judge_pass,
                                error_code=judged.error_code,
                            )
                        except Exception:
                            persistence = None
                            persistence_error = "evaluation_persistence_unavailable"
                else:
                    judged = None
                if failure_projection is not None:
                    eval_failed = not driven.hard_eval.passed or (
                        judged is not None and judged.judge_pass is False
                    )
                    reason = (
                        "HARD_GATE_FAIL"
                        if not driven.hard_eval.passed
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
                            cost_microusd=driven.agent_cost_microusd,
                            cost_budget_microusd=(
                                args.cost_budget_microusd
                                if args.cost_budget_microusd is not None
                                else settings.evaluation_case_cost_budget_microusd
                            ),
                            failure_reason=reason,
                        )
                    except Exception:
                        # Failure learning is auxiliary to the live report.
                        pass
            if cancelled:
                break

        report = build_report(
            cases,
            results,
            judges=judges,
            judge_enabled=args.judge == "on",
            dataset_hash=loader.dataset_hash(),
            dataset_id=loader.dataset_id,
            dataset_version=loader.dataset_version,
            manifest_hash=_manifest_hash(loader.manifest),
            runtime_hash=f"live:{_gateway_value(runtime.gateway, 'config_hash')}",
            runtime="live_model",
            rubric_hash=_file_hash(rubric_path),
            runtime_versions={
                "knowledge_runtime": "postgresql",
                "sandbox_policy": "prepare_only_no_commit",
            },
            mode=args.mode,
            repetitions=args.repetitions,
            cancelled=cancelled,
        )
        report.update(
            {
                "runtime": "live_model",
                "runtime_versions": {
                    "agent_model": _gateway_value(runtime.gateway, "model_name"),
                    "agent_config_hash": _gateway_value(runtime.gateway, "config_hash"),
                    "classifier_config_hash": _gateway_value(
                        runtime.gateway, "classifier_config_hash"
                    ),
                    "knowledge_runtime": "postgresql",
                    "sandbox_policy": "prepare_only_no_commit",
                },
                "dataset_id": loader.dataset_id,
                "dataset_version": loader.dataset_version,
                "manifest_hash": _manifest_hash(loader.manifest),
                "eval_run_id": str(eval_run_id),
                "source_commit": _source_commit(),
                "rubric_path": str(rubric_path),
                "persistence": "postgres" if persistence is not None else "local_report_only",
            }
        )
        generator_config_hash = loader.manifest.get("generator_config_hash")
        if isinstance(generator_config_hash, str):
            report["generator_config_hash"] = generator_config_hash
        if persistence_error is not None:
            report["persistence_error"] = persistence_error
        if judge is not None:
            report["judge_prompt_hash"] = f"sha256:{judge.prompt_hash}"
            report["judge_config_hash"] = judge.config.config_hash
            report["rubric_version"] = judge.rubric_version
        if persistence is not None:
            try:
                persistence.finish(eval_run_id=persisted_id, status=str(report["status"]))
            except Exception:
                report["persistence"] = "local_report_only"
                report["persistence_error"] = "evaluation_persistence_unavailable"
        _finish(report, output_dir)
        return 0 if report.get("status") == "completed" else 2
    finally:
        signal.signal(signal.SIGINT, previous)


def _incomplete_report(
    *,
    cases: list[EvalCase],
    loader: CaseLoader,
    eval_run_id: UUID,
    reason: str,
    mode: str,
    repetitions: int,
    judge_enabled: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "status": "incomplete",
        "runtime": "live_model",
        "incomplete_reason": reason,
        "dataset_id": loader.dataset_id,
        "dataset_version": loader.dataset_version,
        "dataset_hash": loader.dataset_hash(),
        "manifest_hash": _manifest_hash(loader.manifest),
        "eval_run_id": str(eval_run_id),
        "mode": mode,
        "judge": "on" if judge_enabled else "off",
        "repetitions": repetitions,
        "selected_cases": len(cases),
        "completed_cases": 0,
        "attempts": 0,
        "passed_cases": 0,
        "failed_cases": 0,
        "first_pass_rate": None,
        "all_repetitions_pass_rate": None,
        "tracks": {},
        "judge_dimension_stats": {},
        "judge_score_stats": {},
        "performance_stats": {},
        "results": [],
    }


def _finish(report: dict[str, Any], output_dir: Path) -> None:
    write_report(report, output_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _parse_eval_id(value: str | None) -> UUID:
    if value is None:
        return uuid4()
    try:
        return UUID(value)
    except ValueError as error:
        raise SystemExit("--eval-run-id must be a UUID") from error


def _manifest_hash(manifest: dict[str, Any]) -> str | None:
    if not manifest:
        return None
    serialized = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode()).hexdigest()}"


def _file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _source_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _gateway_value(gateway: object, name: str) -> str:
    value = getattr(gateway, name, None)
    return value if isinstance(value, str) and value else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]

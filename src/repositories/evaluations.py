"""Persistence for reproducible evaluation runs and judge annotations."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    eval_run_id: UUID
    dataset_hash: str
    rubric_version: str
    status: str


class EvaluationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_run(self, *, dataset_hash: str, rubric_version: str, config: dict[str, object]) -> UUID:
        run_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO evaluation.eval_runs "
                "(eval_run_id, dataset_hash, rubric_version, status, config_json, created_at) "
                "VALUES (:run_id, :dataset_hash, :rubric_version, 'running', CAST(:config AS jsonb), now())"),
                {"run_id": run_id, "dataset_hash": dataset_hash, "rubric_version": rubric_version,
                 "config": json.dumps(config)})
        return run_id

    def record_hard_result(self, *, eval_run_id: UUID, case_id: str, track: str, hard_pass: bool,
                           result: dict[str, object]) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO evaluation.eval_case_results "
                "(eval_run_id, case_id, track, hard_pass, result_json, created_at) "
                "VALUES (:run_id, :case_id, :track, :hard_pass, CAST(:result AS jsonb), now())"),
                {"run_id": eval_run_id, "case_id": case_id, "track": track, "hard_pass": hard_pass,
                 "result": json.dumps(result)})

    def record_judge_result(self, *, eval_run_id: UUID, case_id: str, judge_model: str,
                            score: float | None, result: dict[str, object], self_judged: bool) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO evaluation.judge_results "
                "(eval_run_id, case_id, judge_model, score, result_json, self_judged, created_at) "
                "VALUES (:run_id, :case_id, :judge_model, :score, CAST(:result AS jsonb), :self_judged, now())"),
                {"run_id": eval_run_id, "case_id": case_id, "judge_model": judge_model, "score": score,
                 "result": json.dumps(result), "self_judged": self_judged})

    def finish(self, *, eval_run_id: UUID, status: str) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(text("UPDATE evaluation.eval_runs SET status = :status, finished_at = now() "
                "WHERE eval_run_id = :run_id AND status = 'running'"), {"run_id": eval_run_id, "status": status})
        return result.rowcount == 1

    def get_run(self, *, eval_run_id: UUID) -> dict[str, object] | None:
        """Return a redacted run summary for the eval API."""
        with self._engine.begin() as connection:
            row = connection.execute(text(
                "SELECT eval_run_id, dataset_hash, rubric_version, status, config_json, created_at, finished_at "
                "FROM evaluation.eval_runs WHERE eval_run_id = :run_id"
            ), {"run_id": eval_run_id}).mappings().first()
        return dict(row) if row else None

    def list_case_results(
        self, *, eval_run_id: UUID, limit: int = 50, offset: int = 0,
        track: str | None = None, failed_only: bool = False,
    ) -> list[dict[str, object]]:
        limit = max(1, min(limit, 200)); offset = max(0, offset)
        clauses = ["eval_run_id = :run_id"]
        params: dict[str, object] = {"run_id": eval_run_id, "limit": limit, "offset": offset}
        if track:
            clauses.append("track = :track"); params["track"] = track
        if failed_only:
            clauses.append("hard_pass = false")
        where = " AND ".join(clauses)
        with self._engine.begin() as connection:
            rows = connection.execute(text(
                f"SELECT eval_run_id, case_id, track, hard_pass, result_json, created_at "
                f"FROM evaluation.eval_case_results WHERE {where} ORDER BY case_id LIMIT :limit OFFSET :offset"
            ), params).mappings().all()
        return [dict(row) for row in rows]

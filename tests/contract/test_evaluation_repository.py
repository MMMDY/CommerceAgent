"""PostgreSQL contracts for evaluation persistence."""

# ruff: noqa: E501

from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError

from src.repositories.evaluations import EvaluationRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def test_evaluation_results_require_hard_result_and_finish_once(engine: Engine) -> None:
    repository = EvaluationRepository(engine)
    run_id = repository.create_run(dataset_hash="dataset", rubric_version="rubric", config={"judge": "off"})
    with pytest.raises(IntegrityError):
        repository.record_judge_result(eval_run_id=run_id, case_id="case", judge_model="judge", score=3,
            result={}, self_judged=False)
    repository.record_hard_result(eval_run_id=run_id, case_id="case", track="intent_route", hard_pass=True,
        result={"passed": True})
    repository.record_judge_result(eval_run_id=run_id, case_id="case", judge_model="judge", score=3,
        result={"score": 3}, self_judged=False)
    assert repository.finish(eval_run_id=run_id, status="completed") is True
    assert repository.finish(eval_run_id=run_id, status="completed") is False

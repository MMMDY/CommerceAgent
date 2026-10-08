from typing import Any, cast
from uuid import uuid4

from sqlalchemy.engine import Engine

from src.repositories.failures import FailureRepository


class _Result:
    def mappings(self) -> "_Result":
        return self

    def all(self) -> list[dict[str, Any]]:
        return []


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self.calls.append((str(statement), params))
        return _Result()


class _Engine:
    def __init__(self) -> None:
        self.connection = _Connection()

    def connect(self) -> _Connection:
        return self.connection


def test_failure_list_filters_by_tenant_and_cluster_without_browser_side_join() -> None:
    engine = _Engine()

    result = FailureRepository(cast(Engine, engine)).list(
        tenant_id="demo-tenant", cluster_key="cluster:social"
    )

    assert result == ()
    sql, params = engine.connection.calls[0]
    assert "tenant_id = :tenant_id" in sql
    assert "cluster_key = :cluster_key" in sql
    assert params == {
        "tenant_id": "demo-tenant",
        "cluster_key": "cluster:social",
        "limit": 100,
    }


def test_failure_summary_uses_the_same_cluster_filter_for_all_aggregates() -> None:
    engine = _Engine()

    summary = FailureRepository(cast(Engine, engine)).summary(
        tenant_id="demo-tenant", window_days=7, cluster_key="cluster:social"
    )

    assert summary["trend"] == []
    assert len(engine.connection.calls) == 5
    for sql, params in engine.connection.calls:
        assert "cluster_key = :cluster_key" in sql
        assert params["cluster_key"] == "cluster:social"
    assert "failure.cluster_key = :cluster_key" in engine.connection.calls[1][0]


def test_failure_list_supports_explicit_run_and_evaluation_links() -> None:
    engine = _Engine()
    run_id = uuid4()
    eval_run_id = uuid4()

    FailureRepository(cast(Engine, engine)).list(
        tenant_id="demo-tenant",
        run_id=run_id,
        eval_run_id=eval_run_id,
        case_id="case_001",
    )

    sql, params = engine.connection.calls[0]
    assert "run_id = :run_id" in sql
    assert "eval_run_id = :eval_run_id" in sql
    assert "case_id = :case_id" in sql
    assert params["run_id"] == run_id
    assert params["eval_run_id"] == eval_run_id
    assert params["case_id"] == "case_001"

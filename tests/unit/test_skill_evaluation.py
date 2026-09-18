from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.api.main import SkillEvaluationCreateRequest
from src.repositories.skills import SkillTransitionError, _metric_map


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_hash": "sha256:" + "a" * 64,
        "before": {"quality": 0.7, "p95_latency_ms": 120},
        "after": {"quality": 0.8, "p95_latency_ms": 110},
        "safety_result": "pass",
        "cost_delta_microusd": -2,
        "latency_delta_ms": -10,
        "gate_pass": True,
        "judge_disagreement_count": 0,
        "idempotency_key": "skill-eval-001",
    }
    payload.update(overrides)
    return payload


def test_skill_evaluation_request_forbids_raw_report_and_invalid_hash() -> None:
    with pytest.raises(ValidationError):
        SkillEvaluationCreateRequest(**_payload(report={"prompt": "hidden"}))
    with pytest.raises(ValidationError):
        SkillEvaluationCreateRequest(**_payload(dataset_hash="dataset"))


def test_skill_evaluation_request_accepts_optional_version() -> None:
    request = SkillEvaluationCreateRequest(**_payload(skill_version_id=uuid4()))
    assert request.skill_version_id is not None
    assert request.before["quality"] == 0.7


def test_skill_evaluation_metrics_are_whitelisted_and_numeric() -> None:
    assert _metric_map({"quality": 0.8, "handoff_rate": None}) == {
        "quality": 0.8,
        "handoff_rate": None,
    }
    with pytest.raises(SkillTransitionError, match="not_allowed"):
        _metric_map({"prompt": 1})  # type: ignore[arg-type]
    with pytest.raises(SkillTransitionError, match="value_invalid"):
        _metric_map({"quality": True})  # type: ignore[dict-item]
    with pytest.raises(SkillTransitionError, match="range_invalid"):
        _metric_map({"quality": 1.1})
    with pytest.raises(SkillTransitionError, match="range_invalid"):
        _metric_map({"p95_latency_ms": -1})

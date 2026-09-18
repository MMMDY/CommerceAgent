from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.evolution.skill_registry import SkillRegistry
from src.repositories.skills import SkillTransitionError


class _FakeRepository:
    refs = ("a", "b", "c", "d", "e")

    def __init__(self, _engine: object) -> None:
        self.created: dict[str, object] | None = None

    def cluster_evidence_refs(self, *, tenant_id: str, cluster_key: str) -> tuple[str, ...]:
        del tenant_id, cluster_key
        return self.refs

    def create_candidate(self, **kwargs: Any) -> UUID:
        self.created = kwargs
        return uuid4()


def test_registry_rejects_cluster_without_five_independent_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeRepository.refs = ("a", "b", "c", "d")
    monkeypatch.setattr("src.evolution.skill_registry.SkillRepository", _FakeRepository)

    with pytest.raises(SkillTransitionError, match="distinct_evidence"):
        SkillRegistry(object()).generate_from_cluster(
            tenant_id="tenant",
            cluster_key="cluster",
            scope_type="tenant",
            scope_value="tenant",
            keywords=["模糊问题"],
            response_policy="graceful_unsupported",
            offline_gate_pass=True,
            safety_gate_pass=True,
        )


def test_registry_creates_review_only_candidate_from_bounded_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeRepository.refs = ("a", "b", "c", "d", "e")
    monkeypatch.setattr("src.evolution.skill_registry.SkillRepository", _FakeRepository)
    registry = SkillRegistry(object())

    skill_id = registry.generate_from_cluster(
        tenant_id="tenant",
        cluster_key="cluster",
        scope_type="tenant",
        scope_value="tenant",
        keywords=["夸一夸"],
        response_policy="conversational_response",
        offline_gate_pass=True,
        safety_gate_pass=True,
    )

    assert skill_id
    repository = registry._repository
    assert isinstance(repository, _FakeRepository)
    assert repository.created is not None
    assert repository.created["source_count"] == 5
    assert repository.created["provenance"] == {
        "generation": "failure_cluster",
        "cluster_key": "cluster",
        "evidence_refs": ["a", "b", "c", "d", "e"],
        "evidence_count": 5,
    }
    definition = repository.created["definition"]
    assert definition["scope"] == {"type": "tenant", "value": "tenant"}
    assert definition["positive_examples"]
    assert definition["negative_examples"]
    assert definition["allowed_decisions"] == ["respond", "finish"]
    assert definition["forbidden_tools"]
    assert definition["ttl_seconds"] == 30 * 86400


def test_global_skill_requires_project_safety_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeRepository.refs = ("a", "b", "c", "d", "e")
    monkeypatch.setattr("src.evolution.skill_registry.SkillRepository", _FakeRepository)
    with pytest.raises(SkillTransitionError, match="global_skill"):
        SkillRegistry(object()).generate_from_cluster(
            tenant_id="tenant",
            cluster_key="cluster",
            scope_type="global",
            scope_value="*",
            keywords=["夸一夸"],
            response_policy="conversational_response",
            offline_gate_pass=True,
            safety_gate_pass=True,
        )

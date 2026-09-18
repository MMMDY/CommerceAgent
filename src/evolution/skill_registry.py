"""Failure-cluster to review-only Skill candidate orchestration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Engine

from src.evolution.skill_generator import build_skill_candidate
from src.repositories.skills import SkillRepository, SkillTransitionError


class SkillRegistry:
    """Generate bounded candidates while preserving the human approval boundary."""

    def __init__(self, engine: Engine) -> None:
        self._repository = SkillRepository(engine)

    def generate_from_cluster(
        self,
        *,
        tenant_id: str,
        cluster_key: str,
        scope_type: str,
        scope_value: str,
        keywords: list[str],
        response_policy: str,
        offline_gate_pass: bool,
        safety_gate_pass: bool,
        provenance: dict[str, Any] | None = None,
        ttl_days: int = 30,
        owner: str = "tenant",
        kind: str = "experience",
    ) -> UUID:
        """Create one pending-review candidate from independent evidence only.

        ``keywords`` are expected to come from a separate bounded generator;
        this service never forwards failure summaries or user text into the
        Skill definition.  Approval, Canary and Active transitions remain
        separate explicit operations.
        """

        if scope_type == "global" and (owner != "project" or kind != "safety"):
            raise SkillTransitionError("global_skill_requires_project_safety")

        evidence_refs = self._repository.cluster_evidence_refs(
            tenant_id=tenant_id, cluster_key=cluster_key
        )
        if len(evidence_refs) < 5:
            raise SkillTransitionError("skill_generation_distinct_evidence_threshold_not_met")
        candidate = build_skill_candidate(
            cluster_key=cluster_key,
            source_count=len(evidence_refs),
            keywords=keywords,
            response_policy=response_policy,
            scope_type=scope_type,
            scope_value=scope_value,
            ttl_days=ttl_days,
        )
        candidate_provenance = {
            **(provenance or {}),
            "generation": "failure_cluster",
            "cluster_key": cluster_key,
            "evidence_refs": list(evidence_refs),
            "evidence_count": len(evidence_refs),
        }
        return self._repository.create_candidate(
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_value=scope_value,
            trigger=candidate["trigger"],
            strategy=candidate["strategy"],
            provenance=candidate_provenance,
            cluster_key=cluster_key,
            source_count=len(evidence_refs),
            offline_gate_pass=offline_gate_pass,
            safety_gate_pass=safety_gate_pass,
            owner=owner,
            kind=kind,
            definition=candidate["definition"],
            ttl_days=ttl_days,
        )


__all__ = ["SkillRegistry"]

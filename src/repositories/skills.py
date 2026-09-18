"""Persistence boundary for the human-gated experience Skill registry."""

# ruff: noqa: E501

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.evolution.skill_validator import validate_skill_definition


class SkillTransitionError(ValueError):
    """Raised when a Skill lifecycle transition is not safe or not allowed."""


class SkillRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def matching_enabled(self, *, tenant_id: str) -> bool:
        """Read the tenant kill switch; a missing row means enabled.

        The runtime calls this immediately before registry matching.  A
        control-plane/database error is intentionally raised so the caller can
        fail closed and use ordinary routing without a Skill.
        """

        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT matching_enabled FROM experience.skill_controls "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar()
        return True if row is None else bool(row)

    def matching_control(self, *, tenant_id: str) -> dict[str, object]:
        """Return the redacted control-plane state for an operator view."""

        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT tenant_id, matching_enabled, updated_by, reason_hash, updated_at "
                    "FROM experience.skill_controls WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).mappings().first()
        if row is None:
            return {
                "tenant_id": tenant_id,
                "matching_enabled": True,
                "updated_by": None,
                "reason_hash": None,
                "updated_at": None,
            }
        return dict(row)

    def set_matching_enabled(
        self, *, tenant_id: str, enabled: bool, updated_by: str, reason_hash: str
    ) -> dict[str, object]:
        """Atomically enable/disable matching for one tenant."""

        if not tenant_id or not updated_by or not reason_hash.startswith("sha256:"):
            raise ValueError("invalid_skill_control")
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "INSERT INTO experience.skill_controls "
                    "(tenant_id, matching_enabled, updated_by, reason_hash) "
                    "VALUES (:tenant_id, :enabled, :updated_by, :reason_hash) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET "
                    "matching_enabled = EXCLUDED.matching_enabled, "
                    "updated_by = EXCLUDED.updated_by, reason_hash = EXCLUDED.reason_hash, "
                    "updated_at = now() "
                    "RETURNING tenant_id, matching_enabled, updated_by, reason_hash, updated_at"
                ),
                {
                    "tenant_id": tenant_id,
                    "enabled": enabled,
                    "updated_by": updated_by,
                    "reason_hash": reason_hash,
                },
            ).mappings().one()
        return dict(row)

    def list(self, *, tenant_id: str, status: str | None = None, limit: int = 100) -> tuple[dict[str, Any], ...]:
        self.expire_due(tenant_id=tenant_id)
        limit = max(1, min(limit, 500))
        clause = "tenant_id = :tenant_id"
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        if status:
            clause += " AND status = :status"
            params["status"] = status
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT skill_id, tenant_id, owner, kind, scope_type, scope_value, trigger_json, strategy_json, "
                    "provenance_json, cluster_key, status, source_count, positive_count, negative_count, "
                    "offline_gate_pass, safety_gate_pass, review_deadline, created_at, updated_at, "
                    "evaluation_gate_pass, evaluation_safety_result, evaluation_judge_disagreement_count "
                    "FROM experience.skill_candidates c LEFT JOIN LATERAL ("
                    "SELECT gate_pass AS evaluation_gate_pass, safety_result AS evaluation_safety_result, "
                    "judge_disagreement_count AS evaluation_judge_disagreement_count "
                    "FROM experience.skill_evaluations WHERE skill_id = c.skill_id "
                    "ORDER BY created_at DESC LIMIT 1) evaluation ON TRUE WHERE " + clause +
                    " ORDER BY updated_at DESC LIMIT :limit"
                ), params
            ).mappings().all()
        return tuple(self._candidate(row) for row in rows)

    def get(self, *, tenant_id: str, skill_id: UUID) -> dict[str, Any] | None:
        self.expire_due(tenant_id=tenant_id)
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT skill_id, tenant_id, owner, kind, scope_type, scope_value, trigger_json, strategy_json, "
                    "provenance_json, cluster_key, status, source_count, positive_count, negative_count, "
                    "offline_gate_pass, safety_gate_pass, review_deadline, created_at, updated_at "
                    "FROM experience.skill_candidates WHERE tenant_id = :tenant_id AND skill_id = :skill_id"
                ), {"tenant_id": tenant_id, "skill_id": skill_id}
            ).mappings().first()
            if row is None:
                return None
            candidate = self._candidate(row)
            versions = connection.execute(
                text(
                    "SELECT skill_version_id, version_no, definition_json, definition_hash, approved_by, "
                    "approved_at, activated_at, expires_at, rollback_of, status, created_at "
                    "FROM experience.skill_versions WHERE skill_id = :skill_id ORDER BY version_no DESC"
                ), {"skill_id": skill_id}
            ).mappings().all()
            candidate["versions"] = [self._version(item) for item in versions]
            evaluations = connection.execute(
                text(
                    "SELECT evaluation_id, skill_id, skill_version_id, dataset_hash, "
                    "before_json, after_json, safety_result, cost_delta_microusd, "
                    "latency_delta_ms, gate_pass, judge_disagreement_count, created_at "
                    "FROM experience.skill_evaluations WHERE skill_id = :skill_id "
                    "ORDER BY created_at DESC LIMIT 20"
                ),
                {"skill_id": skill_id},
            ).mappings().all()
            candidate["evaluations"] = [self._evaluation(item) for item in evaluations]
        return candidate

    def record_evaluation(
        self,
        *,
        tenant_id: str,
        skill_id: UUID,
        skill_version_id: UUID | None = None,
        dataset_hash: str,
        before: dict[str, float | int | None],
        after: dict[str, float | int | None],
        safety_result: str,
        cost_delta_microusd: int | None,
        latency_delta_ms: int | None,
        gate_pass: bool,
        judge_disagreement_count: int,
    ) -> dict[str, Any]:
        """Persist only bounded paired-eval aggregates, never report rows."""

        if not dataset_hash.startswith("sha256:") or safety_result not in {
            "pass",
            "fail",
            "incomplete",
        }:
            raise SkillTransitionError("invalid_skill_evaluation")
        if judge_disagreement_count < 0 or (gate_pass and judge_disagreement_count > 0):
            raise SkillTransitionError("judge_disagreement_blocks_gate")
        before_safe = _metric_map(before)
        after_safe = _metric_map(after)
        with self._engine.begin() as connection:
            exists = connection.execute(
                text(
                    "SELECT 1 FROM experience.skill_candidates "
                    "WHERE tenant_id = :tenant_id AND skill_id = :skill_id"
                ),
                {"tenant_id": tenant_id, "skill_id": skill_id},
            ).first()
            if exists is None:
                raise SkillTransitionError("skill_not_found")
            if skill_version_id is not None:
                version_exists = connection.execute(
                    text(
                        "SELECT 1 FROM experience.skill_versions "
                        "WHERE skill_id = :skill_id AND skill_version_id = :version_id"
                    ),
                    {"skill_id": skill_id, "version_id": skill_version_id},
                ).first()
                if version_exists is None:
                    raise SkillTransitionError("skill_version_not_found")
            evaluation_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO experience.skill_evaluations "
                    "(evaluation_id, skill_id, skill_version_id, dataset_hash, before_json, after_json, "
                    "safety_result, cost_delta_microusd, latency_delta_ms, gate_pass, "
                    "judge_disagreement_count) VALUES "
                    "(:evaluation_id, :skill_id, :skill_version_id, :dataset_hash, CAST(:before AS jsonb), "
                    "CAST(:after AS jsonb), :safety_result, :cost_delta, :latency_delta, "
                    ":gate_pass, :disagreements)"
                ),
                {
                    "evaluation_id": evaluation_id,
                    "skill_id": skill_id,
                    "skill_version_id": skill_version_id,
                    "dataset_hash": dataset_hash,
                    "before": json.dumps(before_safe, ensure_ascii=False, sort_keys=True),
                    "after": json.dumps(after_safe, ensure_ascii=False, sort_keys=True),
                    "safety_result": safety_result,
                    "cost_delta": cost_delta_microusd,
                    "latency_delta": latency_delta_ms,
                    "gate_pass": gate_pass,
                    "disagreements": judge_disagreement_count,
                },
            )
        return {
            "evaluation_id": str(evaluation_id),
            "skill_id": str(skill_id),
            "skill_version_id": str(skill_version_id) if skill_version_id is not None else None,
            "dataset_hash": dataset_hash,
            "before": before_safe,
            "after": after_safe,
            "safety_result": safety_result,
            "cost_delta_microusd": cost_delta_microusd,
            "latency_delta_ms": latency_delta_ms,
            "gate_pass": gate_pass,
            "judge_disagreement_count": judge_disagreement_count,
        }

    def candidates_for_match(
        self, *, tenant_id: str, mode: str = "active", limit: int = 100
    ) -> tuple[dict[str, Any], ...]:
        """Load only non-expired versions allowed for the requested match mode."""

        self.expire_due(tenant_id=tenant_id)

        statuses = {
            "active": ("ACTIVE", "CANARY"),
            "canary": ("CANARY",),
            "shadow": ("APPROVED", "CANARY", "ACTIVE"),
        }.get(mode)
        if statuses is None:
            raise ValueError("invalid_skill_match_mode")
        limit = max(1, min(limit, 500))
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT c.skill_id, c.tenant_id, c.scope_type, c.scope_value, "
                    "c.trigger_json, c.strategy_json, c.status, v.skill_version_id, "
                    "v.definition_json, v.status AS version_status, v.expires_at "
                    "FROM experience.skill_candidates c "
                    "JOIN experience.skill_versions v ON v.skill_id = c.skill_id "
                    "WHERE c.tenant_id = :tenant_id AND c.status = ANY(:statuses) "
                    "AND v.status = c.status AND v.expires_at > now() "
                    "ORDER BY c.updated_at DESC LIMIT :limit"
                ),
                {"tenant_id": tenant_id, "statuses": list(statuses), "limit": limit},
            ).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            item["trigger"] = item.pop("trigger_json") or {}
            item["strategy"] = item.pop("strategy_json") or {}
            item["skill_id"] = str(item["skill_id"])
            item["skill_version_id"] = str(item["skill_version_id"])
            item.pop("definition_json", None)
            item.pop("version_status", None)
            result.append(item)
        return tuple(result)

    def record_match(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        skill_id: UUID,
        skill_version_id: UUID,
        match_score: float,
        mode: str,
        outcome: str | None = None,
    ) -> UUID:
        """Persist a bounded match audit record without storing request text."""

        if mode not in {"shadow", "canary", "active"} or not 0 <= match_score <= 1:
            raise ValueError("invalid_skill_match")
        with self._engine.begin() as connection:
            return UUID(str(connection.execute(
                text(
                    "INSERT INTO experience.skill_matches "
                    "(match_id, tenant_id, run_id, skill_id, skill_version_id, "
                    "match_score, mode, outcome) VALUES "
                    "(:id, :tenant_id, :run_id, :skill_id, :version_id, :score, :mode, :outcome) "
                    "RETURNING match_id"
                ),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "skill_id": skill_id,
                    "version_id": skill_version_id,
                    "score": match_score,
                    "mode": mode,
                    "outcome": outcome,
                },
            ).scalar_one()))

    def cluster_evidence_refs(
        self, *, tenant_id: str, cluster_key: str, limit: int = 500
    ) -> tuple[str, ...]:
        """Return bounded, non-text identities for independent cluster evidence."""

        limit = max(5, min(limit, 5000))
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT DISTINCT COALESCE(case_id, run_id::text, failure_id::text) AS evidence_ref "
                    "FROM evaluation.failure_cases WHERE tenant_id = :tenant_id "
                    "AND cluster_key = :cluster_key ORDER BY evidence_ref LIMIT :limit"
                ),
                {"tenant_id": tenant_id, "cluster_key": cluster_key, "limit": limit},
            ).scalars().all()
        return tuple(str(item) for item in rows if item is not None)

    def create_candidate(
        self, *, tenant_id: str, scope_type: str, scope_value: str, trigger: dict[str, Any],
        strategy: dict[str, Any], provenance: dict[str, Any], cluster_key: str,
        source_count: int, offline_gate_pass: bool, safety_gate_pass: bool,
        definition: dict[str, Any], ttl_days: int = 30,
        owner: str = "tenant", kind: str = "experience",
    ) -> UUID:
        if source_count < 5:
            raise SkillTransitionError("skill_generation_threshold_not_met")
        if not safety_gate_pass or not offline_gate_pass:
            raise SkillTransitionError("skill_gate_not_passed")
        if scope_type not in {"tenant", "route", "global"} or not scope_value:
            raise SkillTransitionError("invalid_skill_scope")
        if owner not in {"tenant", "project"} or kind not in {"experience", "safety"}:
            raise SkillTransitionError("invalid_skill_owner_or_kind")
        if scope_type == "global" and (owner != "project" or kind != "safety"):
            raise SkillTransitionError("global_skill_requires_project_safety")
        if not 1 <= ttl_days <= 90:
            raise SkillTransitionError("invalid_skill_ttl")
        valid_definition, definition_errors = validate_skill_definition(definition)
        if not valid_definition:
            raise SkillTransitionError(
                "invalid_skill_definition:" + ",".join(definition_errors)
            )
        skill_id, version_id = uuid4(), uuid4()
        definition_hash = "sha256:" + sha256(
            json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self._engine.begin() as connection:
            verified_source_count = connection.execute(
                text(
                    "SELECT count(DISTINCT COALESCE(case_id, run_id::text, failure_id::text)) "
                    "FROM evaluation.failure_cases WHERE tenant_id = :tenant_id "
                    "AND cluster_key = :cluster_key"
                ),
                {"tenant_id": tenant_id, "cluster_key": cluster_key},
            ).scalar_one()
            if int(verified_source_count or 0) < 5:
                raise SkillTransitionError("skill_generation_distinct_evidence_threshold_not_met")
            connection.execute(
                text(
                    "INSERT INTO experience.skill_candidates "
                    "(skill_id, tenant_id, owner, kind, scope_type, scope_value, trigger_json, strategy_json, provenance_json, "
                    "cluster_key, status, source_count, offline_gate_pass, safety_gate_pass, review_deadline) "
                    "VALUES (:skill_id, :tenant_id, :owner, :kind, :scope_type, :scope_value, CAST(:trigger AS jsonb), "
                    "CAST(:strategy AS jsonb), CAST(:provenance AS jsonb), :cluster_key, 'CANDIDATE', :source_count, "
                    ":offline_gate_pass, :safety_gate_pass, :review_deadline)"
                ), {"skill_id": skill_id, "tenant_id": tenant_id, "owner": owner, "kind": kind, "scope_type": scope_type,
                    "scope_value": scope_value, "trigger": json.dumps(trigger), "strategy": json.dumps(strategy),
                    "provenance": json.dumps({**provenance, "verified_source_count": int(verified_source_count)}),
                    "cluster_key": cluster_key, "source_count": int(verified_source_count),
                    "offline_gate_pass": offline_gate_pass, "safety_gate_pass": safety_gate_pass,
                    "review_deadline": datetime.now(UTC) + timedelta(days=ttl_days)}
            )
            connection.execute(
                text(
                    "INSERT INTO experience.skill_versions "
                    "(skill_version_id, skill_id, version_no, definition_json, definition_hash, expires_at, status) "
                    "VALUES (:version_id, :skill_id, 1, CAST(:definition AS jsonb), :definition_hash, :expires_at, 'PENDING_REVIEW')"
                ), {"version_id": version_id, "skill_id": skill_id, "definition": json.dumps(definition),
                    "definition_hash": definition_hash, "expires_at": datetime.now(UTC) + timedelta(days=ttl_days)}
            )
        return skill_id

    def submit_for_review(self, *, tenant_id: str, skill_id: UUID) -> dict[str, Any]:
        return self._transition(tenant_id=tenant_id, skill_id=skill_id, expected="CANDIDATE", target="PENDING_REVIEW")

    def approve(self, *, tenant_id: str, skill_id: UUID, reviewer: str) -> dict[str, Any]:
        if not reviewer:
            raise SkillTransitionError("reviewer_required")
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "UPDATE experience.skill_candidates SET status = 'APPROVED', updated_at = now() "
                    "WHERE tenant_id = :tenant_id AND skill_id = :skill_id AND status = 'PENDING_REVIEW' "
                    "AND offline_gate_pass IS TRUE AND safety_gate_pass IS TRUE "
                    "AND EXISTS (SELECT 1 FROM experience.skill_evaluations e "
                    "WHERE e.skill_id = experience.skill_candidates.skill_id "
                    "AND e.gate_pass IS TRUE AND e.safety_result = 'pass' "
                    "AND e.judge_disagreement_count = 0) RETURNING skill_id"
                ), {"tenant_id": tenant_id, "skill_id": skill_id}
            ).first()
            if row is None:
                raise SkillTransitionError("skill_not_pending_or_evaluation_gate_failed")
            connection.execute(
                text(
                    "UPDATE experience.skill_versions SET status = 'APPROVED', approved_by = :reviewer, "
                    "approved_at = now() WHERE skill_id = :skill_id AND status = 'PENDING_REVIEW'"
                ), {"skill_id": skill_id, "reviewer": reviewer}
            )
        return self.get(tenant_id=tenant_id, skill_id=skill_id) or {}

    def reject(self, *, tenant_id: str, skill_id: UUID, reviewer: str, reason: str) -> dict[str, Any]:
        if not reviewer or not reason.strip():
            raise SkillTransitionError("reviewer_and_reason_required")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE experience.skill_candidates SET status = 'REJECTED', updated_at = now(), "
                    "provenance_json = provenance_json || CAST(:reason AS jsonb) "
                    "WHERE tenant_id = :tenant_id AND skill_id = :skill_id AND status = 'PENDING_REVIEW' RETURNING skill_id"
                ), {"tenant_id": tenant_id, "skill_id": skill_id, "reason": json.dumps({"review_reason": reason[:500], "reviewer": reviewer})}
            ).first()
            if result is None:
                raise SkillTransitionError("skill_not_pending")
            connection.execute(
                text("UPDATE experience.skill_versions SET status = 'ROLLED_BACK' WHERE skill_id = :skill_id AND status IN ('PENDING_REVIEW', 'APPROVED')"),
                {"skill_id": skill_id}
            )
        return self.get(tenant_id=tenant_id, skill_id=skill_id) or {}

    def canary(self, *, tenant_id: str, skill_id: UUID) -> dict[str, Any]:
        return self._transition(tenant_id=tenant_id, skill_id=skill_id, expected="APPROVED", target="CANARY", version_target="CANARY")

    def rollback(self, *, tenant_id: str, skill_id: UUID, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise SkillTransitionError("rollback_reason_required")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE experience.skill_candidates SET status = 'ROLLED_BACK', updated_at = now() "
                    "WHERE tenant_id = :tenant_id AND skill_id = :skill_id "
                    "AND status IN ('CANARY', 'ACTIVE') RETURNING skill_id"
                ),
                {"tenant_id": tenant_id, "skill_id": skill_id},
            ).first()
            if result is None:
                raise SkillTransitionError("skill_transition_requires_canary_or_active")
            connection.execute(
                text(
                    "UPDATE experience.skill_versions SET status = 'ROLLED_BACK' "
                    "WHERE skill_id = :skill_id AND status IN ('CANARY', 'ACTIVE')"
                ),
                {"skill_id": skill_id},
            )
        return self.get(tenant_id=tenant_id, skill_id=skill_id) or {}

    def expire_due(self, *, tenant_id: str | None = None) -> int:
        """Expire review windows and versions before they can be selected."""

        clause = ""
        params: dict[str, Any] = {}
        if tenant_id is not None:
            clause = " AND c.tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        with self._engine.begin() as connection:
            versions = connection.execute(
                text(
                    "UPDATE experience.skill_versions SET status = 'EXPIRED' "
                    "WHERE expires_at <= now() AND status IN ('PENDING_REVIEW', 'APPROVED', 'CANARY', 'ACTIVE') "
                    "AND skill_id IN (SELECT skill_id FROM experience.skill_candidates c WHERE 1=1" + clause + ")"
                ),
                params,
            ).rowcount or 0
            candidates = connection.execute(
                text(
                    "UPDATE experience.skill_candidates SET status = 'EXPIRED', updated_at = now() "
                    "WHERE status IN ('CANDIDATE', 'PENDING_REVIEW') AND review_deadline <= now()"
                    + (" AND tenant_id = :tenant_id" if tenant_id is not None else "")
                ),
                params,
            ).rowcount or 0
            active_expired = connection.execute(
                text(
                    "UPDATE experience.skill_candidates c SET status = 'EXPIRED', updated_at = now() "
                    "WHERE c.status IN ('CANARY', 'ACTIVE') "
                    "AND NOT EXISTS (SELECT 1 FROM experience.skill_versions v "
                    "WHERE v.skill_id = c.skill_id AND v.status IN ('APPROVED', 'CANARY', 'ACTIVE') "
                    "AND v.expires_at > now())"
                    + (" AND c.tenant_id = :tenant_id" if tenant_id is not None else "")
                ),
                params,
            ).rowcount or 0
        return int(versions + candidates + active_expired)

    def _transition(self, *, tenant_id: str, skill_id: UUID, expected: str, target: str, version_target: str | None = None) -> dict[str, Any]:
        with self._engine.begin() as connection:
            result = connection.execute(
                text("UPDATE experience.skill_candidates SET status = :target, updated_at = now() "
                     "WHERE tenant_id = :tenant_id AND skill_id = :skill_id AND status = :expected RETURNING skill_id"),
                {"tenant_id": tenant_id, "skill_id": skill_id, "target": target, "expected": expected}
            ).first()
            if result is None:
                raise SkillTransitionError(f"skill_transition_requires_{expected.lower()}")
            if version_target:
                connection.execute(
                    text("UPDATE experience.skill_versions SET status = CAST(:target AS varchar(32)), activated_at = CASE WHEN CAST(:target AS varchar(32)) = 'CANARY' THEN now() ELSE activated_at END "
                         "WHERE skill_id = :skill_id AND status = :expected"),
                    {"skill_id": skill_id, "target": version_target, "expected": expected}
                )
        return self.get(tenant_id=tenant_id, skill_id=skill_id) or {}

    @staticmethod
    def _candidate(row: Any) -> dict[str, Any]:
        values = dict(row)
        for key in ("trigger_json", "strategy_json", "provenance_json"):
            values[key.removesuffix("_json")] = values.pop(key) or {}
        return values

    @staticmethod
    def _version(row: Any) -> dict[str, Any]:
        values = dict(row)
        values["definition"] = values.pop("definition_json") or {}
        return values

    @staticmethod
    def _evaluation(row: Any) -> dict[str, Any]:
        values = dict(row)
        values["evaluation_id"] = str(values["evaluation_id"])
        values["skill_id"] = str(values["skill_id"])
        if values.get("skill_version_id") is not None:
            values["skill_version_id"] = str(values["skill_version_id"])
        values["before"] = values.pop("before_json") or {}
        values["after"] = values.pop("after_json") or {}
        return values


def _metric_map(value: dict[str, float | int | None]) -> dict[str, float | int | None]:
    allowed = {
        "quality",
        "safety_pass_rate",
        "p95_latency_ms",
        "p95_cost_microusd",
        "handoff_rate",
    }
    if any(key not in allowed for key in value):
        raise SkillTransitionError("skill_evaluation_metric_not_allowed")
    for key, item in value.items():
        if item is None:
            continue
        if not isinstance(item, int | float) or isinstance(item, bool) or not math.isfinite(float(item)):
            raise SkillTransitionError("skill_evaluation_metric_value_invalid")
        if key in {"quality", "safety_pass_rate", "handoff_rate"} and not 0 <= float(item) <= 1:
            raise SkillTransitionError("skill_evaluation_metric_range_invalid")
        if key in {"p95_latency_ms", "p95_cost_microusd"} and float(item) < 0:
            raise SkillTransitionError("skill_evaluation_metric_range_invalid")
    return dict(value)


__all__ = ["SkillRepository", "SkillTransitionError"]

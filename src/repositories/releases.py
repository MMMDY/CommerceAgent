"""Tenant-scoped progressive delivery release records."""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.release.canary_guard import CanaryMetrics, transition_stage


class ReleaseTransitionError(ValueError):
    pass


class ReleaseRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(self, *, tenant_id: str, limit: int = 100) -> tuple[dict[str, Any], ...]:
        limit = max(1, min(limit, 500))
        with self._engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT release_id, tenant_id, owner_ref, current_version, candidate_version, stage, status, "
                "traffic_percent, observation_started_at, observation_ends_at, baseline_json, candidate_json, "
                "gates_json, stop_reason, rollback_version, created_at, updated_at FROM release.releases "
                "WHERE tenant_id = :tenant_id ORDER BY updated_at DESC LIMIT :limit"
            ), {"tenant_id": tenant_id, "limit": limit}).mappings().all()
        return tuple(self._view(row) for row in rows)

    def get(self, *, tenant_id: str, release_id: UUID) -> dict[str, Any] | None:
        with self._engine.connect() as connection:
            row = connection.execute(text(
                "SELECT release_id, tenant_id, owner_ref, current_version, candidate_version, stage, status, "
                "traffic_percent, observation_started_at, observation_ends_at, baseline_json, candidate_json, "
                "gates_json, stop_reason, rollback_version, created_at, updated_at FROM release.releases "
                "WHERE tenant_id = :tenant_id AND release_id = :release_id"
            ), {"tenant_id": tenant_id, "release_id": release_id}).mappings().first()
            if row is None:
                return None
            events = connection.execute(text(
                "SELECT event_id, event_type, actor_ref, payload_redacted_json, created_at FROM release.release_events "
                "WHERE release_id = :release_id ORDER BY created_at DESC LIMIT 100"
            ), {"release_id": release_id}).mappings().all()
            assignments = connection.execute(
                text(
                    "SELECT assignment_id, run_id, current_version, candidate_version, "
                    "selected_version, mode, bucket, traffic_percent, risk_level, risk_hint, "
                    "reason, comparison_json, created_at FROM release.release_assignments "
                    "WHERE release_id = :release_id ORDER BY created_at DESC LIMIT 100"
                ),
                {"release_id": release_id},
            ).mappings().all()
        result = self._view(row)
        result["events"] = [{**dict(event), "payload": dict(event["payload_redacted_json"] or {})} for event in events]
        for item in result["events"]:
            item.pop("payload_redacted_json", None)
        result["assignments"] = [
            {**dict(assignment), "comparison": dict(assignment["comparison_json"] or {})}
            for assignment in assignments
        ]
        for item in result["assignments"]:
            item.pop("comparison_json", None)
        return result

    def latest_active(self, *, tenant_id: str) -> dict[str, Any] | None:
        """Return the newest active release without exposing another tenant."""

        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT release_id, current_version, candidate_version, stage, status, "
                    "traffic_percent FROM release.releases WHERE tenant_id = :tenant_id "
                    "AND status = 'ACTIVE' ORDER BY updated_at DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id},
            ).mappings().first()
        return dict(row) if row is not None else None

    def runtime_available(self, *, tenant_id: str, version: str) -> bool:
        """Return whether an executable, tenant-scoped runtime is active."""

        with self._engine.connect() as connection:
            return bool(
                connection.execute(
                    text(
                        "SELECT 1 FROM release.runtime_registrations "
                        "WHERE tenant_id = :tenant_id AND version = :version "
                        "AND status = 'ACTIVE'"
                    ),
                    {"tenant_id": tenant_id, "version": version},
                ).first()
            )

    def register_runtime(
        self,
        *,
        tenant_id: str,
        version: str,
        runtime_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register or reactivate the same immutable runtime definition."""

        if not version or not runtime_hash:
            raise ValueError("runtime_identity_required")
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT registration_id, runtime_hash FROM release.runtime_registrations "
                    "WHERE tenant_id = :tenant_id AND version = :version FOR UPDATE"
                ),
                {"tenant_id": tenant_id, "version": version},
            ).mappings().first()
            if existing is not None:
                if existing["runtime_hash"] != runtime_hash:
                    raise ReleaseTransitionError("runtime_definition_conflict")
                connection.execute(
                    text(
                        "UPDATE release.runtime_registrations SET status = 'ACTIVE', "
                        "retired_at = NULL, metadata_redacted_json = CAST(:metadata AS jsonb) "
                        "WHERE registration_id = :registration_id"
                    ),
                    {
                        "registration_id": existing["registration_id"],
                        "metadata": json.dumps(metadata or {}),
                    },
                )
                registration_id = existing["registration_id"]
            else:
                registration_id = uuid4()
                connection.execute(
                    text(
                        "INSERT INTO release.runtime_registrations "
                        "(registration_id, tenant_id, version, runtime_hash, status, "
                        "metadata_redacted_json) VALUES (:id, :tenant_id, :version, "
                        ":runtime_hash, 'ACTIVE', CAST(:metadata AS jsonb))"
                    ),
                    {
                        "id": registration_id,
                        "tenant_id": tenant_id,
                        "version": version,
                        "runtime_hash": runtime_hash,
                        "metadata": json.dumps(metadata or {}),
                    },
                )
        return {
            "registration_id": registration_id,
            "tenant_id": tenant_id,
            "version": version,
            "runtime_hash": runtime_hash,
            "status": "ACTIVE",
            "metadata": metadata or {},
        }

    def due_for_evaluation(self, *, tenant_id: str) -> tuple[dict[str, Any], ...]:
        """Return active releases whose observation window has elapsed.

        The query is intentionally tenant-scoped and lets PostgreSQL provide
        the clock used by the state transition.  A scheduler may call this
        repeatedly; the repository transition still locks the row before it
        changes a stage.
        """

        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT release_id, tenant_id, stage, status, observation_ends_at "
                    "FROM release.releases WHERE tenant_id = :tenant_id "
                    "AND status = 'ACTIVE' AND (observation_ends_at IS NULL "
                    "OR observation_ends_at <= now()) ORDER BY updated_at, release_id"
                ),
                {"tenant_id": tenant_id},
            ).mappings().all()
        return tuple(dict(row) for row in rows)

    def canary_metrics(self, *, tenant_id: str, release_id: UUID) -> CanaryMetrics:
        """Build guarded metrics from candidate/shadow assignment evidence.

        Current-version fallbacks are deliberately excluded.  If a candidate
        runtime is unavailable, the resulting zero coverage causes the
        fail-closed guard to stop instead of promoting an untested release.
        Baselines are read only from the immutable release gate configuration.
        """

        with self._engine.connect() as connection:
            release = connection.execute(
                text(
                    "SELECT observation_started_at, gates_json FROM release.releases "
                    "WHERE tenant_id = :tenant_id AND release_id = :release_id"
                ),
                {"tenant_id": tenant_id, "release_id": release_id},
            ).mappings().first()
            if release is None:
                raise ReleaseTransitionError("release_not_found")
            aggregate = connection.execute(
                text(
                    "WITH candidate_runs AS ("
                    " SELECT DISTINCT assignment.run_id FROM release.release_assignments assignment "
                    " WHERE assignment.tenant_id = :tenant_id AND assignment.release_id = :release_id "
                    " AND assignment.mode IN ('shadow', 'canary') "
                    " AND assignment.created_at >= COALESCE(:started, now() - interval '24 hours')"
                    ") SELECT count(*)::bigint AS run_count, "
                    "count(*) FILTER (WHERE run.status = 'completed')::bigint AS completed_count, "
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY "
                    "EXTRACT(EPOCH FROM (run.response_published_at - run.accepted_at)) * 1000) "
                    "FILTER (WHERE run.accepted_at IS NOT NULL AND run.response_published_at IS NOT NULL) "
                    "AS p95_e2e_ms, percentile_cont(0.99) WITHIN GROUP (ORDER BY "
                    "EXTRACT(EPOCH FROM (run.response_published_at - run.accepted_at)) * 1000) "
                    "FILTER (WHERE run.accepted_at IS NOT NULL AND run.response_published_at IS NOT NULL) "
                    "AS p99_e2e_ms, percentile_cont(0.95) WITHIN GROUP "
                    "(ORDER BY run.total_cost_microusd) FILTER (WHERE run.total_cost_microusd IS NOT NULL) "
                    "AS p95_cost_microusd FROM candidate_runs candidate "
                    "JOIN runtime.agent_runs run ON run.run_id = candidate.run_id "
                    "AND run.tenant_id = :tenant_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "release_id": release_id,
                    "started": release["observation_started_at"],
                },
            ).mappings().one()
            published = connection.execute(
                text(
                    "SELECT count(DISTINCT event.run_id)::bigint AS published_count "
                    "FROM release.release_assignments assignment "
                    "JOIN runtime.run_events event ON event.run_id = assignment.run_id "
                    "JOIN runtime.agent_runs run ON run.run_id = assignment.run_id "
                    "AND run.tenant_id = assignment.tenant_id "
                    "WHERE assignment.tenant_id = :tenant_id AND assignment.release_id = :release_id "
                    "AND assignment.mode IN ('shadow', 'canary') "
                    "AND assignment.created_at >= COALESCE(:started, now() - interval '24 hours') "
                    "AND event.event_type = 'terminal_response_published'"
                ),
                {
                    "tenant_id": tenant_id,
                    "release_id": release_id,
                    "started": release["observation_started_at"],
                },
            ).mappings().one()
            p0 = connection.execute(
                text(
                    "SELECT count(*)::bigint AS p0_events FROM runtime.run_events event "
                    "JOIN release.release_assignments assignment ON assignment.run_id = event.run_id "
                    "AND assignment.release_id = :release_id AND assignment.tenant_id = :tenant_id "
                    "AND assignment.mode IN ('shadow', 'canary') "
                    "AND assignment.created_at >= COALESCE(:started, now() - interval '24 hours') "
                    "WHERE event.event_type = 'safety_routed' "
                    "AND event.payload_json->>'risk_level' = 'high' "
                    "AND event.payload_json->>'disposition' = 'continue'"
                ),
                {
                    "tenant_id": tenant_id,
                    "release_id": release_id,
                    "started": release["observation_started_at"],
                },
            ).scalar_one()
            handoff = connection.execute(
                text(
                    "WITH candidate_runs AS (SELECT DISTINCT run_id FROM release.release_assignments "
                    "WHERE tenant_id = :tenant_id AND release_id = :release_id "
                    "AND mode IN ('shadow', 'canary') AND risk_level = 'low' "
                    "AND created_at >= COALESCE(:started, now() - interval '24 hours')) "
                    "SELECT count(DISTINCT candidate_runs.run_id) FILTER "
                    "(WHERE event.event_type = 'handoff_created')::bigint AS handoff_count, "
                    "count(DISTINCT candidate_runs.run_id)::bigint AS event_count FROM candidate_runs "
                    "LEFT JOIN runtime.run_events event ON event.run_id = candidate_runs.run_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "release_id": release_id,
                    "started": release["observation_started_at"],
                },
            ).mappings().one()

        run_count = int(aggregate["run_count"] or 0)
        raw_gates = release["gates_json"]
        gates: dict[str, Any] = raw_gates if isinstance(raw_gates, dict) else {}
        raw_baseline = gates.get("baseline")
        baseline: dict[str, Any] = (
            raw_baseline if isinstance(raw_baseline, dict) else gates
        )
        handoff_count = int(handoff["handoff_count"] or 0)
        event_count = int(handoff["event_count"] or 0)
        configured_quality_gate = gates.get("quality_gate_pass")
        quality_gate_pass = (
            configured_quality_gate
            if isinstance(configured_quality_gate, bool)
            else None
        )
        configured_safety_gate = gates.get("safety_gate_pass")
        safety_gate_pass: bool | None
        if isinstance(configured_safety_gate, bool):
            safety_gate_pass = configured_safety_gate
        else:
            # Runtime events alone cannot prove the complete independent
            # safety evaluation.  A P0 event is an explicit failure; absence
            # of the independent Gate remains incomplete.
            safety_gate_pass = False if int(p0 or 0) > 0 else None
        return CanaryMetrics(
            p0_events=int(p0 or 0),
            quality_gate_pass=quality_gate_pass,
            safety_gate_pass=safety_gate_pass,
            terminal_response_coverage=(
                float(published["published_count"] or 0) / run_count if run_count else 0.0
            ),
            p95_e2e_ms=_number(aggregate["p95_e2e_ms"]),
            baseline_p95_e2e_ms=_number(baseline.get("p95_e2e_ms")),
            p99_e2e_ms=_number(aggregate["p99_e2e_ms"]),
            baseline_p99_e2e_ms=_number(baseline.get("p99_e2e_ms")),
            p95_cost_microusd=_number(aggregate["p95_cost_microusd"]),
            baseline_p95_cost_microusd=_number(baseline.get("p95_cost_microusd")),
            low_risk_handoff_rate=handoff_count / event_count if event_count else 0.0,
            baseline_low_risk_handoff_rate=_number(baseline.get("low_risk_handoff_rate")),
        )

    def record_assignment(
        self,
        *,
        tenant_id: str,
        release_id: UUID,
        run_id: UUID,
        actor_id: str,
        conversation_id: UUID,
        assignment: Any,
        risk_level: str,
        risk_hint: str,
        comparison: dict[str, Any] | None = None,
    ) -> UUID:
        """Persist one assignment per release/Run without storing raw identities."""

        actor_hash = _hash_identity(actor_id)
        conversation_hash = _hash_identity(str(conversation_id))
        with self._engine.begin() as connection:
            owned = connection.execute(
                text(
                    "SELECT 1 FROM release.releases WHERE release_id = :release_id "
                    "AND tenant_id = :tenant_id AND EXISTS ("
                    "SELECT 1 FROM runtime.agent_runs WHERE run_id = :run_id "
                    "AND tenant_id = :tenant_id)"
                ),
                {"release_id": release_id, "run_id": run_id, "tenant_id": tenant_id},
            ).first()
            if owned is None:
                raise ReleaseTransitionError("release_or_run_not_owned")
            row = connection.execute(
                text(
                    "INSERT INTO release.release_assignments "
                    "(assignment_id, release_id, tenant_id, run_id, actor_key_hash, "
                    "conversation_key_hash, current_version, candidate_version, selected_version, "
                    "mode, bucket, traffic_percent, risk_level, risk_hint, reason, comparison_json) "
                    "VALUES (:assignment_id, :release_id, :tenant_id, :run_id, :actor_hash, "
                    ":conversation_hash, :current_version, :candidate_version, :selected_version, "
                    ":mode, :bucket, :traffic_percent, :risk_level, :risk_hint, :reason, "
                    "CAST(:comparison AS jsonb)) ON CONFLICT (release_id, run_id) DO UPDATE SET "
                    "comparison_json = CASE WHEN :comparison_provided THEN EXCLUDED.comparison_json "
                    "ELSE release.release_assignments.comparison_json END "
                    "RETURNING assignment_id"
                ),
                {
                    "assignment_id": uuid4(),
                    "release_id": release_id,
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "actor_hash": actor_hash,
                    "conversation_hash": conversation_hash,
                    "current_version": assignment.current_version,
                    "candidate_version": assignment.candidate_version,
                    "selected_version": assignment.selected_version,
                    "mode": assignment.mode,
                    "bucket": assignment.bucket,
                    "traffic_percent": assignment.traffic_percent,
                    "risk_level": risk_level,
                    "risk_hint": risk_hint,
                    "reason": assignment.reason[:128],
                    "comparison": json.dumps(comparison or {}),
                    "comparison_provided": comparison is not None,
                },
            ).first()
            if row is not None:
                return UUID(str(row[0]))
            existing = connection.execute(
                text(
                    "SELECT assignment_id FROM release.release_assignments "
                    "WHERE release_id = :release_id AND run_id = :run_id"
                ),
                {"release_id": release_id, "run_id": run_id},
            ).scalar_one()
        return UUID(str(existing))

    def create(self, *, tenant_id: str, owner_ref: str, current_version: str, candidate_version: str, gates: dict[str, Any]) -> dict[str, Any]:
        release_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO release.releases (release_id, tenant_id, owner_ref, current_version, candidate_version, "
                "stage, status, traffic_percent, observation_started_at, observation_ends_at, gates_json) "
                "VALUES (:id, :tenant_id, :owner, :current, :candidate, 'SHADOW', 'ACTIVE', 0, now(), :ends, CAST(:gates AS jsonb))"
            ), {"id": release_id, "tenant_id": tenant_id, "owner": owner_ref, "current": current_version,
                "candidate": candidate_version, "ends": datetime.now(UTC) + timedelta(hours=24), "gates": json.dumps(gates)})
            self._event(connection, release_id, "created", owner_ref, {"stage": "SHADOW", "traffic_percent": 0})
        return self.get(tenant_id=tenant_id, release_id=release_id) or {}

    def stop(self, *, tenant_id: str, release_id: UUID, actor_ref: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ReleaseTransitionError("stop_reason_required")
        with self._engine.begin() as connection:
            result = connection.execute(text(
                "UPDATE release.releases SET stage = 'STOPPED', status = 'STOPPED', traffic_percent = 0, "
                "stop_reason = :reason, updated_at = now() WHERE tenant_id = :tenant_id AND release_id = :id "
                "AND status = 'ACTIVE' RETURNING release_id"
            ), {"tenant_id": tenant_id, "id": release_id, "reason": reason[:128]}).first()
            if result is None:
                raise ReleaseTransitionError("release_not_active")
            self._event(connection, release_id, "stopped", actor_ref, {"reason": reason[:128]})
        return self.get(tenant_id=tenant_id, release_id=release_id) or {}

    def evaluate_and_advance(
        self,
        *,
        tenant_id: str,
        release_id: UUID,
        actor_ref: str,
        metrics: CanaryMetrics,
    ) -> dict[str, Any]:
        """Persist one guarded stage decision; no transition skips a stage."""

        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT stage, status, current_version, observation_ends_at "
                    "FROM release.releases "
                    "WHERE tenant_id = :tenant_id AND release_id = :release_id FOR UPDATE"
                ),
                {"tenant_id": tenant_id, "release_id": release_id},
            ).mappings().first()
            if row is None:
                raise ReleaseTransitionError("release_not_found")
            if row["status"] != "ACTIVE":
                raise ReleaseTransitionError("release_not_active")
            candidate_available = connection.execute(
                text(
                    "SELECT 1 FROM release.runtime_registrations registration "
                    "WHERE registration.tenant_id = :tenant_id "
                    "AND registration.version = (SELECT candidate_version FROM release.releases "
                    "WHERE release_id = :release_id) AND registration.status = 'ACTIVE'"
                ),
                {"tenant_id": tenant_id, "release_id": release_id},
            ).first()
            if candidate_available is None:
                raise ReleaseTransitionError("candidate_runtime_unavailable")
            if row["observation_ends_at"] is not None and row["observation_ends_at"] > datetime.now(UTC):
                raise ReleaseTransitionError("observation_window_not_finished")
            transition = transition_stage(
                current_stage=str(row["stage"]),
                current_version=str(row["current_version"]),
                metrics=metrics,
            )
            observation_started_at = None
            observation_ends_at = None
            if transition.status == "ACTIVE" and transition.stage != "FULL":
                observation_started_at = datetime.now(UTC)
                observation_ends_at = observation_started_at + timedelta(hours=24)
            elif transition.status == "COMPLETED":
                observation_started_at = datetime.now(UTC)
            connection.execute(
                text(
                    "UPDATE release.releases SET stage = :stage, status = :status, "
                    "traffic_percent = :traffic, rollback_version = :rollback, "
                    "stop_reason = :reason, observation_started_at = COALESCE(:started, observation_started_at), "
                    "observation_ends_at = :ends, updated_at = now() "
                    "WHERE tenant_id = :tenant_id AND release_id = :release_id"
                ),
                {
                    "stage": transition.stage,
                    "status": transition.status,
                    "traffic": transition.traffic_percent,
                    "rollback": transition.rollback_version,
                    "reason": ",".join(transition.reasons)[:128] or None,
                    "started": observation_started_at,
                    "ends": observation_ends_at,
                    "tenant_id": tenant_id,
                    "release_id": release_id,
                },
            )
            self._event(
                connection,
                release_id,
                "stage_evaluated",
                actor_ref,
                {
                    "stage": transition.stage,
                    "status": transition.status,
                    "traffic_percent": transition.traffic_percent,
                    "reasons": list(transition.reasons),
                },
            )
        return self.get(tenant_id=tenant_id, release_id=release_id) or {}

    @staticmethod
    def _event(connection: Any, release_id: UUID, event_type: str, actor_ref: str, payload: dict[str, Any]) -> None:
        connection.execute(text(
            "INSERT INTO release.release_events (event_id, release_id, event_type, actor_ref, payload_redacted_json) "
            "VALUES (:id, :release_id, :event_type, :actor_ref, CAST(:payload AS jsonb))"
        ), {"id": uuid4(), "release_id": release_id, "event_type": event_type, "actor_ref": actor_ref, "payload": json.dumps(payload)})

    @staticmethod
    def _view(row: Any) -> dict[str, Any]:
        values = dict(row)
        for key in ("baseline_json", "candidate_json", "gates_json"):
            values[key.removesuffix("_json")] = values.pop(key) or {}
        return values


__all__ = ["ReleaseRepository", "ReleaseTransitionError"]


def _hash_identity(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None

"""Tenant-scoped failure cases and attribution evidence."""

# ruff: noqa: E501

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.evolution.contracts import FailureCaseView
from src.evolution.redaction import redact_text


class FailureRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record_signal(
        self, *, tenant_id: str, signal: str, severity: str, source: str,
        run_id: UUID | None, cluster_key: str, summary_redacted: str,
        trace_refs: tuple[str, ...] = (), case_id: str | None = None,
        eval_run_id: UUID | None = None,
    ) -> FailureCaseView:
        if len(summary_redacted) > 2000 or len(trace_refs) > 64:
            raise ValueError("failure evidence exceeds bound")
        with self._engine.begin() as connection:
            if run_id is not None:
                signal_record = json.dumps(({
                    "signal": signal,
                    "severity": severity,
                    "source": source,
                    "reason": summary_redacted[:256],
                },))
                row = connection.execute(
                    text(
                        "INSERT INTO evaluation.failure_cases "
                        "(failure_id, tenant_id, signal, severity, source, run_id, eval_run_id, case_id, "
                        "trace_refs, signals_json, cluster_key, summary_redacted) VALUES "
                        "(:failure_id, :tenant_id, :signal, :severity, :source, :run_id, :eval_run_id, :case_id, "
                        "CAST(:trace_refs AS jsonb), CAST(:signals AS jsonb), :cluster_key, :summary) "
                        "ON CONFLICT (tenant_id, run_id, cluster_key) WHERE run_id IS NOT NULL DO UPDATE SET "
                        # A run-bound failure case is unique per (tenant, run,
                        # cluster). Repeated signals from the same Run must
                        # not inflate the independent-source count; the
                        # merged signals_json retains the extra observations.
                        "source_count = GREATEST(evaluation.failure_cases.source_count, 1), "
                        "signal = EXCLUDED.signal, severity = EXCLUDED.severity, source = EXCLUDED.source, "
                        "trace_refs = (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb) "
                        "FROM jsonb_array_elements(evaluation.failure_cases.trace_refs || EXCLUDED.trace_refs) AS item), "
                        "signals_json = (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb) "
                        "FROM jsonb_array_elements(evaluation.failure_cases.signals_json || EXCLUDED.signals_json) AS item), "
                        "updated_at = now() RETURNING failure_id"
                    ),
                    {"failure_id": uuid4(), "tenant_id": tenant_id, "signal": signal, "severity": severity,
                     "source": source, "run_id": run_id, "eval_run_id": eval_run_id, "case_id": case_id,
                     "trace_refs": json.dumps(trace_refs), "signals": signal_record,
                     "cluster_key": cluster_key, "summary": summary_redacted},
                ).one()
                failure_id = row[0]
            else:
                failure_id = uuid4()
                connection.execute(
                    text(
                        "INSERT INTO evaluation.failure_cases "
                        "(failure_id, tenant_id, signal, severity, source, eval_run_id, case_id, trace_refs, signals_json, cluster_key, summary_redacted) "
                        "VALUES (:failure_id, :tenant_id, :signal, :severity, :source, :eval_run_id, :case_id, "
                        "CAST(:trace_refs AS jsonb), CAST(:signals AS jsonb), :cluster_key, :summary)"
                    ),
                    {"failure_id": failure_id, "tenant_id": tenant_id, "signal": signal, "severity": severity,
                     "source": source, "eval_run_id": eval_run_id, "case_id": case_id,
                     "trace_refs": json.dumps(trace_refs), "signals": json.dumps(({
                         "signal": signal, "severity": severity, "source": source,
                         "reason": summary_redacted[:256],
                     },)), "cluster_key": cluster_key, "summary": summary_redacted},
                )
        return self.get(tenant_id=tenant_id, failure_id=failure_id)  # type: ignore[return-value]

    def list(self, *, tenant_id: str, limit: int = 100, status: str | None = None) -> tuple[FailureCaseView, ...]:
        limit = max(1, min(limit, 500))
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        clause = "tenant_id = :tenant_id"
        if status:
            clause += " AND status = :status"
            params["status"] = status
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT failure_id, tenant_id, signal, severity, source, run_id, eval_run_id, case_id, "
                    "trace_refs, signals_json, status, cluster_key, summary_redacted, source_count, created_at, updated_at, "
                    "(SELECT jsonb_build_object('deterministic_category', deterministic_category, "
                    "'llm_category', llm_category, 'confidence', confidence, 'review_status', review_status, "
                    "'reviewed_category', reviewed_category, 'reviewed_by', reviewed_by, "
                    "'reviewed_at', reviewed_at, 'review_note_redacted', review_note_redacted, "
                    "'evidence_refs', evidence_refs, 'rationale_redacted', rationale_redacted) "
                    "FROM evaluation.failure_attributions WHERE failure_id = failure_cases.failure_id "
                    "ORDER BY created_at DESC LIMIT 1) AS attribution_json "
                    "FROM evaluation.failure_cases WHERE " + clause + " ORDER BY updated_at DESC LIMIT :limit"
                ), params
            ).mappings().all()
        return tuple(self._view(row) for row in rows)

    def summary(self, *, tenant_id: str, window_days: int = 30, limit: int = 10) -> dict[str, object]:
        """Return bounded aggregate failure telemetry without failure text."""

        if not 1 <= window_days <= 90:
            raise ValueError("window_days must be between 1 and 90")
        limit = max(1, min(limit, 50))
        params = {"tenant_id": tenant_id, "window_days": window_days, "limit": limit}
        with self._engine.connect() as connection:
            clusters = connection.execute(
                text(
                    "SELECT cluster_key, count(*)::bigint AS case_count, "
                    "max(source_count)::bigint AS max_source_count "
                    "FROM evaluation.failure_cases "
                    "WHERE tenant_id = :tenant_id "
                    "AND created_at >= now() - make_interval(days => :window_days) "
                    "GROUP BY cluster_key ORDER BY case_count DESC, cluster_key LIMIT :limit"
                ),
                params,
            ).mappings().all()
            taxonomy = connection.execute(
                text(
                    "SELECT COALESCE(latest.deterministic_category, 'unattributed') AS category, "
                    "count(*)::bigint AS case_count "
                    "FROM evaluation.failure_cases AS failure "
                    "LEFT JOIN LATERAL ("
                    "SELECT deterministic_category FROM evaluation.failure_attributions "
                    "WHERE failure_id = failure.failure_id ORDER BY created_at DESC LIMIT 1"
                    ") AS latest ON TRUE "
                    "WHERE failure.tenant_id = :tenant_id "
                    "AND failure.created_at >= now() - make_interval(days => :window_days) "
                    "GROUP BY category ORDER BY case_count DESC, category"
                ),
                params,
            ).mappings().all()
            severities = connection.execute(
                text(
                    "SELECT severity, count(*)::bigint AS case_count "
                    "FROM evaluation.failure_cases WHERE tenant_id = :tenant_id "
                    "AND created_at >= now() - make_interval(days => :window_days) "
                    "GROUP BY severity ORDER BY severity"
                ),
                params,
            ).mappings().all()
            statuses = connection.execute(
                text(
                    "SELECT status, count(*)::bigint AS case_count "
                    "FROM evaluation.failure_cases WHERE tenant_id = :tenant_id "
                    "AND created_at >= now() - make_interval(days => :window_days) "
                    "GROUP BY status ORDER BY status"
                ),
                params,
            ).mappings().all()
            trend = connection.execute(
                text(
                    "SELECT date_trunc('day', created_at) AS bucket, "
                    "count(*)::bigint AS case_count, "
                    "count(*) FILTER (WHERE severity IN ('p0', 'p1'))::bigint AS critical_count, "
                    "count(*) FILTER (WHERE status = 'reviewed')::bigint AS reviewed_count "
                    "FROM evaluation.failure_cases WHERE tenant_id = :tenant_id "
                    "AND created_at >= now() - make_interval(days => :window_days) "
                    "GROUP BY bucket ORDER BY bucket"
                ),
                params,
            ).mappings().all()
        return {
            "window_days": window_days,
            "top_clusters": [dict(row) for row in clusters],
            "taxonomy": [dict(row) for row in taxonomy],
            "severity": [dict(row) for row in severities],
            "status": [dict(row) for row in statuses],
            "trend": [
                {
                    **dict(row),
                    "bucket": row["bucket"].isoformat(),
                }
                for row in trend
            ],
        }

    def learning_summary(
        self, *, tenant_id: str, window_days: int = 30, limit: int = 25
    ) -> dict[str, object]:
        """Build the auditable failure-learning chain for the operations UI.

        This is intentionally a read model, not a browser-side join.  Every
        edge is derived from tenant-scoped rows: failure clusters come from
        ``failure_cases``, attribution from the latest attribution row, Skill
        candidates from their persisted cluster key, and Release links only
        when a release assignment explicitly recorded the candidate Skill (or
        its immutable version id).  Missing edges stay missing rather than
        being inferred from the fact that a page exists.
        """

        if not 1 <= window_days <= 90:
            raise ValueError("window_days must be between 1 and 90")
        limit = max(1, min(limit, 100))
        params = {"tenant_id": tenant_id, "window_days": window_days, "limit": limit}
        with self._engine.connect() as connection:
            clusters = connection.execute(
                text(
                    "WITH latest_attribution AS ("
                    " SELECT DISTINCT ON (failure_id) failure_id, deterministic_category, "
                    " review_status FROM evaluation.failure_attributions "
                    " ORDER BY failure_id, created_at DESC), grouped AS ("
                    " SELECT failure.cluster_key, count(*)::bigint AS case_count, "
                    " max(failure.source_count)::bigint AS max_source_count, "
                    " count(DISTINCT COALESCE(failure.case_id, failure.run_id::text, "
                    " failure.failure_id::text))::bigint AS evidence_count, "
                    " count(latest.failure_id)::bigint AS attributed_case_count, "
                    " count(latest.failure_id) FILTER (WHERE latest.review_status IN "
                    " ('reviewed', 'verified', 'approved'))::bigint AS reviewed_case_count, "
                    " min(failure.failure_id::text) AS representative_failure_id "
                    " FROM evaluation.failure_cases AS failure LEFT JOIN latest_attribution latest "
                    " ON latest.failure_id = failure.failure_id "
                    " WHERE failure.tenant_id = :tenant_id AND failure.created_at >= "
                    " now() - make_interval(days => :window_days) "
                    " GROUP BY failure.cluster_key ORDER BY case_count DESC, failure.cluster_key "
                    " LIMIT :limit) SELECT grouped.*, latest.deterministic_category AS latest_category "
                    " FROM grouped LEFT JOIN LATERAL ("
                    " SELECT attribution.deterministic_category FROM evaluation.failure_cases failure "
                    " JOIN evaluation.failure_attributions attribution ON attribution.failure_id = failure.failure_id "
                    " WHERE failure.tenant_id = :tenant_id AND failure.cluster_key = grouped.cluster_key "
                    " ORDER BY attribution.created_at DESC LIMIT 1) latest ON TRUE"
                ),
                params,
            ).mappings().all()
            skills = connection.execute(
                text(
                    "SELECT skill_id::text AS skill_id, cluster_key, status, source_count, "
                    " offline_gate_pass, safety_gate_pass, review_deadline, updated_at "
                    " FROM experience.skill_candidates WHERE tenant_id = :tenant_id "
                    " AND updated_at >= now() - make_interval(days => :window_days) "
                    " ORDER BY updated_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
            versions = connection.execute(
                text(
                    "SELECT skill_id::text AS skill_id, skill_version_id::text AS skill_version_id "
                    " FROM experience.skill_versions WHERE skill_id IN ("
                    " SELECT skill_id FROM experience.skill_candidates WHERE tenant_id = :tenant_id)"
                ),
                {"tenant_id": tenant_id},
            ).mappings().all()
            releases = connection.execute(
                text(
                    "SELECT release_id::text AS release_id, current_version, candidate_version, "
                    " stage, status, traffic_percent, stop_reason, rollback_version, updated_at "
                    " FROM release.releases WHERE tenant_id = :tenant_id "
                    " AND updated_at >= now() - make_interval(days => :window_days) "
                    " ORDER BY updated_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
            assignment_links = connection.execute(
                text(
                    "SELECT DISTINCT release_id::text AS release_id, "
                    " comparison_json->>'candidate_skill' AS candidate_skill "
                    " FROM release.release_assignments WHERE tenant_id = :tenant_id "
                    " AND created_at >= now() - make_interval(days => :window_days) "
                    " AND comparison_json ? 'candidate_skill'"
                ),
                params,
            ).mappings().all()

        version_ids: dict[str, set[str]] = {}
        for row in versions:
            version_ids.setdefault(str(row["skill_id"]), set()).add(str(row["skill_version_id"]))
        release_by_id = {str(row["release_id"]): dict(row) for row in releases}
        release_links: dict[str, list[dict[str, object]]] = {}
        for row in assignment_links:
            release = release_by_id.get(str(row["release_id"]))
            candidate_skill = row.get("candidate_skill")
            if release is None or not candidate_skill:
                continue
            release_links.setdefault(str(candidate_skill), []).append(
                {
                    "release_id": str(release["release_id"]),
                    "stage": release["stage"],
                    "status": release["status"],
                    "candidate_version": release["candidate_version"],
                    "traffic_percent": int(release["traffic_percent"]),
                    "stop_reason": release["stop_reason"],
                    "rollback_version": release["rollback_version"],
                    "updated_at": release["updated_at"].isoformat(),
                }
            )
        # A release may identify the Skill by its candidate runtime version
        # rather than by an assignment comparison.  Only exact immutable ids
        # are accepted here; free-text names are never treated as a link.
        for skill_id in version_ids:
            release_links.setdefault(skill_id, [])
            for release_row in releases:
                if str(release_row["candidate_version"]) == skill_id or str(
                    release_row["candidate_version"]
                ) in version_ids[skill_id]:
                    release_links[skill_id].append(
                        {
                            "release_id": str(release_row["release_id"]),
                            "stage": release_row["stage"],
                            "status": release_row["status"],
                            "candidate_version": release_row["candidate_version"],
                            "traffic_percent": int(release_row["traffic_percent"]),
                            "stop_reason": release_row["stop_reason"],
                            "rollback_version": release_row["rollback_version"],
                            "updated_at": release_row["updated_at"].isoformat(),
                        }
                    )

        skills_by_cluster: dict[str, list[dict[str, object]]] = {}
        for row in skills:
            skill_id = str(row["skill_id"])
            links = release_links.get(skill_id, [])
            # De-duplicate an exact release link if both candidate_version and
            # assignment comparison identify the same immutable Skill.
            unique_links = {str(item["release_id"]): item for item in links}
            skill = {
                "skill_id": skill_id,
                "cluster_key": row["cluster_key"],
                "status": row["status"],
                "source_count": int(row["source_count"]),
                "offline_gate_pass": bool(row["offline_gate_pass"]),
                "safety_gate_pass": bool(row["safety_gate_pass"]),
                "review_deadline": row["review_deadline"].isoformat()
                if row["review_deadline"]
                else None,
                "updated_at": row["updated_at"].isoformat(),
                "releases": list(unique_links.values()),
            }
            skills_by_cluster.setdefault(str(row["cluster_key"]), []).append(skill)

        cluster_rows: list[dict[str, object]] = []
        for row in clusters:
            cluster_key = str(row["cluster_key"])
            cluster_rows.append(
                {
                    "cluster_key": cluster_key,
                    "case_count": int(row["case_count"]),
                    "max_source_count": int(row["max_source_count"] or 0),
                    "evidence_count": int(row["evidence_count"]),
                    "attributed_case_count": int(row["attributed_case_count"]),
                    "reviewed_case_count": int(row["reviewed_case_count"]),
                    "latest_category": row["latest_category"],
                    "representative_failure_id": row["representative_failure_id"],
                    "skills": skills_by_cluster.get(cluster_key, []),
                }
            )

        skill_rows = [skill for skills_for_cluster in skills_by_cluster.values() for skill in skills_for_cluster]
        release_rows = list(release_by_id.values())
        attributed = sum(
            int(cast(int, row["attributed_case_count"])) for row in cluster_rows
        )
        reviewed = sum(int(cast(int, row["reviewed_case_count"])) for row in cluster_rows)
        return {
            "window_days": window_days,
            "clusters": cluster_rows,
            "stages": {
                "signals": {
                    "case_count": sum(int(cast(int, row["case_count"])) for row in cluster_rows),
                    "cluster_count": len(cluster_rows),
                },
                "clusters": {
                    "cluster_count": len(cluster_rows),
                    "eligible_count": sum(
                        1 for row in cluster_rows if cast(int, row["evidence_count"]) >= 5
                    ),
                },
                "attribution": {
                    "attributed_case_count": attributed,
                    "reviewed_case_count": reviewed,
                    "pending_case_count": max(0, attributed - reviewed),
                },
                "skills": {
                    "candidate_count": len(skill_rows),
                    "pending_review_count": sum(
                        1 for row in skill_rows if row["status"] == "PENDING_REVIEW"
                    ),
                    "approved_count": sum(
                        1
                        for row in skill_rows
                        if row["status"] in {"APPROVED", "CANARY", "ACTIVE"}
                    ),
                    "blocked_count": sum(
                        1
                        for row in skill_rows
                        if not row["offline_gate_pass"] or not row["safety_gate_pass"]
                    ),
                },
                "releases": {
                    "release_count": len(release_rows),
                    "active_count": sum(1 for row in release_rows if row["status"] == "ACTIVE"),
                    "canary_count": sum(
                        1 for row in release_rows if str(row["stage"]).startswith("CANARY")
                    ),
                    "stopped_or_rolled_back_count": sum(
                        1
                        for row in release_rows
                        if row["status"] in {"STOPPED", "ROLLED_BACK"}
                    ),
                },
            },
        }

    def get(self, *, tenant_id: str, failure_id: UUID) -> FailureCaseView | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT failure_id, tenant_id, signal, severity, source, run_id, eval_run_id, case_id, "
                    "trace_refs, signals_json, status, cluster_key, summary_redacted, source_count, created_at, updated_at "
                    "FROM evaluation.failure_cases WHERE tenant_id = :tenant_id AND failure_id = :failure_id"
                ), {"tenant_id": tenant_id, "failure_id": failure_id}
            ).mappings().first()
            attribution = None
            if row is not None:
                attribution = connection.execute(
                    text(
                        "SELECT deterministic_category, llm_category, confidence, evidence_refs, "
                        "review_status, rationale_redacted, model_hash, prompt_hash, created_at, "
                        "reviewed_category, reviewed_by, reviewed_at, review_note_redacted "
                        "FROM evaluation.failure_attributions WHERE failure_id = :failure_id "
                        "ORDER BY created_at DESC LIMIT 1"
                    ), {"failure_id": failure_id}
                ).mappings().first()
        if not row:
            return None
        view = self._view(row)
        return view.model_copy(update={"attribution": dict(attribution) if attribution else None})

    def add_attribution(
        self, *, failure_id: UUID, deterministic_category: str, llm_category: str | None,
        confidence: float | None, evidence_refs: tuple[str, ...], model_hash: str | None,
        prompt_hash: str | None, review_status: str, rationale: str | None,
    ) -> UUID:
        with self._engine.begin() as connection:
            return cast(UUID, connection.execute(
                text(
                    "INSERT INTO evaluation.failure_attributions "
                    "(attribution_id, failure_id, deterministic_category, llm_category, confidence, evidence_refs, model_hash, prompt_hash, review_status, rationale_redacted) "
                    "VALUES (:id, :failure_id, :deterministic, :llm, :confidence, CAST(:evidence AS jsonb), :model_hash, :prompt_hash, :review_status, :rationale) RETURNING attribution_id"
                ),
                {"id": uuid4(), "failure_id": failure_id, "deterministic": deterministic_category,
                 "llm": llm_category, "confidence": confidence, "evidence": json.dumps(evidence_refs),
                 "model_hash": model_hash, "prompt_hash": prompt_hash, "review_status": review_status,
                 "rationale": rationale[:2000] if rationale else None},
            ).scalar_one())

    def review_attribution(
        self,
        *,
        tenant_id: str,
        failure_id: UUID,
        outcome: str,
        reviewer: str,
        reviewed_category: str | None,
        review_note: str,
    ) -> UUID:
        """Attach a human decision to the latest automatic attribution.

        Automatic fields are preserved; the human category and note live in
        their own columns.  This prevents an operator decision from being
        mistaken for an LLM result during later Skill generation.
        """

        if outcome not in {"verified_success", "verified_failure"}:
            raise ValueError("invalid_review_outcome")
        if not reviewer or not review_note.strip():
            raise ValueError("reviewer_and_note_required")
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT a.attribution_id FROM evaluation.failure_attributions a "
                    "JOIN evaluation.failure_cases f ON f.failure_id = a.failure_id "
                    "WHERE f.tenant_id = :tenant_id AND a.failure_id = :failure_id "
                    "ORDER BY a.created_at DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id, "failure_id": failure_id},
            ).first()
            if row is None:
                attribution_id = uuid4()
                connection.execute(
                    text(
                        "INSERT INTO evaluation.failure_attributions "
                        "(attribution_id, failure_id, deterministic_category, review_status, "
                        "reviewed_category, reviewed_by, reviewed_at, review_note_redacted) "
                        "VALUES (:id, :failure_id, 'unknown', :status, :category, :reviewer, now(), :note)"
                    ),
                    {
                        "id": attribution_id,
                        "failure_id": failure_id,
                        "status": outcome,
                        "category": reviewed_category,
                        "reviewer": reviewer[:128],
                        "note": redact_text(review_note),
                    },
                )
            else:
                attribution_id = UUID(str(row[0]))
                connection.execute(
                    text(
                        "UPDATE evaluation.failure_attributions SET review_status = :status, "
                        "reviewed_category = :category, reviewed_by = :reviewer, reviewed_at = now(), "
                        "review_note_redacted = :note WHERE attribution_id = :id"
                    ),
                    {
                        "id": attribution_id,
                        "status": outcome,
                        "category": reviewed_category,
                        "reviewer": reviewer[:128],
                        "note": redact_text(review_note),
                    },
                )
            connection.execute(
                text(
                    "UPDATE evaluation.failure_cases SET status = 'reviewed', updated_at = now() "
                    "WHERE tenant_id = :tenant_id AND failure_id = :failure_id"
                ),
                {"tenant_id": tenant_id, "failure_id": failure_id},
            )
        return attribution_id

    @staticmethod
    def _view(row: Any) -> FailureCaseView:
        values = dict(row)
        values["trace_refs"] = tuple(str(item) for item in (values.get("trace_refs") or []))
        values["signals"] = tuple(
            item for item in (values.pop("signals_json", None) or []) if isinstance(item, dict)
        )
        values["attribution"] = values.pop("attribution_json", None)
        return FailureCaseView(**values)


__all__ = ["FailureRepository"]

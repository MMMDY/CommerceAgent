"""Tenant-scoped, redacted read models for Run observability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

_PRIMARY_SAFETY_CATEGORIES = (
    "account_takeover",
    "transaction_bypass",
    "privacy",
    "prompt_injection",
    "unknown_tool_state",
)


@dataclass(frozen=True, slots=True)
class ModelInvocationView:
    model_call_id: UUID
    step_id: str
    purpose: str
    provider: str
    model: str
    status: str
    error_code: str | None
    latency_ms: int | None
    first_token_latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    usage_estimated: bool
    provider_usage_version: str | None
    pricing_version_id: UUID | None
    cost_microusd: int | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ToolInvocationView:
    tool_call_id: UUID
    step_id: str
    tool_name: str
    tool_version: str
    risk_level: str
    status: str
    attempt_no: int
    error_code: str | None
    latency_ms: int | None
    started_at: datetime
    finished_at: datetime | None


class RunObservabilityRepository:
    """Expose structured metadata while keeping prompts and payloads server-side."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def model_invocations(self, *, run_id: UUID, tenant_id: str) -> tuple[ModelInvocationView, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT invocation.model_call_id, invocation.step_id, invocation.purpose, "
                    "invocation.provider, invocation.model, invocation.status, "
                    "invocation.error_code, invocation.latency_ms, "
                    "invocation.first_token_latency_ms, invocation.input_tokens, "
                    "invocation.output_tokens, invocation.cached_input_tokens, "
                    "invocation.reasoning_tokens, invocation.total_tokens, "
                    "invocation.usage_estimated, invocation.provider_usage_version, "
                    "invocation.pricing_version_id, invocation.cost_microusd, "
                    "invocation.started_at, invocation.finished_at "
                    "FROM runtime.model_invocations AS invocation "
                    "JOIN runtime.agent_runs AS run ON run.run_id = invocation.run_id "
                    "WHERE invocation.run_id = :run_id AND run.tenant_id = :tenant_id "
                    "ORDER BY invocation.started_at, invocation.model_call_id"
                ),
                {"run_id": run_id, "tenant_id": tenant_id},
            ).mappings()
        return tuple(ModelInvocationView(**dict(row)) for row in rows)

    def tool_invocations(self, *, run_id: UUID, tenant_id: str) -> tuple[ToolInvocationView, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT invocation.tool_call_id, invocation.step_id, invocation.tool_name, "
                    "invocation.tool_version, invocation.risk_level, invocation.status, "
                    "invocation.attempt_no, invocation.error_code, invocation.latency_ms, "
                    "invocation.started_at, invocation.finished_at "
                    "FROM runtime.tool_invocations AS invocation "
                    "JOIN runtime.agent_runs AS run ON run.run_id = invocation.run_id "
                    "WHERE invocation.run_id = :run_id AND run.tenant_id = :tenant_id "
                    "ORDER BY invocation.started_at, invocation.tool_call_id"
                ),
                {"run_id": run_id, "tenant_id": tenant_id},
            ).mappings()
        return tuple(ToolInvocationView(**dict(row)) for row in rows)

    def operations_summary(
        self,
        *,
        tenant_id: str,
        window_hours: int = 24,
        route: str | None = None,
        model: str | None = None,
        run_limit: int = 50,
    ) -> dict[str, object]:
        if not 1 <= window_hours <= 24 * 31:
            raise ValueError("window_hours must be between 1 and 744")
        if not 1 <= run_limit <= 200:
            raise ValueError("run_limit must be between 1 and 200")
        params: dict[str, object] = {
            "tenant_id": tenant_id,
            "window_hours": window_hours,
            "run_limit": run_limit,
        }
        route_expression = (
            "COALESCE("
            "(SELECT checkpoint.state_json->>'route' FROM runtime.run_checkpoints AS checkpoint "
            " WHERE checkpoint.run_id = run.run_id ORDER BY checkpoint.checkpoint_seq "
            "DESC LIMIT 1), "
            "(SELECT event.payload_json->>'route' FROM runtime.run_events AS event "
            " WHERE event.run_id = run.run_id AND event.payload_json ? 'route' "
            " ORDER BY event.event_seq DESC LIMIT 1), run.workflow_id)"
        )
        route_filter = ""
        if route:
            params["route"] = route
            route_filter = f" AND {route_expression} = :route"
        model_filter = ""
        model_scope_filter = ""
        if model:
            params["model"] = model
            model_filter = " AND invocation.provider || '/' || invocation.model = :model"
            model_scope_filter = (
                " AND EXISTS (SELECT 1 FROM runtime.model_invocations AS scoped_invocation "
                "WHERE scoped_invocation.run_id = run.run_id "
                "AND scoped_invocation.provider || '/' || scoped_invocation.model = :model)"
            )
        scoped_cost = "run.total_cost_microusd"
        if model:
            scoped_cost = (
                "(SELECT CASE WHEN count(*) = count(cost_microusd) "
                "THEN sum(cost_microusd) ELSE NULL END "
                "FROM runtime.model_invocations AS selected_invocation "
                "WHERE selected_invocation.run_id = run.run_id "
                "AND selected_invocation.provider || '/' || selected_invocation.model = :model)"
            )
        scoped_runs = (
            "WITH scoped_runs AS (SELECT run.*, "
            f"{route_expression} AS route, {scoped_cost} AS scoped_cost "
            "FROM runtime.agent_runs AS run "
            "WHERE run.tenant_id = :tenant_id"
            f"{route_filter}{model_scope_filter})"
        )
        with self._engine.connect() as connection:
            summary = (
                connection.execute(
                    text(
                        scoped_runs + ", scoped AS ("
                        " SELECT status, accepted_at, response_published_at, scoped_cost,"
                        " CASE WHEN accepted_at IS NOT NULL AND response_published_at IS NOT NULL"
                        " THEN EXTRACT(EPOCH FROM (response_published_at - accepted_at)) * 1000"
                        " END AS latency_ms FROM scoped_runs"
                        " WHERE accepted_at >= now() - make_interval(hours => :window_hours)"
                        ") SELECT count(*)::bigint AS request_count,"
                        " count(*) FILTER (WHERE status = 'completed')::bigint AS completed_count,"
                        " count(*) FILTER (WHERE status = 'failed')::bigint AS failed_count,"
                        " count(latency_ms)::bigint AS measured_latency_count,"
                        " percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) "
                        "AS p50_latency_ms,"
                        " percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) "
                        "AS p95_latency_ms,"
                        " percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) "
                        "AS p99_latency_ms,"
                        " count(scoped_cost)::bigint AS priced_run_count,"
                        " avg(scoped_cost) FILTER (WHERE status = 'completed')"
                        " AS avg_success_cost_microusd,"
                        " sum(scoped_cost) AS total_cost_microusd FROM scoped"
                    ),
                    params,
                )
                .mappings()
                .one()
            )
            invocation = (
                connection.execute(
                    text(
                        scoped_runs
                        + " SELECT invocation.purpose, invocation.provider, invocation.model,"
                        " count(*)::bigint AS invocation_count,"
                        " count(invocation.total_tokens)::bigint AS measured_token_count,"
                        " sum(invocation.input_tokens)::bigint AS input_tokens,"
                        " sum(invocation.output_tokens)::bigint AS output_tokens,"
                        " sum(invocation.cached_input_tokens)::bigint AS cached_input_tokens,"
                        " sum(invocation.reasoning_tokens)::bigint AS reasoning_tokens,"
                        " sum(invocation.total_tokens)::bigint AS total_tokens,"
                        " count(*) FILTER (WHERE invocation.usage_estimated)::bigint "
                        "AS estimated_count,"
                        " count(invocation.cost_microusd)::bigint AS priced_count,"
                        " sum(invocation.cost_microusd)::bigint AS cost_microusd"
                        " FROM runtime.model_invocations AS invocation"
                        " JOIN scoped_runs AS run ON run.run_id = invocation.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        + model_filter
                        + " GROUP BY invocation.purpose, invocation.provider, invocation.model"
                        " ORDER BY invocation.purpose, invocation.provider, invocation.model"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            trend = (
                connection.execute(
                    text(
                        scoped_runs + " SELECT date_trunc('hour', accepted_at) AS bucket,"
                        " count(*)::bigint AS requests,"
                        " count(*) FILTER (WHERE status = 'completed')::bigint AS completed,"
                        " count(scoped_cost)::bigint AS priced_runs,"
                        " sum(scoped_cost)::bigint AS cost_microusd"
                        " FROM scoped_runs WHERE accepted_at >= now() - make_interval("
                        "hours => :window_hours)"
                        " GROUP BY bucket ORDER BY bucket"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            safety = (
                connection.execute(
                    text(
                        scoped_runs
                        + " SELECT count(*) FILTER (WHERE event.payload_json->>'risk_level' IN "
                        "('high', 'medium'))::bigint AS triaged_risk_count, "
                        " count(*) FILTER (WHERE event.payload_json->>'disposition' = "
                        "'blocked')::bigint AS blocked_count,"
                        " count(*) FILTER (WHERE event.payload_json->>'risk_level' = "
                        "'high')::bigint AS high_risk_count"
                        " FROM runtime.run_events AS event JOIN scoped_runs AS run "
                        "ON run.run_id = event.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " AND event.event_type = 'safety_routed'"
                    ),
                    params,
                )
                .mappings()
                .one()
            )
            safety_categories = (
                connection.execute(
                    text(
                        scoped_runs
                        + " SELECT COALESCE(NULLIF(event.payload_json->>'category', ''), "
                        "'unknown') AS category,"
                        " count(*)::bigint AS hit_count,"
                        " count(*) FILTER (WHERE event.payload_json->>'disposition' = "
                        "'handoff')::bigint AS handoff_count FROM runtime.run_events AS event"
                        " JOIN scoped_runs AS run ON run.run_id = event.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " AND event.event_type = 'safety_routed' GROUP BY category "
                        "ORDER BY hit_count DESC, category"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            safety_trend = (
                connection.execute(
                    text(
                        scoped_runs + " SELECT date_trunc('hour', event.created_at) AS bucket, "
                        "count(*)::bigint AS triaged_count,"
                        " count(*) FILTER (WHERE event.payload_json->>'disposition' = "
                        "'blocked')::bigint AS blocked_count,"
                        " count(*) FILTER (WHERE event.payload_json->>'disposition' = "
                        "'handoff')::bigint AS handoff_count"
                        " FROM runtime.run_events AS event JOIN scoped_runs AS run "
                        "ON run.run_id = event.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " AND event.event_type = 'safety_routed' GROUP BY bucket ORDER BY bucket"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            handoff = (
                connection.execute(
                    text(
                        scoped_runs
                        + " SELECT count(*)::bigint AS handoff_count FROM runtime.run_events "
                        "AS event"
                        " JOIN scoped_runs AS run ON run.run_id = event.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " AND event.event_type::text LIKE '%handoff%'"
                    ),
                    params,
                )
                .mappings()
                .one()
            )
            recent_runs = (
                connection.execute(
                    text(
                        scoped_runs
                        + " SELECT run.run_id, run.status, run.execution_mode, run.workflow_id, "
                        "run.route,"
                        " run.accepted_at, run.response_published_at, run.scoped_cost "
                        "AS total_cost_microusd,"
                        " CASE WHEN run.accepted_at IS NOT NULL AND "
                        "run.response_published_at IS NOT NULL"
                        " THEN EXTRACT(EPOCH FROM (run.response_published_at - "
                        "run.accepted_at)) * 1000 END AS latency_ms,"
                        " (SELECT string_agg(DISTINCT invocation.provider || '/' || "
                        "invocation.model, ', '"
                        " ORDER BY invocation.provider || '/' || invocation.model)"
                        " FROM runtime.model_invocations AS invocation WHERE "
                        "invocation.run_id = run.run_id) AS models"
                        " FROM scoped_runs AS run WHERE run.accepted_at >= now()"
                        " - make_interval(hours => :window_hours)"
                        + (
                            " AND EXISTS (SELECT 1 FROM runtime.model_invocations AS invocation"
                            " WHERE invocation.run_id = run.run_id AND invocation.provider || '/' "
                            "|| invocation.model = :model)"
                            if model
                            else ""
                        )
                        + " ORDER BY run.accepted_at DESC LIMIT :run_limit"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            available_routes = (
                connection.execute(
                    text(
                        scoped_runs
                        + " SELECT DISTINCT route FROM scoped_runs WHERE route IS NOT NULL "
                        "ORDER BY route LIMIT 100"
                    ),
                    params,
                )
                .scalars()
                .all()
            )
            available_models = (
                connection.execute(
                    text(
                        "SELECT DISTINCT invocation.provider || '/' || invocation.model AS model"
                        " FROM runtime.model_invocations AS invocation JOIN runtime.agent_runs "
                        "AS run"
                        " ON run.run_id = invocation.run_id WHERE run.tenant_id = :tenant_id"
                        " AND run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " ORDER BY model LIMIT 100"
                    ),
                    params,
                )
                .scalars()
                .all()
            )
            release = (
                connection.execute(
                    text(
                        "WITH latest AS (SELECT release_id, current_version, candidate_version, "
                        "stage, "
                        "status FROM release.releases WHERE tenant_id = :tenant_id "
                        "ORDER BY updated_at DESC LIMIT 1)"
                        " SELECT latest.release_id, latest.current_version, "
                        "latest.candidate_version, latest.stage,"
                        " latest.status, count(assignment.assignment_id)::bigint "
                        "AS assignment_count,"
                        " count(*) FILTER (WHERE assignment.mode = 'shadow')::bigint "
                        "AS shadow_count,"
                        " count(*) FILTER (WHERE assignment.mode = 'canary')::bigint "
                        "AS canary_count,"
                        " count(*) FILTER (WHERE assignment.mode = 'current')::bigint "
                        "AS current_count"
                        " FROM latest LEFT JOIN release.release_assignments AS assignment"
                        " ON assignment.release_id = latest.release_id AND "
                        "assignment.created_at >= "
                        "now()"
                        " - make_interval(hours => :window_hours) GROUP BY latest.release_id,"
                        " latest.current_version, latest.candidate_version, latest.stage, "
                        "latest.status"
                    ),
                    params,
                )
                .mappings()
                .first()
            )
            version_breakdown = (
                connection.execute(
                    text(
                        scoped_runs
                        + ", latest_release AS ("
                        " SELECT release_id FROM release.releases"
                        " WHERE tenant_id = :tenant_id ORDER BY updated_at DESC LIMIT 1"
                        "), assignments AS ("
                        " SELECT assignment.run_id, assignment.selected_version, assignment.mode"
                        " FROM release.release_assignments AS assignment"
                        " JOIN latest_release ON latest_release.release_id = assignment.release_id"
                        " WHERE assignment.tenant_id = :tenant_id"
                        "), grouped AS ("
                        " SELECT COALESCE(assignment.selected_version, 'unassigned') AS version,"
                        " count(*)::bigint AS request_count,"
                        " count(*) FILTER (WHERE run.status = 'completed')::bigint AS "
                        "completed_count,"
                        " count(*) FILTER (WHERE run.status = 'failed')::bigint AS failed_count,"
                        " count(*) FILTER (WHERE assignment.mode = 'shadow')::bigint AS "
                        "shadow_count,"
                        " count(*) FILTER (WHERE assignment.mode = 'canary')::bigint AS "
                        "canary_count,"
                        " count(*) FILTER (WHERE assignment.mode = 'current')::bigint AS "
                        "current_count,"
                        " percentile_cont(0.95) WITHIN GROUP (ORDER BY"
                        " CASE WHEN run.accepted_at IS NOT NULL AND "
                        "run.response_published_at IS NOT NULL"
                        " THEN EXTRACT(EPOCH FROM (run.response_published_at - "
                        "run.accepted_at)) * 1000 END)"
                        " AS p95_latency_ms,"
                        " avg(run.total_cost_microusd) FILTER (WHERE run.status = 'completed')"
                        " AS avg_success_cost_microusd"
                        " FROM scoped_runs AS run LEFT JOIN assignments AS assignment"
                        " ON assignment.run_id = run.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " GROUP BY version"
                        "), token_usage AS ("
                        " SELECT COALESCE(assignment.selected_version, 'unassigned') AS version,"
                        " sum(invocation.total_tokens)::bigint AS total_tokens,"
                        " count(invocation.total_tokens)::bigint AS measured_token_count"
                        " FROM scoped_runs AS run LEFT JOIN assignments AS assignment"
                        " ON assignment.run_id = run.run_id"
                        " LEFT JOIN runtime.model_invocations AS invocation"
                        " ON invocation.run_id = run.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " GROUP BY version"
                        "), route_rows AS ("
                        " SELECT COALESCE(assignment.selected_version, 'unassigned') AS version,"
                        " COALESCE(run.route, 'unknown') AS route, count(*)::bigint AS route_count"
                        " FROM scoped_runs AS run LEFT JOIN assignments AS assignment"
                        " ON assignment.run_id = run.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " GROUP BY version, route"
                        "), route_counts AS ("
                        " SELECT version, jsonb_object_agg(route, route_count) AS route_counts"
                        " FROM route_rows GROUP BY version"
                        "), skill_counts AS ("
                        " SELECT COALESCE(assignment.selected_version, 'unassigned') AS version,"
                        " count(DISTINCT skill_match.match_id)::bigint AS skill_match_count"
                        " FROM scoped_runs AS run LEFT JOIN assignments AS assignment"
                        " ON assignment.run_id = run.run_id"
                        " LEFT JOIN experience.skill_matches AS skill_match"
                        " ON skill_match.run_id = run.run_id AND skill_match.tenant_id = :tenant_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " GROUP BY version"
                        "), event_counts AS ("
                        " SELECT COALESCE(assignment.selected_version, 'unassigned') AS version,"
                        " count(DISTINCT run.run_id)::bigint AS event_run_count,"
                        " count(*) FILTER (WHERE event.event_type = 'safety_routed')::bigint AS"
                        " safety_hit_count,"
                        " count(*) FILTER (WHERE event.event_type = 'safety_routed'"
                        " AND event.payload_json->>'risk_level' = 'high')::bigint AS"
                        " safety_high_risk_count,"
                        " count(*) FILTER (WHERE event.event_type = 'safety_routed'"
                        " AND event.payload_json->>'disposition' = 'blocked')::bigint AS"
                        " safety_blocked_count,"
                        " count(DISTINCT run.run_id) FILTER (WHERE event.event_type ="
                        " 'handoff_created')::bigint AS handoff_count"
                        " FROM scoped_runs AS run LEFT JOIN assignments AS assignment"
                        " ON assignment.run_id = run.run_id"
                        " LEFT JOIN runtime.run_events AS event ON event.run_id = run.run_id"
                        " WHERE run.accepted_at >= now() - make_interval(hours => :window_hours)"
                        " GROUP BY version"
                        ") SELECT grouped.*, token_usage.total_tokens,"
                        " token_usage.measured_token_count, route_counts.route_counts,"
                        " COALESCE(skill_counts.skill_match_count, 0)::bigint AS skill_match_count,"
                        " COALESCE(event_counts.event_run_count, 0)::bigint AS event_run_count,"
                        " COALESCE(event_counts.safety_hit_count, 0)::bigint AS safety_hit_count,"
                        " COALESCE(event_counts.safety_high_risk_count, 0)::bigint AS"
                        " safety_high_risk_count,"
                        " COALESCE(event_counts.safety_blocked_count, 0)::bigint AS"
                        " safety_blocked_count,"
                        " COALESCE(event_counts.handoff_count, 0)::bigint AS handoff_count,"
                        " CASE WHEN grouped.request_count > 0 THEN"
                        " COALESCE(event_counts.handoff_count, 0)::numeric / grouped.request_count"
                        " ELSE NULL END AS handoff_rate,"
                        " NULL::numeric AS quality_score, 0::bigint AS quality_measured_count"
                        " FROM grouped LEFT JOIN token_usage USING (version)"
                        " LEFT JOIN route_counts USING (version)"
                        " LEFT JOIN skill_counts USING (version)"
                        " LEFT JOIN event_counts USING (version) ORDER BY version"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        category_rows = [dict(row) for row in safety_categories]
        category_by_name = {str(row["category"]): row for row in category_rows}
        safety_category_breakdown = [
            {
                "category": category,
                "hit_count": int(category_by_name.get(category, {}).get("hit_count", 0) or 0),
                "handoff_count": int(
                    category_by_name.get(category, {}).get("handoff_count", 0) or 0
                ),
                # These require reviewed labels and are intentionally not
                # inferred from detector hits.
                "false_negative_count": None,
                "false_rejection_count": None,
            }
            for category in _PRIMARY_SAFETY_CATEGORIES
        ]
        return {
            **dict(summary),
            "model_breakdown": [dict(row) for row in invocation],
            "trend": [dict(row) for row in trend],
            "safety_summary": dict(safety),
            "safety_categories": category_rows,
            "safety_category_breakdown": safety_category_breakdown,
            "safety_trend": [
                {**dict(row), "bucket": row["bucket"].isoformat()} for row in safety_trend
            ],
            "safety_handoff_count": int(handoff["handoff_count"] or 0),
            # Reviewed false-positive/false-negative labels are intentionally N/A.
            "safety_false_negative_count": None,
            "safety_false_rejection_count": None,
            "release_summary": dict(release) if release is not None else None,
            "version_breakdown": [dict(row) for row in version_breakdown],
            "recent_runs": [
                {
                    **dict(row),
                    "run_id": str(row["run_id"]),
                    "accepted_at": row["accepted_at"].isoformat() if row["accepted_at"] else None,
                    "response_published_at": row["response_published_at"].isoformat()
                    if row["response_published_at"]
                    else None,
                }
                for row in recent_runs
            ],
            "available_routes": [str(item) for item in available_routes],
            "available_models": [str(item) for item in available_models],
        }


__all__ = [
    "ModelInvocationView",
    "RunObservabilityRepository",
    "ToolInvocationView",
]

"""Shared failure projection and evidence-bounded attribution service.

All runtime failure signals use this boundary.  It deliberately separates:

* deterministic taxonomy, which is always available;
* optional LLM attribution, which requires replayable event evidence; and
* human review, which is never implied by an automated result.

The service only sends redacted summaries and event ids/types to the optional
attribution model.  It never sends the original user message or model prompt.
"""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from uuid import UUID

from sqlalchemy.engine import Engine

from src.config import Settings, get_settings
from src.evolution.attribution_llm import AttributionAnalyzer, AttributionModelConfig
from src.evolution.attribution_rules import deterministic_category
from src.evolution.clustering import cluster_key
from src.evolution.contracts import FailureCaseView
from src.evolution.failure_signals import signals_for_evaluation, signals_for_run
from src.evolution.redaction import redact_text
from src.repositories.failures import FailureRepository
from src.repositories.runs import RunRepository


class FailureAttributionService:
    """Project a failure signal and optionally attach a pending LLM attribution."""

    def __init__(
        self,
        engine: Engine,
        *,
        settings: Settings | None = None,
        failures: FailureRepository | None = None,
        runs: RunRepository | None = None,
        analyzer_factory: Callable[..., AttributionAnalyzer] = AttributionAnalyzer,
    ) -> None:
        self._engine = engine
        self._settings = settings or get_settings()
        self._failures = failures or FailureRepository(engine)
        self._runs = runs or RunRepository(engine)
        self._analyzer_factory = analyzer_factory

    def record_run_signal(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        signal: str,
        source: str,
        reason: str,
        route: str | None = None,
        severity: str | None = None,
    ) -> FailureCaseView | None:
        """Record a run-bound signal and attach deterministic/optional attribution.

        Event replay is best effort for deterministic projection, but the LLM
        path is fail-closed when replay cannot produce a non-empty allow-list.
        """

        event_facts, event_types, allowed_event_ids = self._event_facts(
            run_id=run_id, tenant_id=tenant_id
        )
        category = deterministic_category(reason_code=reason, event_types=event_types)
        failure = self._failures.record_signal(
            tenant_id=tenant_id,
            signal=signal,
            severity=severity or self._severity_for(signal),
            source=source,
            run_id=run_id,
            cluster_key=cluster_key(
                category="run_signal",
                route=route or "terminal",
                # A Run may emit several independent failure signals.  Keep
                # them in one case and preserve the individual facts in the
                # repository's signals_json projection instead of creating a
                # new case for every terminal reason.
                reason_code=None,
            ),
            summary_redacted=redact_text(f"{signal}: {reason[:256]}"),
            trace_refs=tuple(item["event_id"] for item in event_facts),
        )
        self._append_attribution(
            failure=failure,
            category=category.value,
            event_facts=event_facts,
            allowed_event_ids=allowed_event_ids,
            signal=signal,
        )
        return self._failures.get(tenant_id=tenant_id, failure_id=failure.failure_id)

    def record_run_outcome(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        status: str,
        terminal_reason: str | None = None,
        route: str | None = None,
        eval_failed: bool = False,
        human_rejected: bool = False,
    ) -> tuple[FailureCaseView, ...]:
        """Project every observable outcome signal through one boundary.

        A single Run can emit multiple observations (for example a failed
        mutation that also exceeded budget).  The repository merges them into
        the same route-scoped case and retains each signal in ``signals``.
        """

        observations = signals_for_run(
            status=status,
            terminal_reason=terminal_reason,
            eval_failed=eval_failed,
            human_rejected=human_rejected,
        )
        results: list[FailureCaseView] = []
        for observation in observations:
            result = self.record_run_signal(
                tenant_id=tenant_id,
                run_id=run_id,
                signal=observation.signal.value,
                source=observation.source,
                reason=observation.reason_code,
                route=route,
                severity=observation.severity,
            )
            if result is not None:
                results.append(result)
        return tuple(results)

    def record_evaluation_outcome(
        self,
        *,
        tenant_id: str,
        eval_run_id: UUID,
        case_id: str,
        track: str,
        eval_failed: bool,
        cost_microusd: int | None = None,
        cost_budget_microusd: int | None = None,
        failure_reason: str = "EVALUATION_FAILED",
    ) -> tuple[FailureCaseView, ...]:
        """Project evaluation and budget failures into the same failure pool.

        Evaluation cases have no runtime Run/event stream, so the projection
        uses only immutable identifiers and evaluator reason codes.  It never
        sends case text to the attribution model and remains ``pending`` until
        a human review supplies a conclusion.
        """

        observations = signals_for_evaluation(
            eval_failed=eval_failed,
            cost_microusd=cost_microusd,
            cost_budget_microusd=cost_budget_microusd,
            failure_reason=failure_reason,
        )
        results: list[FailureCaseView] = []
        for observation in observations:
            failure = self._failures.record_signal(
                tenant_id=tenant_id,
                signal=observation.signal.value,
                severity=observation.severity,
                source=observation.source,
                run_id=None,
                eval_run_id=eval_run_id,
                case_id=case_id,
                cluster_key=cluster_key(
                    category="evaluation",
                    route=track,
                    reason_code=observation.signal.value,
                ),
                summary_redacted=(
                    f"{observation.signal.value}: {observation.reason_code}"
                ),
            )
            self._append_attribution(
                failure=failure,
                category=deterministic_category(
                    reason_code=observation.reason_code,
                    event_types=(),
                ).value,
                event_facts=[],
                allowed_event_ids=set(),
                signal=observation.signal.value,
                rationale="评测/预算信号已记录；自动化结果仍待人工复核。",
            )
            refreshed = self._failures.get(
                tenant_id=tenant_id, failure_id=failure.failure_id
            )
            if refreshed is not None:
                results.append(refreshed)
        return tuple(results)

    def reanalyze(self, failure: FailureCaseView) -> FailureCaseView | None:
        """Attach a fresh pending attribution to an existing failure case."""

        event_facts: list[dict[str, str]] = []
        event_types: tuple[str, ...] = ()
        allowed_event_ids: set[str] = set()
        if failure.run_id is not None:
            event_facts, event_types, allowed_event_ids = self._event_facts(
                run_id=failure.run_id, tenant_id=failure.tenant_id
            )
        category = deterministic_category(
            reason_code=failure.signal, event_types=event_types
        )
        self._append_attribution(
            failure=failure,
            category=category.value,
            event_facts=event_facts,
            allowed_event_ids=allowed_event_ids,
            signal=failure.signal,
            rationale="重新运行确定性归因；自动化评测没有真人审批，因此仍待复核。",
        )
        return self._failures.get(
            tenant_id=failure.tenant_id, failure_id=failure.failure_id
        )

    def _event_facts(
        self, *, run_id: UUID, tenant_id: str
    ) -> tuple[list[dict[str, str]], tuple[str, ...], set[str]]:
        try:
            replayed = self._runs.replay_events(run_id=run_id, tenant_id=tenant_id)
            facts = [
                {"event_id": str(item.event_id), "type": item.event.event_type.value}
                for item in replayed
            ]
            return facts, tuple(item["type"] for item in facts), {
                item["event_id"] for item in facts
            }
        except Exception:
            return [], (), set()

    def _append_attribution(
        self,
        *,
        failure: FailureCaseView,
        category: str,
        event_facts: list[dict[str, str]],
        allowed_event_ids: set[str],
        signal: str,
        rationale: str | None = None,
    ) -> None:
        llm_category: str | None = None
        llm_confidence: float | None = None
        llm_evidence: tuple[str, ...] = tuple(failure.trace_refs)
        final_rationale = rationale or "确定性规则归因；LLM 归因需独立模型并保持待复核。"
        settings = self._settings
        if (
            settings.enable_failure_attribution
            and settings.judge_model
            and settings.judge_api_base
            and settings.judge_api_key
            and allowed_event_ids
        ):
            try:
                output = self._analyzer_factory(
                    AttributionModelConfig(
                        model=settings.judge_model,
                        api_base=settings.judge_api_base,
                        api_key=settings.judge_api_key.get_secret_value(),
                    )
                ).analyze(
                    signal=signal,
                    summary_redacted=failure.summary_redacted,
                    deterministic_category=category,
                    event_facts=event_facts,
                    allowed_event_ids=allowed_event_ids,
                )
            except Exception:
                output = None
            if output is not None:
                llm_category = output.category.value
                llm_confidence = output.confidence
                llm_evidence = output.evidence_event_ids
                final_rationale = output.rationale or final_rationale

        self._failures.add_attribution(
            failure_id=failure.failure_id,
            deterministic_category=category,
            llm_category=llm_category,
            confidence=llm_confidence,
            evidence_refs=llm_evidence,
            model_hash=(
                _model_hash(settings.judge_model)
                if llm_category is not None and settings.judge_model
                else None
            ),
            prompt_hash=(
                "sha256:attribution-facts-only-v1" if llm_category is not None else None
            ),
            # Automated evidence is never a human approval.
            review_status="pending",
            rationale=final_rationale,
        )

    @staticmethod
    def _severity_for(signal: str) -> str:
        return "p1" if signal in {"run_failed", "cost_exceeded"} else "p2"


def _model_hash(model: str) -> str:
    return "sha256:" + sha256(("attribution-model:" + model).encode()).hexdigest()[:64]


__all__ = ["FailureAttributionService"]

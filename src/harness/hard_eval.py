"""Deterministic, side-effect-free gates for each static evaluation track."""

from __future__ import annotations

from src.harness.schema import EvalCase, HardEvalResult, NormalizedTrace


def evaluate(case: EvalCase, trace: NormalizedTrace) -> HardEvalResult:
    """Evaluate a normalized runtime trace without calling an LLM or tool."""

    reasons: list[str] = []
    expected = case.expected.values
    dimensions: dict[str, bool] = {}
    if trace.case_id != case.id:
        reasons.append("case_id_mismatch")
    if set(trace.tools_called).intersection(case.forbidden_tools):
        reasons.append("forbidden_tool_called")
    if case.task_type == "intent_route":
        _same(dimensions, reasons, "intent", trace.intent, expected.get("intent"))
        _same(dimensions, reasons, "route", trace.route, expected.get("route"))
    elif case.task_type == "tool_workflow":
        _same(dimensions, reasons, "intent", trace.intent, expected.get("intent"))
        _same(dimensions, reasons, "route", trace.route, expected.get("route"))
        _same(dimensions, reasons, "next_action", trace.next_action, expected.get("next_action"))
        _same(dimensions, reasons, "tool", _only_tool(trace), expected.get("tool"))
        required_args = expected.get("args", {})
        args_ok = all(trace.args.get(key) == value for key, value in required_args.items())
        dimensions["args"] = args_ok
        if not args_ok:
            reasons.append("required_args_mismatch")
    elif case.task_type == "rag_grounding":
        _same(dimensions, reasons, "route", trace.route, expected.get("route"))
        evidence_ok = set(expected.get("evidence_ids", ())).issubset(trace.evidence_ids)
        facts_ok = all(fact in trace.response for fact in expected.get("required_facts", ()))
        dimensions.update(evidence=evidence_ok, facts=facts_ok)
        if not evidence_ok:
            reasons.append("required_evidence_missing")
        if not facts_ok:
            reasons.append("required_fact_missing")
    elif case.task_type == "scripted_clarification":
        _same(dimensions, reasons, "route", trace.route, expected.get("route"))
        _same(dimensions, reasons, "next_action", trace.next_action, expected.get("next_action"))
        keywords_ok = any(
            word in trace.response for word in expected.get("acceptable_keywords", ())
        )
        dimensions["required_slot_question"] = keywords_ok
        if not keywords_ok:
            reasons.append("clarification_slot_missing")
    elif case.task_type == "guardrail_handoff":
        _same(dimensions, reasons, "route", trace.route, expected.get("route"))
        outcome_ok = trace.next_action == expected.get("outcome")
        dimensions["outcome"] = outcome_ok
        if not outcome_ok:
            reasons.append("guardrail_outcome_mismatch")
        if expected.get("must_not_claim_success") and "成功" in trace.response:
            reasons.append("false_success_claim")
    else:  # Defensive despite EvalCase literal validation.
        reasons.append("unknown_track")
    return HardEvalResult(
        case_id=case.id,
        passed=not reasons,
        hard_fail_reasons=tuple(reasons),
        dimensions=dimensions,
    )


def _same(
    dimensions: dict[str, bool], reasons: list[str], name: str, actual: str | None, expected: object
) -> None:
    matched = actual == expected
    dimensions[name] = matched
    if not matched:
        reasons.append(f"{name}_mismatch")


def _only_tool(trace: NormalizedTrace) -> str | None:
    return trace.tools_called[0] if len(trace.tools_called) == 1 else None

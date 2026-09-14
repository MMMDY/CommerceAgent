from __future__ import annotations

from uuid import uuid4

from src.policies.engine import FactCondition, PolicyEffect, PolicyEngine, PolicyRule
from src.protocols import (
    RetryPolicy,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from src.telemetry.trace import TraceStore
from src.tools.executor import ToolExecutor


def _context(scopes: tuple[str, ...] = ("order:read",)) -> ToolContext:
    return ToolContext(
        request_id=uuid4(),
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        scopes=scopes,
    )


def _spec(risk: ToolRisk = ToolRisk.READ_ONLY) -> ToolSpec:
    return ToolSpec(
        name="read",
        version="1",
        input_schema={},
        output_schema={},
        risk=risk,
        required_scopes=("order:read",),
        timeout_ms=1,
        retry_policy=RetryPolicy(max_attempts=2),
        model_visible=True,
    )


def test_readonly_retries_once_but_unknown_commit_does_not_retry() -> None:
    calls: list[int] = []

    def retrying(_: ToolContext, __: dict[str, object]) -> ToolResult:
        calls.append(1)
        return ToolResult(
            tool_name="read",
            tool_version="1",
            error=ToolError(code=ToolErrorCode.UPSTREAM_TIMEOUT, retryable=True, message="timeout"),
        )

    outcome = ToolExecutor({"read": retrying}).execute(
        spec=_spec(), context=_context(), arguments={}
    )
    assert outcome.attempts == 2 and len(calls) == 2
    unknown = ToolExecutor(
        {
            "read": lambda _c, _a: ToolResult(
                tool_name="read",
                tool_version="1",
                error=ToolError(
                    code=ToolErrorCode.STATUS_UNKNOWN, retryable=True, message="unknown"
                ),
            )
        }
    ).execute(spec=_spec(ToolRisk.COMMIT), context=_context(), arguments={})
    assert unknown.attempts == 1


def test_executor_denies_missing_scope_before_adapter() -> None:
    outcome = ToolExecutor(
        {"read": lambda _c, _a: (_ for _ in ()).throw(AssertionError())}
    ).execute(spec=_spec(), context=_context(()), arguments={})
    assert outcome.result.error is not None
    assert outcome.result.error.code is ToolErrorCode.PERMISSION_DENIED


def test_executor_requires_an_allowing_policy_before_the_adapter() -> None:
    policy = PolicyEngine(
        version="v1",
        allowed_facts=frozenset({"resource.owner_match"}),
        rules=(
            PolicyRule(
                "owner",
                "read",
                1,
                (FactCondition("resource.owner_match", "eq", True),),
                PolicyEffect.ALLOW,
                "OWNER",
            ),
        ),
    )
    executor = ToolExecutor(
        {"read": lambda _c, _a: ToolResult(tool_name="read", tool_version="1", data={})},
        policy=policy,
    )
    denied = executor.execute(spec=_spec(), context=_context(), arguments={})
    assert denied.result.error is not None
    assert denied.result.error.code is ToolErrorCode.POLICY_DENIED
    allowed = executor.execute(
        spec=_spec(), context=_context(), arguments={}, policy_facts={"resource.owner_match": True}
    )
    assert allowed.result.error is None


def test_executor_rejects_an_untrusted_adapter_result_before_observation() -> None:
    spec = _spec()
    spec = spec.model_copy(
        update={
            "output_schema": {
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            }
        }
    )
    wrong_identity = ToolExecutor(
        {"read": lambda _c, _a: ToolResult(tool_name="other", tool_version="1", data={"count": 1})}
    ).execute(spec=spec, context=_context(), arguments={})
    assert wrong_identity.result.error is not None
    malformed = ToolExecutor(
        {"read": lambda _c, _a: ToolResult(tool_name="read", tool_version="1", data={"count": "1"})}
    ).execute(spec=spec, context=_context(), arguments={})
    assert malformed.result.error is not None


def test_executor_maps_adapter_timeout_by_risk_and_never_retries_writes() -> None:
    ticks = iter((0.0, 0.002, 1.0, 1.002, 2.0, 2.002))
    calls: list[str] = []

    def adapter(_: ToolContext, __: dict[str, object]) -> ToolResult:
        calls.append("called")
        return ToolResult(tool_name="read", tool_version="1", data={})

    readonly = ToolExecutor({"read": adapter}, clock=lambda: next(ticks)).execute(
        spec=_spec(), context=_context(), arguments={}
    )
    assert readonly.attempts == 2
    assert readonly.result.error is not None
    assert readonly.result.error.code is ToolErrorCode.UPSTREAM_TIMEOUT

    commit = ToolExecutor({"read": adapter}, clock=lambda: next(ticks)).execute(
        spec=_spec(ToolRisk.COMMIT), context=_context(), arguments={}
    )
    assert commit.attempts == 1
    assert commit.result.error is not None
    assert commit.result.error.code is ToolErrorCode.STATUS_UNKNOWN
    assert len(calls) == 3


def test_executor_records_only_redacted_tool_execution_metadata() -> None:
    traces = TraceStore()
    executor = ToolExecutor(
        {
            "read": lambda _context, _arguments: ToolResult(
                tool_name="read",
                tool_version="1",
                data={"customer_phone": "13800138000", "api_key": "adapter-secret"},
            )
        },
        traces=traces,
    )

    outcome = executor.execute(
        spec=_spec(),
        context=_context(),
        arguments={
            "phone": "13800138000",
            "confirmation_token": "confirmation-secret",
            "api_key": "request-secret",
        },
    )

    assert outcome.result.error is None
    records = traces.records()
    assert len(records) == 1
    assert records[0].kind == "tool_observed"
    assert records[0].payload == {
        "tool_name": "read",
        "tool_version": "1",
        "risk": "read_only",
        "attempts": 1,
        "outcome": "succeeded",
    }
    serialized = str(records[0].payload)
    for forbidden in ("13800138000", "confirmation-secret", "request-secret", "adapter-secret"):
        assert forbidden not in serialized


def test_executor_records_denied_execution_without_invoking_adapter() -> None:
    traces = TraceStore()
    outcome = ToolExecutor(
        {"read": lambda _context, _arguments: (_ for _ in ()).throw(AssertionError())},
        traces=traces,
    ).execute(spec=_spec(), context=_context(()), arguments={})

    assert outcome.result.error is not None
    assert traces.records()[0].payload == {
        "tool_name": "read",
        "tool_version": "1",
        "risk": "read_only",
        "attempts": 0,
        "outcome": "failed",
        "error_code": "PERMISSION_DENIED",
        "retryable": False,
    }

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

from __future__ import annotations

import pytest

from src.harness.sandbox_tools import SandboxCommitBlocked, SandboxToolPolicy
from src.protocols import RetryPolicy, ToolRisk, ToolSpec


def _spec(name: str, risk: ToolRisk) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk=risk,
        required_scopes=(),
        timeout_ms=1000,
        retry_policy=RetryPolicy(max_attempts=1),
        model_visible=True,
    )


def test_commit_tools_are_always_blocked() -> None:
    policy = SandboxToolPolicy()

    with pytest.raises(SandboxCommitBlocked):
        policy.validate(_spec("commit_refund", ToolRisk.COMMIT))
    assert policy.can_commit() is False


def test_read_only_tool_cannot_be_disguised_as_prepare() -> None:
    with pytest.raises(ValueError, match="mutation tools"):
        SandboxToolPolicy().prepare(
            spec=_spec("get_order_status", ToolRisk.READ_ONLY), arguments={}
        )


@pytest.mark.parametrize("risk", (ToolRisk.PREPARE, ToolRisk.LOW_WRITE))
def test_prepare_only_returns_an_argument_hash_without_side_effects(risk: ToolRisk) -> None:
    preparation = SandboxToolPolicy().prepare(
        spec=_spec("refund", risk), arguments={"order_id": "ORD-1", "reason": "test"}
    )

    assert preparation.committed is False
    assert preparation.tool_name == "refund"
    assert preparation.arguments_hash.startswith("sha256:")
    assert len(preparation.arguments_hash) == len("sha256:") + 64

from __future__ import annotations

from uuid import uuid4

from src.protocols import ToolContext, ToolError, ToolErrorCode, ToolResult
from src.tools.fake import DeterministicFakeToolAdapter


def _context() -> ToolContext:
    return ToolContext(
        request_id=uuid4(),
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        scopes=(),
    )


def test_fake_tool_returns_queued_success_and_failure_in_order() -> None:
    success = ToolResult(tool_name="read", tool_version="1", data={"ok": True})
    timeout = ToolResult(
        tool_name="read",
        tool_version="1",
        error=ToolError(code=ToolErrorCode.UPSTREAM_TIMEOUT, retryable=True, message="timeout"),
    )
    adapter = DeterministicFakeToolAdapter((success, timeout))
    assert adapter(_context(), {"id": "1"}) == success
    assert adapter(_context(), {"id": "2"}) == timeout
    assert len(adapter.calls) == 2

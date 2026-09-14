"""Short-term session memory derived from trusted persisted state."""

from __future__ import annotations

from typing import Any

from src.repositories.messages import MessageRecord
from src.repositories.runs import RunSnapshot


def build_session_memory(
    *,
    messages: tuple[MessageRecord, ...],
    run: RunSnapshot | None = None,
) -> dict[str, Any]:
    """Return a redacted, non-authoritative view for Prompt/UI use.

    No long-term write happens here.  Only the authenticated conversation
    messages and the latest run snapshot are exposed; order/payment/refund
    values are deliberately omitted from the memory shape.
    """
    latest_user = next(
        (item.content_redacted for item in reversed(messages) if item.role == "user"),
        None,
    )
    result: dict[str, Any] = {
        "message_count": len(messages),
        "latest_user_goal": latest_user,
        "evidence_ids": [],
        "workflow": None,
    }
    if run is not None:
        result["workflow"] = {
            "run_id": str(run.run_id),
            "status": run.status,
            "current_step": run.current_step,
            "step_count": run.step_count,
        }
    return result

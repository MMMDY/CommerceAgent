from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.protocols import Decision, DecisionType, RunContext, RunStatus, SlotSource, SlotValue


def test_contracts_round_trip_with_schema_version() -> None:
    context = RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant-a",
        actor_id="actor-a",
        workflow_id="readonly",
        workflow_version="1.0",
        status=RunStatus.CREATED,
    )
    assert RunContext.model_validate_json(context.model_dump_json()) == context
    assert context.schema_version == "1.0"


def test_contracts_reject_unknown_fields_and_invalid_enums() -> None:
    with pytest.raises(ValidationError):
        SlotValue(value="x", source=SlotSource.USER, unexpected=True)
    with pytest.raises(ValidationError):
        Decision(
            type="unknown",
            intent="status",
            route="readonly",
            confidence=1,
        )


def test_decision_requires_bounded_confidence() -> None:
    with pytest.raises(ValidationError):
        Decision(type=DecisionType.RESPOND, intent="status", route="readonly", confidence=1.1)

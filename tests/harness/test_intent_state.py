from __future__ import annotations

import pytest

from src.harness.intent_state import IntentStateError, IntentStateMachine


def test_intent_state_machine_requires_raise_before_address() -> None:
    machine = IntentStateMachine(("物流",))
    with pytest.raises(IntentStateError, match="unraised"):
        machine.address_intents(("物流",), turn_id=1)
    machine.raise_intents(("物流",), turn_id=1, evidence=("user:turn_1",))
    machine.address_intents(("物流",), turn_id=1, evidence=("response:turn_1",))
    machine.verify_intents(("物流",), turn_id=2)
    assert machine.states == {"物流": "VERIFIED"}
    assert len(machine.history) == 3


def test_intent_state_machine_rejects_unknown_intent() -> None:
    machine = IntentStateMachine(("物流",))
    with pytest.raises(IntentStateError, match="outside"):
        machine.raise_intents(("退款",), turn_id=1)

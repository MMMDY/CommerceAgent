from src.agent.slot_extractor import SlotExtractor


def test_identifiers_are_extracted_as_unverified_user_slots() -> None:
    slots = SlotExtractor().extract(
        "请查询订单 ORD-demo-001 里的 TAH6206", required_slots=("order_id", "item_id")
    )
    assert slots["order_id"].value == "ORD-DEMO-001"
    assert slots["order_id"].verified is False
    assert slots["order_id"].source.value == "user"
    assert slots["item_id"].value == "TAH6206"


def test_extractor_does_not_invent_missing_slots() -> None:
    assert SlotExtractor().extract("我想查订单", required_slots=("order_id",)) == {}

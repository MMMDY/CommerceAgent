"""Deterministic extraction of identifiers before trusted owner verification."""

from __future__ import annotations

import re

from src.protocols import SlotSource, SlotValue

_ORDER_ID = re.compile(r"\bORD-[A-Z0-9-]{3,64}\b", re.IGNORECASE)
_PRODUCT_ID = re.compile(r"\b(?:[A-Z]{2,8}\d{2,8}(?:/[A-Z0-9]+)?)\b", re.IGNORECASE)


class SlotExtractor:
    """Extract only syntactic candidates; every result is explicitly unverified."""

    def extract(self, text: str, *, required_slots: tuple[str, ...] = ()) -> dict[str, SlotValue]:
        if not text.strip():
            return {}
        slots: dict[str, SlotValue] = {}
        order = _ORDER_ID.search(text)
        if order and (not required_slots or "order_id" in required_slots):
            slots["order_id"] = SlotValue(value=order.group(0).upper(), source=SlotSource.USER)
        product = _PRODUCT_ID.search(text)
        product_required = any(key in required_slots for key in ("product_id", "item_id", "sku"))
        if product and (not required_slots or product_required):
            value = product.group(0).upper()
            key = "item_id" if "item_id" in required_slots else "product_id"
            slots[key] = SlotValue(value=value, source=SlotSource.USER)
        return slots

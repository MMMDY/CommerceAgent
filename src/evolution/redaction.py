"""Small, conservative redaction helper for human-entered review notes."""

from __future__ import annotations

import re


def redact_text(value: str, *, maximum: int = 2000) -> str:
    value = re.sub(
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[EMAIL_REDACTED]",
        value,
    )
    value = re.sub(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", "[PAYMENT_REDACTED]", value)
    return value[:maximum]


__all__ = ["redact_text"]

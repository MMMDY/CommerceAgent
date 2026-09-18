"""Versioned pricing contracts used by runtime and evaluation reporting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.protocols import TokenUsage


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Prices are USD per one million tokens unless otherwise labelled."""

    pricing_version_id: str
    provider: str
    model: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None
    reasoning_per_million: Decimal | None = None
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.pricing_version_id or not self.provider or not self.model:
            raise ValueError("pricing identity is required")
        if self.currency != "USD":
            raise ValueError("runtime pricing must be stored in USD")
        prices = (
            self.input_per_million,
            self.output_per_million,
            self.cached_input_per_million,
            self.reasoning_per_million,
        )
        if any(price is not None and price < 0 for price in prices):
            raise ValueError("pricing cannot be negative")


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """A rounded, auditable cost result in integer micro-USD."""

    input_microusd: int = 0
    cached_input_microusd: int = 0
    output_microusd: int = 0
    reasoning_microusd: int = 0

    @property
    def total_microusd(self) -> int:
        return (
            self.input_microusd
            + self.cached_input_microusd
            + self.output_microusd
            + self.reasoning_microusd
        )


def usage_has_billable_tokens(usage: TokenUsage) -> bool:
    return any(
        value is not None
        for value in (
            usage.input_tokens,
            usage.cached_input_tokens,
            usage.output_tokens,
            usage.reasoning_tokens,
        )
    )

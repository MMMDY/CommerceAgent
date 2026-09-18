"""Exact, provider-independent model cost arithmetic."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.cost.models import CostBreakdown, ModelPricing, usage_has_billable_tokens
from src.protocols import TokenUsage


class CostCalculator:
    """Calculate costs without floating-point accumulation error."""

    _MICROUSD_PER_USD = Decimal(1_000_000)
    _TOKENS_PER_MILLION = Decimal(1_000_000)

    def calculate(
        self, *, usage: TokenUsage | None, pricing: ModelPricing | None
    ) -> CostBreakdown | None:
        if usage is None or pricing is None or not usage_has_billable_tokens(usage):
            return None
        return CostBreakdown(
            input_microusd=self._charge(usage.input_tokens, pricing.input_per_million),
            cached_input_microusd=self._charge(
                usage.cached_input_tokens,
                pricing.cached_input_per_million
                if pricing.cached_input_per_million is not None
                else pricing.input_per_million,
            ),
            output_microusd=self._charge(usage.output_tokens, pricing.output_per_million),
            reasoning_microusd=self._charge(
                usage.reasoning_tokens, pricing.reasoning_per_million
            )
            if pricing.reasoning_per_million is not None
            else 0,
        )

    def total_microusd(
        self, *, usage: TokenUsage | None, pricing: ModelPricing | None
    ) -> int | None:
        breakdown = self.calculate(usage=usage, pricing=pricing)
        return breakdown.total_microusd if breakdown is not None else None

    @classmethod
    def _charge(cls, tokens: int | None, price_per_million: Decimal) -> int:
        if tokens is None:
            return 0
        # USD/million × tokens × micro-USD/USD ÷ tokens/million simplifies
        # numerically, but retaining the explicit factors documents the unit.
        amount = (
            price_per_million
            * Decimal(tokens)
            * cls._MICROUSD_PER_USD
            / cls._TOKENS_PER_MILLION
        )
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

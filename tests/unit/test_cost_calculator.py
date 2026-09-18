from decimal import Decimal

import pytest

from src.cost.calculator import CostCalculator
from src.cost.models import ModelPricing
from src.protocols import TokenUsage


def _pricing(**overrides: object) -> ModelPricing:
    values: dict[str, object] = {
        "pricing_version_id": "pricing-v1",
        "provider": "provider",
        "model": "model",
        "input_per_million": Decimal("0.50"),
        "cached_input_per_million": Decimal("0.10"),
        "output_per_million": Decimal("1.00"),
        "reasoning_per_million": Decimal("2.00"),
    }
    values.update(overrides)
    return ModelPricing(**values)


def test_cost_calculator_returns_a_breakdown_in_integer_microusd() -> None:
    breakdown = CostCalculator().calculate(
        usage=TokenUsage(
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=50,
            reasoning_tokens=10,
        ),
        pricing=_pricing(),
    )
    assert breakdown is not None
    assert breakdown.input_microusd == 50
    assert breakdown.cached_input_microusd == 2
    assert breakdown.output_microusd == 50
    assert breakdown.reasoning_microusd == 20
    assert breakdown.total_microusd == 122


@pytest.mark.parametrize(
    "usage, pricing",
    ((None, _pricing()), (TokenUsage(), None), (TokenUsage(), _pricing())),
)
def test_cost_calculator_keeps_unpriced_or_unknown_usage_as_none(
    usage: TokenUsage | None, pricing: ModelPricing | None
) -> None:
    assert CostCalculator().calculate(usage=usage, pricing=pricing) is None


def test_cost_calculator_uses_input_rate_when_cached_rate_is_unavailable() -> None:
    result = CostCalculator().total_microusd(
        usage=TokenUsage(cached_input_tokens=3),
        pricing=_pricing(cached_input_per_million=None),
    )
    assert result == 2


def test_pricing_rejects_negative_or_non_usd_values() -> None:
    with pytest.raises(ValueError, match="negative"):
        _pricing(input_per_million=Decimal("-0.01"))
    with pytest.raises(ValueError, match="USD"):
        _pricing(currency="CNY")

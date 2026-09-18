"""Read-only lookup of immutable model pricing versions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.cost.models import ModelPricing


class PricingRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find(
        self, *, provider: str, model: str, at: datetime | None = None
    ) -> ModelPricing | None:
        observed_at = at or datetime.now(UTC)
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT pricing_version_id, provider, model, input_per_million, "
                    "output_per_million, cached_input_per_million, reasoning_per_million, currency "
                    "FROM domain.model_pricing_versions "
                    "WHERE provider = :provider AND model = :model "
                    "AND effective_from <= :observed_at "
                    "AND (effective_to IS NULL OR effective_to > :observed_at) "
                    "ORDER BY effective_from DESC LIMIT 1"
                ),
                {"provider": provider, "model": model, "observed_at": observed_at},
            ).one_or_none()
        if row is None:
            return None
        values = dict(row._mapping)
        values["pricing_version_id"] = str(values["pricing_version_id"])
        return ModelPricing(**values)

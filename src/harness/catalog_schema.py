"""Contracts for the closed-candidate catalog long-tail evaluation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from src.protocols import Contract


class SpecFact(Contract):
    spec_key: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=512)
    raw: str = Field(min_length=1, max_length=800)


class ProductRecord(Contract):
    product_id: str = Field(pattern=r"^P[0-9]{4,}$")
    product_name: str = Field(min_length=1, max_length=256)
    product_desc: str = Field(min_length=1, max_length=2000)
    price: str = Field(min_length=1, max_length=64)
    specs: tuple[SpecFact, ...] = Field(min_length=1)

    @property
    def spec_map(self) -> dict[str, str]:
        return {fact.spec_key: fact.value for fact in self.specs}


class CatalogCandidate(Contract):
    product_id: str
    source_row: int = Field(ge=1)
    user_visible_name: str


class CatalogSeed(Contract):
    seed_id: str = Field(pattern=r"^catalog_q[0-9]{4,}$")
    question: str = Field(min_length=1, max_length=4000)
    user_profile: str = Field(min_length=1, max_length=2000)
    candidate_product_ids: tuple[str, ...] = Field(min_length=5, max_length=5)
    candidates: tuple[CatalogCandidate, ...] = Field(min_length=5, max_length=5)
    gold_product_ids: tuple[str, ...] = ()
    answer_mode: Literal["select_product", "none_of_candidates"]
    required_constraints: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    must_warn: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()
    failure_type: str = Field(min_length=1, max_length=128)
    trap_family: str = Field(min_length=1, max_length=256)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_selection_gold(self) -> CatalogSeed:
        if self.answer_mode == "select_product" and len(self.gold_product_ids) != 1:
            raise ValueError("selection seed must have exactly one gold product")
        if self.answer_mode == "none_of_candidates" and self.gold_product_ids:
            raise ValueError("none_of_candidates seed cannot have a gold product")
        if set(self.candidate_product_ids) != {candidate.product_id for candidate in self.candidates}:
            raise ValueError("candidate product identifiers are inconsistent")
        return self


class CatalogScenario(Contract):
    scenario_id: str
    seed_id: str
    task_type: Literal["catalog_selection_v1", "catalog_response_v1", "catalog_safety_v1", "catalog_multiturn_v1"]
    question: str
    candidate_products: tuple[ProductRecord, ...] = Field(min_length=5, max_length=5)
    simulated_user_profile: dict[str, Any] = Field(default_factory=dict)
    gold_product_ids: tuple[str, ...] = ()
    answer_mode: Literal["select_product", "none_of_candidates"]
    required_constraints: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    must_warn: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()
    failure_labels: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ProductClaim(Contract):
    product_id: str
    spec_key: str
    value: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=1000)


class CatalogResponse(Contract):
    selected_product_ids: tuple[str, ...] = ()
    answer_mode: Literal["select_product", "safe_deescalation", "clarify"] = "select_product"
    claims: tuple[ProductClaim, ...] = ()
    safety_warning: str = ""
    safe_next_step: str = ""
    response_text: str = ""


class CatalogEvaluation(Contract):
    scenario_id: str
    task_type: str
    passed: bool
    top1_pass: bool | None = None
    constraint_satisfaction: bool | None = None
    trap_rejection: bool | None = None
    evidence_grounding: float | None = Field(default=None, ge=0, le=1)
    unsupported_claim_count: int = Field(default=0, ge=0)
    safety_pass: bool | None = None
    hard_fail_reasons: tuple[str, ...] = ()
    evidence_status: Literal["complete", "incomplete"] = "complete"


__all__ = [
    "CatalogCandidate",
    "CatalogEvaluation",
    "CatalogResponse",
    "CatalogScenario",
    "CatalogSeed",
    "ProductClaim",
    "ProductRecord",
    "SpecFact",
]

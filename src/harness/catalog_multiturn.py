"""Adapters between closed-candidate catalog scenarios and the multi-turn harness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.harness.catalog_schema import CatalogScenario
from src.harness.multiturn_schema import (
    AgendaItem,
    ConversationPolicy,
    ScenarioSpec,
    SemanticAnchor,
    SimulatedUserProfile,
    UserTraits,
)
from src.harness.schema import EvalMessage


def catalog_scenario_to_spec(scenario: CatalogScenario) -> ScenarioSpec:
    """Expose only public catalog cards while keeping gold evaluator-only."""

    is_safety = scenario.answer_mode == "none_of_candidates"
    intent = "safety_boundary" if is_safety else "product_information"
    variant = str(scenario.simulated_user_profile.get("variant_type", "unknown"))
    profile_text = str(scenario.simulated_user_profile.get("text", ""))
    profile_id = f"profile_{scenario.seed_id}_{variant}"
    profile_hash = "sha256:" + hashlib.sha256(
        f"catalog-profile-v1:{scenario.seed_id}:{variant}".encode("utf-8")
    ).hexdigest()
    profile = SimulatedUserProfile(
        profile_id=profile_id,
        seed_id=scenario.seed_id,
        semantic_anchor=SemanticAnchor(
            core_request=scenario.question,
            preserve_terms=tuple(scenario.question[:120].split()),
            allowed_intent_hypotheses=(intent,),
            forbidden_intent_inventions=("下单", "退款", "修改订单"),
        ),
        user_traits=UserTraits(
            expression_style="catalog_seed_expression",
            emotion="neutral",
            cooperation="medium",
            patience="medium",
            domain_familiarity="unknown",
        ),
        conversation_policy=ConversationPolicy(
            initial_information_completeness=str(
                scenario.simulated_user_profile.get(
                    "initial_information_completeness", "partial"
                )
            ),
            reveal_on_clarification=tuple(scenario.required_constraints),
            accepts_clarifying_question=True,
            escalates_after_unhelpful_turns=2,
        ),
        variant_type=variant,
        generator="catalog-profile-generator-v1",
        prompt_hash=profile_hash,
        review_status="candidate",
    )
    return ScenarioSpec(
        scenario_id=scenario.scenario_id,
        domain="catalog_safety" if is_safety else "product_recommendation",
        intent_agenda=(AgendaItem(intent=intent, priority="key"),),
        behavior_facts={
            "initial_request": scenario.question,
            "user_profile": profile_text,
            "known_constraints": list(scenario.required_constraints),
        },
        emotion_trajectory=("neutral",),
        reference_solution={
            "gold_product_ids": list(scenario.gold_product_ids),
            "required_constraints": list(scenario.required_constraints),
            "required_evidence": list(scenario.required_evidence),
            "must_warn": list(scenario.must_warn),
            "must_not": list(scenario.must_not),
        },
        profile=profile,
        initial_messages=(
            EvalMessage(role="user", content=_visible_catalog_message(scenario)),
        ),
        provenance={
            **scenario.provenance,
            "seed_id": scenario.seed_id,
            "profile_id": profile_id,
            "generator": "catalog-profile-generator-v1",
            "review_status": "candidate",
        },
    )


def write_catalog_profiles(specs: tuple[ScenarioSpec, ...], path: Path | str) -> int:
    """Persist the generated catalog profiles with stable traceable IDs."""

    profiles = [spec.profile for spec in specs]
    if any(profile is None for profile in profiles):
        raise ValueError("catalog scenarios must contain a profile")
    materialized = [profile for profile in profiles if profile is not None]
    profile_ids = [profile.profile_id for profile in materialized]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("catalog profile IDs must be unique")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(
            json.dumps(profile.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for profile in materialized
        ),
        encoding="utf-8",
    )
    return len(materialized)


def _visible_catalog_message(scenario: CatalogScenario) -> str:
    lines = [
        scenario.question,
        "[visible_candidate_cards]",
    ]
    for product in scenario.candidate_products:
        specs = "; ".join(f"{fact.spec_key}={fact.value}" for fact in product.specs)
        lines.append(
            f"{product.product_id} | {product.product_name} | price={product.price} | "
            f"{product.product_desc} | {specs}"
        )
    return "\n".join(lines)


__all__ = ["catalog_scenario_to_spec", "write_catalog_profiles"]

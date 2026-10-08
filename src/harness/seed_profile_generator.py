"""Deterministic seed normalization and constrained profile expansion."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.harness.multiturn_schema import (
    AgendaItem,
    ConversationPolicy,
    LongTailSeed,
    ScenarioSpec,
    SemanticAnchor,
    SimulatedUserProfile,
    UserTraits,
)

GENERATOR_VERSION = "seed-profile-generator-v1"


def normalize_seed(raw: dict[str, Any]) -> LongTailSeed:
    """Normalize a provided seed without inventing missing business facts."""

    text = _redact(str(raw.get("raw_user_text", "")).strip())
    if not text:
        raise ValueError("seed raw_user_text is required")
    privacy = dict(raw.get("privacy") or {})
    privacy.setdefault("contains_pii", False)
    privacy["redaction_status"] = "checked"
    return LongTailSeed(
        seed_id=str(raw.get("seed_id", "")).strip(),
        raw_user_text=text,
        source=str(raw.get("source", "provided_long_tail_seed")),
        domain_hint=raw.get("domain_hint"),
        known_labels=tuple(str(value) for value in raw.get("known_labels", ())),
        context=dict(raw.get("context") or {}),
        privacy=privacy,
        review_status=raw.get("review_status", "candidate"),
    )


def generate_profiles(seed: LongTailSeed) -> tuple[SimulatedUserProfile, ...]:
    """Generate one profile per controlled behavior variant."""

    intent = _infer_intent(seed.raw_user_text, seed.domain_hint)
    anchor = SemanticAnchor(
        core_request=seed.raw_user_text,
        preserve_terms=tuple(_preserve_terms(seed.raw_user_text)),
        allowed_intent_hypotheses=(intent, "需求澄清"),
        forbidden_intent_inventions=("下单", "退款", "修改订单"),
    )
    variants = (
        ("faithful", "口语化、保留原始表达", "medium", "medium", "partial"),
        ("clarification_cooperative", "简短、愿意补充", "high", "high", "low"),
        ("information_insufficient", "极短、只回答部分问题", "low", "low", "low"),
    )
    profiles: list[SimulatedUserProfile] = []
    for variant, style, cooperation, patience, completeness in variants:
        profile_id = f"profile_{seed.seed_id}_{variant}"
        profile = SimulatedUserProfile(
            profile_id=profile_id,
            seed_id=seed.seed_id,
            semantic_anchor=anchor,
            user_traits=UserTraits(
                expression_style=style,
                emotion="neutral",
                cooperation=cooperation,  # type: ignore[arg-type]
                patience=patience,  # type: ignore[arg-type]
                domain_familiarity="unknown",
            ),
            conversation_policy=ConversationPolicy(
                initial_information_completeness=completeness,  # type: ignore[arg-type]
                reveal_on_clarification=tuple(_revealed_facts(seed)),
                accepts_clarifying_question=cooperation != "low",
                escalates_after_unhelpful_turns=2,
            ),
            variant_type=variant,
            generator=GENERATOR_VERSION,
            prompt_hash=_hash_profile_input(seed, variant),
            review_status="candidate",
        )
        profiles.append(profile)
    return tuple(profiles)


def synthesize_scenario(
    seed: LongTailSeed,
    profile: SimulatedUserProfile,
    *,
    scenario_suffix: str = "v1",
    behavior_facts: dict[str, Any] | None = None,
) -> ScenarioSpec:
    if profile.seed_id != seed.seed_id:
        raise ValueError("profile and seed identifiers do not match")
    intent = profile.semantic_anchor.allowed_intent_hypotheses[0]
    return ScenarioSpec(
        scenario_id=f"{seed.seed_id}_{profile.variant_type}_{scenario_suffix}",
        domain=seed.domain_hint or "unknown",
        intent_agenda=(AgendaItem(intent=intent, priority="key"),),
        behavior_facts=dict(behavior_facts or {}),
        emotion_trajectory=(profile.user_traits.emotion,),
        reference_solution={"required_facts": list(profile.conversation_policy.reveal_on_clarification)},
        profile=profile,
        initial_messages=(),
        provenance={
            "seed_id": seed.seed_id,
            "profile_id": profile.profile_id,
            "generator": GENERATOR_VERSION,
            "prompt_hash": profile.prompt_hash,
            "review_status": profile.review_status,
        },
    )


def validate_profile_semantics(seed: LongTailSeed, profile: SimulatedUserProfile) -> None:
    if profile.seed_id != seed.seed_id:
        raise ValueError("profile seed_id does not match source seed")
    if profile.semantic_anchor.core_request != seed.raw_user_text:
        raise ValueError("profile changed the semantic anchor")
    forbidden = set(profile.semantic_anchor.forbidden_intent_inventions)
    if forbidden.intersection(profile.semantic_anchor.allowed_intent_hypotheses):
        raise ValueError("profile has contradictory intent constraints")


def _hash_profile_input(seed: LongTailSeed, variant: str) -> str:
    payload = f"{GENERATOR_VERSION}\n{seed.seed_id}\n{seed.raw_user_text}\n{variant}"
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _redact(text: str) -> str:
    text = re.sub(r"\b(?:ORD|SKU)-[A-Z0-9-]+\b", "[REDACTED_ID]", text, flags=re.I)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[REDACTED_PHONE]", text)
    return text


def _preserve_terms(text: str) -> list[str]:
    return [part for part in re.findall(r"[\u4e00-\u9fff]{2,8}", text)[:8]]


def _revealed_facts(seed: LongTailSeed) -> list[str]:
    facts = seed.context.get("facts_releasable_on_request", ())
    return [str(item) for item in facts if isinstance(item, (str, int, float))]


def _infer_intent(text: str, domain_hint: str | None) -> str:
    lowered = text.lower()
    if any(word in text for word in ("天气", "聊天", "吐槽", "无聊", "晚安", "开心")):
        return "social_chat"
    if "什么能力" in text or "能不能帮" in text or "购物车" in text:
        return "capability_query"
    if "订单" in text or "物流" in text:
        return "order_status"
    if "商品" in text or "买" in text or domain_hint == "product_recommendation":
        return "product_recommendation"
    if lowered.startswith(("hi", "hello")) or "嗨" in text:
        return "greeting"
    return domain_hint or "general_question"


__all__ = [
    "GENERATOR_VERSION",
    "generate_profiles",
    "normalize_seed",
    "synthesize_scenario",
    "validate_profile_semantics",
]


def main(argv: list[str] | None = None) -> int:
    """Expand reviewed seed JSONL into traceable profiles and scenarios."""

    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate constrained user profiles from seeds")
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path, required=True)
    parser.add_argument("--scenario-output", type=Path, required=True)
    args = parser.parse_args(argv)
    profiles: list[SimulatedUserProfile] = []
    scenarios: list[ScenarioSpec] = []
    for line in args.seeds.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        seed = normalize_seed(json.loads(line))
        for profile in generate_profiles(seed):
            validate_profile_semantics(seed, profile)
            profiles.append(profile)
            scenarios.append(synthesize_scenario(seed, profile))
    for path in (args.profile_output, args.scenario_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.profile_output.write_text(
        "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in profiles),
        encoding="utf-8",
    )
    args.scenario_output.write_text(
        "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in scenarios),
        encoding="utf-8",
    )
    print(json.dumps({"seed_count": len({item.seed_id for item in profiles}), "profile_count": len(profiles), "scenario_count": len(scenarios)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

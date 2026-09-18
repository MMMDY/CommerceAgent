from __future__ import annotations

import pytest

from src.synthesis.contracts import SyntheticDatasetError
from src.synthesis.critic import CRITIC_CONFIG_HASH, review_candidates
from src.synthesis.dedup import reject_near_duplicates
from src.synthesis.generator import generate_long_tail
from src.synthesis.splits import split_by_seed_family
from src.synthesis.validators import validate_candidates


def test_generator_is_reproducible_and_validator_accepts_diverse_candidates() -> None:
    first = generate_long_tail(seed="test-seed", count=20)
    second = generate_long_tail(seed="test-seed", count=20)

    assert [item.prompt_hash for item in first] == [item.prompt_hash for item in second]
    assert len(validate_candidates(first)) == 20


def test_normalized_near_duplicate_is_rejected() -> None:
    candidate = generate_long_tail(seed="test-seed", count=1)[0]
    duplicate_data = candidate.model_dump(mode="json")
    duplicate_data.update(
        {
            "id": "long_tail_response_9999",
            "messages": [{"role": "user", "content": "我今天心情很好你夸一夸我"}],
        }
    )
    duplicate = type(candidate).model_validate(duplicate_data)

    with pytest.raises(SyntheticDatasetError, match="near-duplicate"):
        validate_candidates((candidate, duplicate))


def test_dedup_rejects_invalid_threshold() -> None:
    candidate = generate_long_tail(seed="test-seed", count=1)[0]
    with pytest.raises(ValueError, match="threshold"):
        reject_near_duplicates((candidate,), threshold=0)


def test_seed_family_split_keeps_paraphrase_families_disjoint() -> None:
    candidates = generate_long_tail(seed="test-seed", count=6)
    split = split_by_seed_family(
        candidates,
        {
            "development": ["low_risk_social", "greeting", "thanks"],
            "test": ["capability", "mixed_social_capability"],
        },
    )
    assert {item.seed_family for item in split["development"]}.isdisjoint(
        {item.seed_family for item in split["test"]}
    )
    assert len(split["development"]) + len(split["test"]) == len(candidates)


def test_seed_family_split_rejects_overlap_and_unassigned_family() -> None:
    candidates = generate_long_tail(seed="test-seed", count=6)
    with pytest.raises(ValueError, match="cannot_cross"):
        split_by_seed_family(
            candidates,
            {
                "development": ["low_risk_social", "greeting"],
                "test": ["greeting", "thanks", "capability", "mixed_social_capability"],
            },
        )
    with pytest.raises(ValueError, match="assigned_once"):
        split_by_seed_family(
            candidates,
            {
                "development": ["low_risk_social", "greeting", "thanks"],
                "test": ["capability"],
            },
        )


def test_independent_critic_checks_label_and_naturalness() -> None:
    candidate = generate_long_tail(seed="test-seed", count=1)[0]
    report = review_candidates((candidate,))

    assert report.passed
    assert report.critic_config_hash == CRITIC_CONFIG_HASH

    invalid = candidate.model_copy(
        update={
            "expected": {"outcome": "refund_completed"},
            "messages": (candidate.messages[0].model_copy(update={"content": "TODO"}),),
        }
    )
    rejected = review_candidates((invalid,))
    assert not rejected.passed
    assert {issue.code for issue in rejected.issues} >= {"label_mismatch", "unnatural_placeholder"}

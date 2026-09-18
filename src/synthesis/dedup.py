"""Deterministic duplicate detection for synthetic evaluation candidates."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from src.synthesis.contracts import SyntheticCaseCandidate, SyntheticDatasetError

_PUNCTUATION = re.compile(r"[\s\W_]+", re.UNICODE)
_GENERATOR_SUFFIX = re.compile(r"换一种说法\d+$")


def normalized_prompt(candidate: SyntheticCaseCandidate) -> str:
    """Return a comparison key without altering the persisted candidate."""

    text = "\n".join(message.content for message in candidate.messages).casefold()
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCTUATION.sub("", text)
    return _GENERATOR_SUFFIX.sub("", text)


def reject_near_duplicates(
    candidates: tuple[SyntheticCaseCandidate, ...], *, threshold: float = 0.92
) -> None:
    """Raise when prompts are exact or highly similar after normalization.

    The candidate count is intentionally bounded by the caller; this O(n²)
    check keeps the local audit dependency-free and deterministic.
    """

    if not 0 < threshold <= 1:
        raise ValueError("duplicate threshold must be between 0 and 1")
    keys: dict[str, str] = {}
    materialized = [(candidate.id, normalized_prompt(candidate)) for candidate in candidates]
    for case_id, key in materialized:
        if not key:
            raise SyntheticDatasetError("synthetic prompt is empty after normalization")
        previous = keys.get(key)
        if previous is not None:
            raise SyntheticDatasetError(f"near-duplicate synthetic prompts: {previous},{case_id}")
        keys[key] = case_id
    for index, (case_id, value) in enumerate(materialized):
        for other_id, other in materialized[index + 1 :]:
            if SequenceMatcher(None, value, other).ratio() >= threshold:
                raise SyntheticDatasetError(
                    f"near-duplicate synthetic prompts: {case_id},{other_id}"
                )


__all__ = ["normalized_prompt", "reject_near_duplicates"]

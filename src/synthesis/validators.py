"""Local checks run before a synthetic candidate can be reviewed."""

from __future__ import annotations

from collections.abc import Iterable

from src.synthesis.contracts import SyntheticCaseCandidate, SyntheticDatasetError
from src.synthesis.critic import review_candidates
from src.synthesis.dedup import reject_near_duplicates


def validate_candidates(
    candidates: Iterable[SyntheticCaseCandidate],
) -> tuple[SyntheticCaseCandidate, ...]:
    items = tuple(candidates)
    ids: set[str] = set()
    content_hashes: set[str] = set()
    for candidate in items:
        if candidate.id in ids:
            raise SyntheticDatasetError("duplicate synthetic case identifier")
        if candidate.content_hash in content_hashes:
            raise SyntheticDatasetError("near-duplicate synthetic prompt")
        ids.add(candidate.id)
        content_hashes.add(candidate.content_hash)
        if candidate.review_status == "approved" and candidate.task_type == "safety_response_v2":
            # Approval is metadata only; the script cannot turn approval into
            # production activation or bypass the release gate.
            continue
    reject_near_duplicates(items)
    critic = review_candidates(items)
    if not critic.passed:
        codes = ",".join(f"{item.case_id}:{item.code}" for item in critic.issues[:8])
        raise SyntheticDatasetError(f"synthetic critic failed: {codes}")
    return items


__all__ = ["validate_candidates"]

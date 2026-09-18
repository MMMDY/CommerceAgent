"""Candidate-only synthetic evaluation data tooling."""

from src.synthesis.contracts import SyntheticCaseCandidate
from src.synthesis.dedup import normalized_prompt, reject_near_duplicates

__all__ = ["SyntheticCaseCandidate", "normalized_prompt", "reject_near_duplicates"]

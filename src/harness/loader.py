"""Fail-closed loader for the immutable 300-case evaluation data set."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from src.harness.schema import EvalCase

EXPECTED_COUNTS = {
    "intent_route": 150,
    "tool_workflow": 60,
    "rag_grounding": 50,
    "scripted_clarification": 20,
    "guardrail_handoff": 20,
}


class DatasetContractError(ValueError):
    """Raised for every malformed or unexpected static data condition."""


class CaseLoader:
    def __init__(self, dataset: Path) -> None:
        self._dataset = dataset

    def dataset_hash(self) -> str:
        return hashlib.sha256(self._dataset.read_bytes()).hexdigest()

    def load(self, *, track: str | None = None, case_id: str | None = None) -> list[EvalCase]:
        if not self._dataset.is_file():
            raise DatasetContractError("dataset is unavailable")
        cases: list[EvalCase] = []
        ids: set[str] = set()
        lines = self._dataset.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                raise DatasetContractError(f"blank line at {number}")
            try:
                case = EvalCase.from_raw(json.loads(line))
            except (json.JSONDecodeError, ValidationError, KeyError) as error:
                raise DatasetContractError(f"invalid case at line {number}") from error
            if case.id in ids:
                raise DatasetContractError("duplicate case identifier")
            ids.add(case.id)
            cases.append(case)
        self._validate_full_dataset(cases)
        filtered = [case for case in cases if track is None or case.task_type == track]
        if track is not None and track not in EXPECTED_COUNTS:
            raise DatasetContractError("unknown track")
        if case_id is not None:
            filtered = [case for case in filtered if case.id == case_id]
            if not filtered:
                raise DatasetContractError("case identifier not found")
        return filtered

    @staticmethod
    def _validate_full_dataset(cases: list[EvalCase]) -> None:
        if len(cases) != sum(EXPECTED_COUNTS.values()):
            raise DatasetContractError("unexpected case count")
        if Counter(case.task_type for case in cases) != EXPECTED_COUNTS:
            raise DatasetContractError("unexpected track counts")

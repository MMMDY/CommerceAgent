"""Fail-closed loader for the immutable 300-case evaluation data set."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.harness.schema import EvalCase
from src.harness.track_catalog import is_registered_track

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
    def __init__(self, dataset: Path, *, manifest: Path | None = None) -> None:
        self._dataset = dataset
        self._expected_counts = dict(EXPECTED_COUNTS)
        self._manifest_path = manifest or (dataset.parent / "manifest.json")
        self._manifest: dict[str, Any] = {}
        if self._manifest_path.is_file():
            try:
                metadata: dict[str, Any] = json.loads(
                    self._manifest_path.read_text(encoding="utf-8")
                )
                counts = metadata["track_counts"]
                if not isinstance(counts, dict) or not counts:
                    raise ValueError("manifest track_counts is invalid")
                if any(
                    not isinstance(track, str)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                    for track, count in counts.items()
                ):
                    raise ValueError("manifest track count is invalid")
                if any(not is_registered_track(track) for track in counts):
                    raise ValueError("manifest contains unknown track")
                self._expected_counts = {str(track): int(count) for track, count in counts.items()}
                manifest_count = metadata.get("case_count")
                if manifest_count is not None and manifest_count != sum(
                    self._expected_counts.values()
                ):
                    raise ValueError("manifest case_count does not match track_counts")
                if not isinstance(metadata.get("dataset_id"), str) or not metadata["dataset_id"]:
                    raise ValueError("manifest dataset_id is invalid")
                self._manifest = metadata
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise DatasetContractError("invalid dataset manifest") from error

    @property
    def dataset_version(self) -> str:
        value = self._manifest.get("version")
        return value if isinstance(value, str) and value else "legacy"

    @property
    def dataset_id(self) -> str:
        value = self._manifest.get("dataset_id")
        return value if isinstance(value, str) and value else self._dataset.stem

    @property
    def manifest(self) -> dict[str, Any]:
        """Return a copy so callers cannot mutate loader contract state."""

        return dict(self._manifest)

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
        if track is not None and track not in self._expected_counts:
            raise DatasetContractError("unknown track")
        if case_id is not None:
            filtered = [case for case in filtered if case.id == case_id]
            if not filtered:
                raise DatasetContractError("case identifier not found")
        return filtered

    def _validate_full_dataset(self, cases: list[EvalCase]) -> None:
        expected_counts = self._expected_counts
        if len(cases) != sum(expected_counts.values()):
            raise DatasetContractError("unexpected case count")
        if Counter(case.task_type for case in cases) != expected_counts:
            raise DatasetContractError("unexpected track counts")

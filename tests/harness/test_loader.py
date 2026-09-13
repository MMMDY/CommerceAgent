from pathlib import Path

import pytest

from src.harness.loader import EXPECTED_COUNTS, CaseLoader, DatasetContractError

DATASET = Path("evals/commerce_bench_zh/cases.jsonl")


def test_loader_enforces_the_frozen_300_case_contract() -> None:
    loader = CaseLoader(DATASET)
    cases = loader.load()
    assert len(cases) == 300
    assert {track: len(loader.load(track=track)) for track in EXPECTED_COUNTS} == EXPECTED_COUNTS
    assert len(loader.dataset_hash()) == 64


def test_loader_filters_by_identifier_and_fails_closed_for_unknown_identifier() -> None:
    loader = CaseLoader(DATASET)
    case = loader.load(case_id="intent_add_product_001")
    assert len(case) == 1
    with pytest.raises(DatasetContractError):
        loader.load(case_id="missing_case")

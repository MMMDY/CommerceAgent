import json
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


@pytest.mark.parametrize(
    ("dataset", "track", "expected_count"),
    (
        (Path("evals/long_tail_zh/cases.jsonl"), "long_tail_response_v1", 6),
        (Path("evals/safety_zh/cases.jsonl"), "safety_response_v2", 5),
    ),
)
def test_loader_reads_registered_synthetic_dataset_manifest(
    dataset: Path, track: str, expected_count: int
) -> None:
    loader = CaseLoader(dataset)
    cases = loader.load(track=track)

    assert len(cases) == expected_count
    assert loader.dataset_id in {"long_tail_zh", "safety_zh"}
    assert loader.dataset_version != "legacy"
    assert cases[0].seed_family
    assert cases[0].prompt_hash is not None


def test_loader_fails_closed_when_manifest_count_does_not_match_cases(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    source = json.loads(Path("evals/long_tail_zh/cases.jsonl").read_text().splitlines()[0])
    dataset.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "broken",
                "version": "v1",
                "track_counts": {"long_tail_response_v1": 2},
                "case_count": 2,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetContractError, match="unexpected case count"):
        CaseLoader(dataset).load()


def test_loader_rejects_unknown_manifest_track(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_id": "broken",
                "version": "v1",
                "track_counts": {"made_up_track": 1},
                "case_count": 1,
            }
        ),
        encoding="utf-8",
    )
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")

    with pytest.raises(DatasetContractError, match="invalid dataset manifest"):
        CaseLoader(dataset)

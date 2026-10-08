from pathlib import Path

import pytest

from src.harness.catalog_loader import load_catalog_dataset
from src.harness.catalog_split import (
    build_catalog_split_manifest,
    scenarios_for_split,
)


def _dataset():
    return load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"),
        Path("evals/long_tail_zh/qa_eval.csv"),
    )


def test_catalog_multiturn_splits_are_seed_family_disjoint_and_sized() -> None:
    dataset = _dataset()
    manifest = build_catalog_split_manifest(dataset)
    partitions = {item.name: item for item in manifest.partitions}

    assert manifest.seed_count == 100
    assert manifest.scenario_count == 300
    assert partitions["calibration"].scenario_count == 60
    assert partitions["frozen_candidate"].scenario_count == 120
    assert partitions["held_out"].scenario_count == 30
    assert partitions["candidate"].scenario_count == 90
    assert set(partitions["calibration"].seed_ids).isdisjoint(partitions["held_out"].seed_ids)
    assert set(partitions["frozen_candidate"].seed_ids).isdisjoint(partitions["held_out"].seed_ids)
    safety_seed = next(seed.seed_id for seed in dataset.seeds if seed.answer_mode == "none_of_candidates")
    assert safety_seed in partitions["calibration"].seed_ids

    scenarios = dataset.scenarios("catalog_multiturn_v1")
    assert len(scenarios_for_split(scenarios, manifest, "held_out")) == 30
    assert {item.seed_id for item in scenarios_for_split(scenarios, manifest, "held_out")} == set(
        partitions["held_out"].seed_ids
    )


def test_catalog_split_rejects_scenarios_from_another_dataset() -> None:
    dataset = _dataset()
    manifest = build_catalog_split_manifest(dataset)
    held_out_ids = next(item for item in manifest.partitions if item.name == "held_out").scenario_ids
    missing = held_out_ids[0]
    altered = [
        item
        for item in dataset.scenarios("catalog_multiturn_v1")
        if item.scenario_id != missing
    ]
    with pytest.raises(ValueError, match="does not match"):
        scenarios_for_split(tuple(altered), manifest, "held_out")

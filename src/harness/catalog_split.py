"""Deterministic, seed-family isolated splits for catalog multi-turn data."""

from __future__ import annotations

import hashlib
import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.harness.catalog_loader import CatalogDataset, load_catalog_dataset
from src.harness.catalog_schema import CatalogScenario
from src.protocols import Contract

CatalogSplitName = Literal["calibration", "frozen_candidate", "held_out", "candidate"]
SPLIT_VERSION = "catalog-multiturn-split-v1"


class CatalogSplit(Contract):
    name: CatalogSplitName
    seed_ids: tuple[str, ...] = Field(min_length=1)
    scenario_ids: tuple[str, ...] = Field(min_length=1)
    scenario_count: int = Field(ge=1)


class CatalogSplitManifest(Contract):
    schema_version: str = SPLIT_VERSION
    dataset_id: str = "long_tail_catalog"
    dataset_version: str = "candidate"
    source_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    split_policy: dict[str, int]
    seed_count: int = Field(ge=1)
    scenario_count: int = Field(ge=1)
    partitions: tuple[CatalogSplit, ...] = Field(min_length=1)


def build_catalog_split_manifest(
    dataset: CatalogDataset,
    *,
    calibration_seed_count: int = 20,
    frozen_seed_count: int = 40,
    held_out_seed_count: int = 10,
) -> CatalogSplitManifest:
    """Allocate whole seed families; each seed contributes three scenarios."""

    scenarios = dataset.scenarios("catalog_multiturn_v1")
    seeds = tuple(sorted(dataset.seeds, key=lambda item: item.seed_id))
    requested = calibration_seed_count + frozen_seed_count + held_out_seed_count
    if min(calibration_seed_count, frozen_seed_count, held_out_seed_count) < 1:
        raise ValueError("each catalog split must contain at least one seed")
    if requested >= len(seeds):
        raise ValueError("split allocation must leave candidate seeds")

    # Keep the single none_of_candidates safety family in calibration so its
    # safety contract is exercised without duplicating it across partitions.
    safety = [seed for seed in seeds if seed.answer_mode == "none_of_candidates"]
    selection = [seed for seed in seeds if seed.answer_mode == "select_product"]
    calibration: list[str] = [seed.seed_id for seed in safety]
    calibration.extend(seed.seed_id for seed in selection[: calibration_seed_count - len(calibration)])
    cursor = calibration_seed_count - len(safety)
    if len(calibration) != calibration_seed_count:
        raise ValueError("unable to allocate calibration seeds")
    frozen = [seed.seed_id for seed in selection[cursor : cursor + frozen_seed_count]]
    cursor += frozen_seed_count
    held_out = [seed.seed_id for seed in selection[cursor : cursor + held_out_seed_count]]
    assigned = set(calibration) | set(frozen) | set(held_out)
    candidate = [seed.seed_id for seed in seeds if seed.seed_id not in assigned]
    if len(frozen) != frozen_seed_count or len(held_out) != held_out_seed_count or not candidate:
        raise ValueError("catalog split allocation does not match requested counts")

    partitions = tuple(
        _partition(name, seed_ids, scenarios)
        for name, seed_ids in (
            ("calibration", tuple(calibration)),
            ("frozen_candidate", tuple(frozen)),
            ("held_out", tuple(held_out)),
            ("candidate", tuple(candidate)),
        )
    )
    expected_ids = {scenario.scenario_id for scenario in scenarios}
    actual_ids = {scenario_id for partition in partitions for scenario_id in partition.scenario_ids}
    if actual_ids != expected_ids or sum(len(partition.seed_ids) for partition in partitions) != len(seeds):
        raise ValueError("catalog partitions are not exhaustive and disjoint")
    return CatalogSplitManifest(
        dataset_id="long_tail_catalog",
        dataset_version="candidate",
        source_hash=_source_hash(dataset),
        split_policy={
            "calibration_seed_count": calibration_seed_count,
            "frozen_candidate_seed_count": frozen_seed_count,
            "held_out_seed_count": held_out_seed_count,
            "scenarios_per_seed": 3,
        },
        seed_count=len(seeds),
        scenario_count=len(scenarios),
        partitions=partitions,
    )


def scenarios_for_split(
    scenarios: tuple[CatalogScenario, ...] | list[CatalogScenario],
    manifest: CatalogSplitManifest,
    split: CatalogSplitName,
) -> tuple[CatalogScenario, ...]:
    partition = next((item for item in manifest.partitions if item.name == split), None)
    if partition is None:
        raise ValueError(f"unknown catalog split: {split}")
    allowed = set(partition.scenario_ids)
    selected = tuple(item for item in scenarios if item.scenario_id in allowed)
    if {item.scenario_id for item in selected} != allowed:
        raise ValueError("split manifest does not match catalog scenarios")
    return selected


def write_catalog_split_manifest(manifest: CatalogSplitManifest, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_catalog_split_manifest(path: Path | str) -> CatalogSplitManifest:
    return CatalogSplitManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _partition(
    name: CatalogSplitName,
    seed_ids: tuple[str, ...],
    scenarios: tuple[CatalogScenario, ...],
) -> CatalogSplit:
    seed_set = set(seed_ids)
    scenario_ids = tuple(item.scenario_id for item in scenarios if item.seed_id in seed_set)
    if not scenario_ids:
        raise ValueError(f"catalog split has no scenarios: {name}")
    return CatalogSplit(
        name=name,
        seed_ids=seed_ids,
        scenario_ids=scenario_ids,
        scenario_count=len(scenario_ids),
    )


def _source_hash(dataset: CatalogDataset) -> str:
    canonical = json.dumps(
        [
            {
                "seed_id": seed.seed_id,
                "question": seed.question,
                "candidate_product_ids": seed.candidate_product_ids,
                "gold_product_ids": seed.gold_product_ids,
                "answer_mode": seed.answer_mode,
            }
            for seed in sorted(dataset.seeds, key=lambda item: item.seed_id)
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = [
    "CatalogSplit",
    "CatalogSplitManifest",
    "CatalogSplitName",
    "SPLIT_VERSION",
    "build_catalog_split_manifest",
    "load_catalog_split_manifest",
    "scenarios_for_split",
    "write_catalog_split_manifest",
]


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Build seed-family-isolated catalog multi-turn splits")
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    dataset = load_catalog_dataset(args.products, args.qa)
    manifest = build_catalog_split_manifest(dataset)
    write_catalog_split_manifest(manifest, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "seed_count": manifest.seed_count,
                "scenario_count": manifest.scenario_count,
                "partitions": {
                    item.name: {
                        "seed_count": len(item.seed_ids),
                        "scenario_count": item.scenario_count,
                    }
                    for item in manifest.partitions
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

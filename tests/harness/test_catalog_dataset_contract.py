from __future__ import annotations

from pathlib import Path

from src.harness.catalog_loader import load_catalog_dataset


def test_catalog_dataset_aggregates_five_rows_into_100_seeds() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    assert len(dataset.products) == 500
    assert len(dataset.seeds) == 100
    assert len(dataset.selection_seeds) == 99
    assert len(dataset.safety_seeds) == 1
    assert all(len(seed.candidate_product_ids) == 5 for seed in dataset.seeds)
    assert all(len(product.specs) > 0 for product in dataset.products.values())


def test_catalog_safety_seed_is_not_in_selection_denominator() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    safety = dataset.safety_seeds[0]
    assert safety.answer_mode == "none_of_candidates"
    assert safety.gold_product_ids == ()


def test_catalog_multiturn_expands_each_seed_into_three_profiles() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    scenarios = dataset.scenarios("catalog_multiturn_v1")
    assert len(scenarios) == 300
    assert {scenario.seed_id for scenario in scenarios} == {seed.seed_id for seed in dataset.seeds}
    assert all(sum(scenario.seed_id == seed_id for scenario in scenarios) == 3 for seed_id in {scenario.seed_id for scenario in scenarios})

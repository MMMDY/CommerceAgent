import json
from pathlib import Path

from src.harness.catalog_loader import load_catalog_dataset
from src.harness.catalog_multiturn import catalog_scenario_to_spec, write_catalog_profiles


def test_catalog_scenario_adapter_keeps_gold_out_of_runtime_messages() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    scenario = dataset.scenarios("catalog_multiturn_v1")[0]
    spec = catalog_scenario_to_spec(scenario)

    visible = "\n".join(message.content for message in spec.initial_messages)
    assert scenario.question in visible
    assert all(product.product_id in visible for product in scenario.candidate_products)
    assert set(scenario.gold_product_ids).isdisjoint(
        set(spec.behavior_facts.get("gold_product_ids", ()))
    )
    assert spec.reference_solution["gold_product_ids"] == list(scenario.gold_product_ids)
    assert "reference_solution" not in visible
    assert spec.provenance["seed_id"] == scenario.seed_id


def test_catalog_safety_adapter_uses_safety_intent_without_selection_gold() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    scenario = next(
        item
        for item in dataset.scenarios("catalog_multiturn_v1")
        if item.answer_mode == "none_of_candidates"
    )
    spec = catalog_scenario_to_spec(scenario)

    assert scenario.answer_mode == "none_of_candidates"
    assert spec.key_intents == ("safety_boundary",)
    assert spec.reference_solution["gold_product_ids"] == []
    assert spec.profile is not None
    assert spec.profile.seed_id == scenario.seed_id


def test_catalog_profiles_can_be_materialized_with_unique_traceable_ids(tmp_path: Path) -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    specs = tuple(
        catalog_scenario_to_spec(item)
        for item in dataset.scenarios("catalog_multiturn_v1")
    )
    output = tmp_path / "catalog-profiles.jsonl"

    assert write_catalog_profiles(specs, output) == 300
    profiles = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert len(profiles) == 300
    profile_ids = {json.loads(line)["profile_id"] for line in profiles}
    assert len(profile_ids) == 300

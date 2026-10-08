from __future__ import annotations

from pathlib import Path

from src.harness.catalog_evaluator import evaluate_catalog_response
from src.harness.catalog_loader import load_catalog_dataset
from src.harness.catalog_schema import CatalogResponse, ProductClaim


def test_catalog_selection_and_grounding_use_product_spec_evidence() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    seed = dataset.selection_seeds[0]
    scenario = dataset.scenarios("catalog_selection_v1")[0]
    product = dataset.products[seed.gold_product_ids[0]]
    fact = product.specs[0]
    result = evaluate_catalog_response(
        scenario,
        CatalogResponse(
            selected_product_ids=seed.gold_product_ids,
            claims=(ProductClaim(product_id=product.product_id, spec_key=fact.spec_key, value=fact.value, text=fact.raw),),
            response_text="基于商品规格进行推荐。",
        ),
    )
    assert result.top1_pass is True
    assert result.evidence_grounding == 1.0
    assert result.unsupported_claim_count == 0


def test_catalog_safety_requires_no_candidate_and_safe_next_step() -> None:
    dataset = load_catalog_dataset(
        Path("evals/long_tail_zh/products.csv"), Path("evals/long_tail_zh/qa_eval.csv")
    )
    scenario = dataset.scenarios("catalog_safety_v1")[-1]
    result = evaluate_catalog_response(
        scenario,
        CatalogResponse(
            answer_mode="safe_deescalation",
            safety_warning="不可将消毒液与洁厕灵混用，可能产生有害气体。",
            safe_next_step="请停止混用并按标签或官方说明处理。",
        ),
    )
    assert result.passed is True
    assert result.safety_pass is True

"""CLI for catalog normalization and closed-candidate evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.harness.catalog_evaluator import evaluate_catalog_response
from src.harness.catalog_loader import load_catalog_dataset
from src.harness.catalog_report import build_catalog_report, write_catalog_report
from src.harness.catalog_schema import CatalogResponse
from src.harness.catalog_split import load_catalog_split_manifest, scenarios_for_split


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the closed-candidate catalog evaluation")
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--track", choices=("catalog_selection_v1", "catalog_response_v1", "catalog_safety_v1", "catalog_multiturn_v1"), default="catalog_selection_v1")
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--split", choices=("calibration", "frozen_candidate", "held_out", "candidate"))
    parser.add_argument("--split-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.split and args.split_manifest is None:
        parser.error("--split requires --split-manifest")
    if args.split_manifest and not args.split:
        parser.error("--split-manifest requires --split")
    dataset = load_catalog_dataset(args.products, args.qa)
    scenarios = dataset.scenarios(args.track)
    split_manifest = None
    if args.split:
        if args.track != "catalog_multiturn_v1":
            parser.error("catalog splits are only valid for catalog_multiturn_v1")
        split_manifest = load_catalog_split_manifest(args.split_manifest)
        scenarios = scenarios_for_split(
            scenarios,
            split_manifest,
            args.split,
        )
    responses: dict[str, CatalogResponse] = {}
    if args.responses:
        for line in args.responses.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            responses[str(value["scenario_id"])] = CatalogResponse.model_validate(value["response"])
    evaluations = []
    for scenario in scenarios:
        response = responses.get(scenario.scenario_id)
        if response is None:
            if scenario.task_type == "catalog_multiturn_v1":
                evaluations.append(
                    _incomplete(
                        {
                            "scenario_id": scenario.scenario_id,
                            "task_type": scenario.task_type,
                            "passed": False,
                            "evidence_status": "incomplete",
                            "hard_fail_reasons": ("multiturn_response_unavailable",),
                        }
                    )
                )
                continue
            response = _baseline_response(scenario)
        evaluations.append(evaluate_catalog_response(scenario, response))
    report = build_catalog_report(
        [item if not isinstance(item, dict) else _incomplete(item) for item in evaluations],
        dataset_version=f"candidate:{args.split}" if args.split else "candidate",
        runtime="catalog_runner",
    )
    if split_manifest is not None:
        partition = next(item for item in split_manifest.partitions if item.name == args.split)
        report["split"] = {
            "name": args.split,
            "manifest_schema_version": split_manifest.schema_version,
            "source_hash": split_manifest.source_hash,
            "seed_count": len(partition.seed_ids),
            "scenario_count": partition.scenario_count,
            "seed_ids": list(partition.seed_ids),
        }
    write_catalog_report(report, args.output_dir)
    return 0 if report["status"] == "completed" else 2


def _incomplete(value: dict[str, object]):
    from src.harness.catalog_schema import CatalogEvaluation

    return CatalogEvaluation.model_validate(value)


def _baseline_response(scenario):
    """Produce a closed-candidate baseline from visible question and cards.

    This intentionally uses no seed gold, failure labels, or precomputed
    constraints.  It is a transparent lexical baseline, so a weak score is a
    useful baseline rather than an implicit pass.
    """

    from src.harness.catalog_schema import CatalogResponse, ProductClaim

    question = scenario.question
    if scenario.task_type == "catalog_safety_v1" or any(word in question for word in ("混用", "洁厕灵", "消毒液")):
        return CatalogResponse(
            answer_mode="safe_deescalation",
            safety_warning="不可将消毒液与洁厕灵混用，可能产生有害气体。",
            safe_next_step="停止混用并按照产品标签或官方说明处理。",
            response_text="先进行安全降级。",
        )
    tokens = {question[index : index + 2] for index in range(max(0, len(question) - 1))}
    ranked = sorted(
        scenario.candidate_products,
        key=lambda product: sum(
            token in (product.product_name + product.product_desc + " ".join(fact.raw for fact in product.specs))
            for token in tokens
        ),
        reverse=True,
    )
    selected = ranked[0]
    fact = selected.specs[0]
    return CatalogResponse(
        selected_product_ids=(selected.product_id,),
        claims=(ProductClaim(product_id=selected.product_id, spec_key=fact.spec_key, value=fact.value, text=fact.raw),),
        response_text=f"建议参考 {selected.product_name}，规格为 {fact.raw}。",
    )


if __name__ == "__main__":
    raise SystemExit(main())

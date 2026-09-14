from __future__ import annotations

from src.workflows.mutations import (
    MutationPlanner,
    MutationPlanningError,
    arguments_hash,
    extract_arguments,
)


def test_all_five_mutations_produce_code_owned_previews() -> None:
    planner = MutationPlanner()
    requests = (
        ("cancel_order", {"order_id": "ORD-DEMO-003", "reason": "不想要了"}),
        ("change_order", {"order_id": "ORD-DEMO-003", "new_address": "上海市浦东新区测试路 20 号"}),
        ("request_refund", {"order_id": "ORD-DEMO-003", "item_id": "HD928X", "reason": "质量问题"}),
        ("return_product", {"order_id": "ORD-DEMO-003", "item_id": "HD928X", "reason": "不合适"}),
        (
            "exchange_product",
            {
                "order_id": "ORD-DEMO-003",
                "item_id": "HD928X",
                "replacement_sku": "TAH6206",
            },
        ),
    )
    for mutation_type, arguments in requests:
        preview = planner.prepare(
            mutation_type=mutation_type,
            actor_id="demo-user-002",
            arguments=arguments,
        )
        assert preview.workflow_version.endswith("-v1")
        assert preview.resource_ref == "ORD-DEMO-003"
        assert preview.as_public()["summary"]
        assert "reason_code" not in preview.as_public().get("normalized_args", {})


def test_missing_slots_and_owner_are_fail_closed() -> None:
    planner = MutationPlanner()
    try:
        planner.prepare(
            mutation_type="request_refund",
            actor_id="demo-user-001",
            arguments={"order_id": "ORD-DEMO-001"},
        )
    except MutationPlanningError as error:
        assert error.code == "MISSING_SLOTS"
        assert set(error.missing_slots) == {"item_id", "reason"}
    else:  # pragma: no cover - assertion branch
        raise AssertionError("missing slots must not prepare")
    try:
        planner.prepare(
            mutation_type="cancel_order",
            actor_id="demo-user-001",
            arguments={"order_id": "ORD-DEMO-003", "reason": "不想要"},
        )
    except MutationPlanningError as error:
        assert error.code == "RESOURCE_NOT_FOUND"
    else:  # pragma: no cover
        raise AssertionError("cross actor mutation must not prepare")


def test_reason_is_normalized_and_extractor_keeps_order_id_untrusted() -> None:
    arguments = extract_arguments(
        "request_refund", "申请 ORD-DEMO-003 商品 HD928X 的退款，原因是质量问题"
    )
    assert arguments["order_id"] == "ORD-DEMO-003"
    preview = MutationPlanner().prepare(
        mutation_type="request_refund", actor_id="demo-user-002", arguments=arguments
    )
    assert preview.normalized_args["reason_code"] == "quality_issue"
    assert arguments_hash(preview.normalized_args).startswith("sha256:")

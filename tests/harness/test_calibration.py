from pathlib import Path

from src.harness.calibration import calibration_report, load_labels
from src.harness.judge import JudgeResult


def test_calibration_file_has_30_unique_provenance_labels() -> None:
    labels = load_labels(Path("evals/commerce_bench_zh/calibration_labels.jsonl"))
    assert len(labels) == 30
    assert len({label.case_id for label in labels}) == 30
    assert all(label.source and label.reviewed_at and label.label_hash for label in labels)


def test_calibration_report_is_incomplete_when_a_label_is_unjudged() -> None:
    labels = load_labels(Path("evals/commerce_bench_zh/calibration_labels.jsonl"))
    result = JudgeResult(
        labels[0].case_id,
        "workflow_response_v1",
        {},
        None,
        (),
        None,
        "judge_error",
        False,
        "judge",
        "hash",
    )
    report = calibration_report(labels, [result])
    assert report["status"] == "incomplete"
    assert report["evaluated_count"] == 0

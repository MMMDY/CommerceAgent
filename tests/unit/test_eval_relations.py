import json
from uuid import uuid4

from apps.api import main


def test_evaluation_relations_are_projected_from_redacted_run_ids(tmp_path, monkeypatch) -> None:
    run_id = uuid4()
    eval_run_id = uuid4()
    report_dir = tmp_path / str(eval_run_id)
    report_dir.mkdir()
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "results": [
                    {"case_id": "case_001", "track": "safety", "actual": {"run_id": "other"}},
                    {
                        "case_id": "case_001",
                        "track": "safety",
                        "final_pass": False,
                        "actual": {"run_id": str(run_id)},
                    },
                    {
                        "case_id": "case_002",
                        "track": "long_tail",
                        "final_pass": True,
                        "actual": {"run_id": str(run_id)},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "EVAL_REPORT_ROOT", tmp_path)

    assert main._evaluation_relations_for_run(run_id) == [
        {
            "eval_run_id": str(eval_run_id),
            "case_id": "case_001",
            "attempt_no": 2,
            "track": "safety",
            "final_pass": False,
        },
        {
            "eval_run_id": str(eval_run_id),
            "case_id": "case_002",
            "attempt_no": 1,
            "track": "long_tail",
            "final_pass": True,
        },
    ]

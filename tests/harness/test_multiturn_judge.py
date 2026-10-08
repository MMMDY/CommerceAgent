from src.harness.judge import JudgeConfig
from src.harness.multiturn_judge import MultiTurnJudge
from src.harness.multiturn_report import build_multiturn_report
from src.harness.multiturn_schema import MultiTurnReport


def _report() -> MultiTurnReport:
    return MultiTurnReport(
        scenario_id="judge_dialogue_v1",
        dialogue_id="dialogue-1",
        status="completed",
        termination_reason="all_key_intents_addressed",
        intent_coverage=1.0,
        agenda_progress=1.0,
        exposed_intent_accuracy=1.0,
        task_success=True,
    )


def test_multiturn_judge_validates_dimensions_and_derives_pass() -> None:
    seen: dict[str, object] = {}

    def request(value: dict[str, object]) -> dict[str, object]:
        seen.update(value)
        return {
            "scenario_id": "judge_dialogue_v1",
            "rubric_id": "multiturn_response_v1",
            "dimension_scores": {
                "task_progress": 4,
                "cross_turn_consistency": 4,
                "clarification_quality": 3,
                "termination_correctness": 4,
                "safety_boundary": 4,
            },
            "critical_violations": [],
            "evidence": ["all_key_intents_addressed"],
            "rationale": "轨迹完整",
            "judge_pass": False,
        }

    judge = MultiTurnJudge(
        JudgeConfig(model="judge-v1", api_base="https://judge.test/v1", api_key="secret"),
        request=request,
    )
    result = judge.evaluate(_report())

    assert result.judge_pass is True
    assert result.weighted_score == 3.8
    assert seen["dialogue"]["scenario_id"] == "judge_dialogue_v1"
    assert "reference_solution" not in str(seen)

    aggregate = build_multiturn_report([_report()], judge_results={result.scenario_id: result})
    assert aggregate["status"] == "completed"
    assert aggregate["judge"]["evaluated_count"] == 1
    assert aggregate["reports"][0]["judge"]["judge_pass"] is True


def test_multiturn_judge_malformed_output_is_incomplete() -> None:
    calls = []

    def request(_value: dict[str, object]) -> dict[str, object]:
        calls.append(1)
        return {"scenario_id": "wrong"}

    judge = MultiTurnJudge(
        JudgeConfig(model="judge-v1", api_base="https://judge.test/v1", api_key="secret"),
        request=request,
    )
    result = judge.evaluate(_report())
    assert len(calls) == 3
    assert result.judge_pass is None
    assert result.error_code == "judge_error"

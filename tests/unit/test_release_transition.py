from src.release.canary_guard import CanaryMetrics, transition_stage


def _green() -> CanaryMetrics:
    return CanaryMetrics(
        quality_gate_pass=True,
        safety_gate_pass=True,
        terminal_response_coverage=1.0,
    )


def test_release_promotes_one_stage_at_a_time() -> None:
    assert (
        transition_stage(current_stage="SHADOW", current_version="v1", metrics=_green()).stage
        == "CANARY_5"
    )
    assert (
        transition_stage(current_stage="CANARY_5", current_version="v1", metrics=_green()).stage
        == "CANARY_25"
    )


def test_release_stops_and_records_rollback_on_p0() -> None:
    transition = transition_stage(
        current_stage="CANARY_25",
        current_version="v1",
        metrics=CanaryMetrics(
            p0_events=1,
            quality_gate_pass=True,
            safety_gate_pass=True,
            terminal_response_coverage=1.0,
        ),
    )

    assert transition.status == "STOPPED"
    assert transition.rollback_version == "v1"
    assert transition.reasons == ("p0_safety_event",)


def test_full_release_becomes_completed() -> None:
    transition = transition_stage(current_stage="FULL", current_version="v1", metrics=_green())

    assert transition.status == "COMPLETED"
    assert transition.traffic_percent == 100

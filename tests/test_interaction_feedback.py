from dataclasses import FrozenInstanceError, replace

import pytest

from core.action_state_machine import ActionState
from core.control_engine import ControlSnapshot, DispatchOutcome
from core.control_session import SessionState
from gui.hud_state import HudState
from gui.interaction_feedback import InteractionFeedbackPresenter, interaction_feedback_model
from platform_services.contracts import ActionRequest, ActionResult


def snapshot(**changes):
    base = ControlSnapshot(
        timestamp=1.0, gesture="point", raw_gesture="point",
        session_state=SessionState.POINTER, pointer_state=ActionState.MOVING,
        hand_present=True, anchor=(100, 100), locked_position=None,
    )
    return replace(base, **changes)


def outcome(action="left_click", executed=True, error_code=""):
    return DispatchOutcome(ActionRequest(action), ActionResult(executed, error_code=error_code))


def render(value, **kwargs):
    return interaction_feedback_model(value, is_running=True, **kwargs)


def test_candidate_confirmed_and_executed_release_sequence():
    frames = [
        snapshot(),
        snapshot(pinch_phase="candidate", pointer_state=ActionState.LOCKING),
        snapshot(pinch_phase="confirmed", pointer_state=ActionState.CLICKING),
        snapshot(pinch_phase="released", outcomes=(outcome(),)),
        snapshot(),
    ]
    models = [render(frame) for frame in frames]
    assert [model.title_key for model in models] == [
        "interaction.aiming", "interaction.candidate", "interaction.confirmed",
        "interaction.clicked", "interaction.aiming",
    ]
    assert [model.stage for model in models] == [0, 1, 2, 2, 0]
    assert models[1].hint_key == "interaction.pinch_to_confirm"
    assert models[1].hud_state is HudState.POINTER
    assert models[2].hud_state is HudState.LOCKING
    assert models[2].hint_key == "interaction.release_or_drag"
    assert models[3].semantic_state == "success"
    assert models[3].hud_state is HudState.CLICKED


def test_released_long_hold_without_dispatch_does_not_claim_click():
    released = snapshot(timestamp=12.0, pinch_phase="released")
    model = render(released)
    assert model.title_key == "interaction.released"
    assert model.semantic_state == "active"
    assert model.hud_state is HudState.POINTER


@pytest.mark.parametrize("action", ["left_click", "right_click", "double_click"])
def test_failed_native_click_reports_failure_instead_of_success(action):
    model = render(snapshot(pinch_phase="released", outcomes=(
        outcome(action, False, "unavailable"),
    )))
    assert model.title_key == "interaction.not_executed"
    assert model.hint_key == "interaction.retry"
    assert model.semantic_state == "danger"
    assert model.hud_state is HudState.ERROR


def test_rejected_click_is_not_executed():
    model = render(snapshot(pinch_phase="released", outcomes=(
        outcome(executed=False, error_code="action_blocked"),
    )))
    assert model.title_key == "interaction.not_executed"
    assert model.semantic_state == "warning"


@pytest.mark.parametrize("code", ["unsupported_action", "unavailable", "input_unavailable"])
def test_individual_dispatch_failure_does_not_claim_control_interrupted(code):
    model = render(snapshot(outcomes=(outcome(executed=False, error_code=code),)))
    assert model.title_key == "interaction.not_executed"
    assert model.hint_key == "interaction.retry"


def test_hand_loss_suppresses_retained_pinch_and_success_feedback():
    model = render(snapshot(hand_present=False, pinch_phase="confirmed", outcomes=(outcome(),)))
    assert model.title_key == "interaction.hand_lost"
    assert model.hint_key == "interaction.show_hand"
    assert model.stage is None


@pytest.mark.parametrize("error", ["invalid_frame_time", "invalid_observation", "frame_geometry_changed"])
def test_tracking_error_precedes_hand_loss_and_stale_click(error):
    model = render(snapshot(error=error, hand_present=False, outcomes=(outcome(),)))
    assert model.title_key == "interaction.error"
    assert model.hint_key == "interaction.recover_tracking"
    assert model.stage is None


def test_stale_frame_dispatch_does_not_claim_released_click():
    model = render(snapshot(pinch_phase="released", outcomes=(
        outcome(executed=False, error_code="stale_frame"),
    )))
    assert model.title_key == "interaction.error"
    assert model.hint_key == "interaction.recover_tracking"


def test_stopped_session_discards_retained_error_and_click():
    model = interaction_feedback_model(
        snapshot(error="control_failed", outcomes=(outcome(),)), is_running=False,
    )
    assert model.title_key == "interaction.paused"
    assert model.stage is None
    assert model.hud_state is HudState.HIDDEN


def test_permissions_and_missing_initial_snapshot():
    assert interaction_feedback_model(None, is_running=False, ready=False).title_key == "interaction.blocked"
    assert render(None).title_key == "interaction.inactive"
    assert render(None, session_state=SessionState.ARMED).title_key == "interaction.hand_lost"


def test_inactive_session_overrides_retained_candidate_and_click():
    model = render(snapshot(pinch_phase="candidate", outcomes=(outcome(),)),
                   session_state=SessionState.INACTIVE)
    assert model.title_key == "interaction.inactive"
    assert model.hint_key == "interaction.activate"
    assert model.stage is None


@pytest.mark.parametrize("phase", ["candidate", "confirmed", "released"])
def test_dragging_takes_precedence_over_physical_phase_and_old_click(phase):
    model = render(snapshot(pointer_state=ActionState.DRAGGING, pinch_phase=phase,
                            outcomes=(outcome(),)))
    assert model.title_key == "interaction.dragging"
    assert model.hint_key == "interaction.release_to_drop"
    assert model.hud_state is HudState.DRAGGING


def test_failed_release_is_visible_after_session_deactivation():
    model = render(snapshot(session_state=SessionState.INACTIVE, outcomes=(
        outcome("drag_end", False, "release_pending"),
    )))
    assert model.title_key == "interaction.not_executed"


def test_cancelled_episode_requires_reopening_without_reporting_click():
    model = render(snapshot(pinch_phase="cancelled", pinch_reason="unconfirmed_release"))
    assert model.title_key == "interaction.cancelled"
    assert model.hint_key == "interaction.reopen"
    assert model.semantic_state == "warning"


def test_click_uses_coalesced_outcomes_and_secondary_hud_semantics():
    model = render(snapshot(), outcomes=(outcome("right_click"),))
    assert model.title_key == "interaction.clicked"
    assert model.hud_state is HudState.SECONDARY_CLICK
    assert render(snapshot(outcomes=(outcome(),)), outcomes=()).title_key == "interaction.aiming"


def test_normal_no_action_outcome_is_not_a_failure():
    model = render(snapshot(outcomes=(outcome("none", False, "no_action"),)))
    assert model.title_key == "interaction.aiming"


def test_feedback_is_immutable():
    model = render(snapshot())
    with pytest.raises(FrozenInstanceError):
        model.stage = 1


@pytest.mark.parametrize("resume_phase", ["idle", "released"])
def test_presenter_keeps_click_readable_for_seven_tenths_then_resumes(resume_phase):
    presenter = InteractionFeedbackPresenter()
    clicked = render(snapshot(outcomes=(outcome(),)))
    baseline = render(snapshot(pinch_phase=resume_phase))
    assert presenter.update(clicked, now=1.0) == clicked
    assert presenter.update(baseline, now=1.1) == clicked
    assert presenter.update(baseline, now=1.69) == clicked
    assert presenter.update(baseline, now=1.71) == baseline


def test_presenter_keeps_failure_readable_for_one_and_half_seconds():
    presenter = InteractionFeedbackPresenter()
    rejected = render(snapshot(outcomes=(outcome(executed=False, error_code="unavailable"),)))
    aiming = render(snapshot())
    assert presenter.update(rejected, now=4.0) == rejected
    assert presenter.update(aiming, now=5.49) == rejected
    assert presenter.update(aiming, now=5.51) == aiming


@pytest.mark.parametrize("boundary", [
    interaction_feedback_model(None, is_running=False),
    interaction_feedback_model(None, is_running=False, ready=False),
    render(snapshot(session_state=SessionState.INACTIVE)),
    render(snapshot(hand_present=False)),
    render(snapshot(pinch_phase="candidate")),
    render(snapshot(pinch_phase="confirmed")),
    render(snapshot(pointer_state=ActionState.DRAGGING, pinch_phase="confirmed")),
    render(snapshot(error="invalid_frame_time")),
    render(snapshot(pinch_phase="cancelled")),
])
@pytest.mark.parametrize("event", [
    render(snapshot(outcomes=(outcome(),))),
    render(snapshot(outcomes=(outcome(executed=False, error_code="unsupported_action"),))),
])
def test_presenter_clears_outcome_immediately_at_instruction_or_session_boundary(boundary, event):
    presenter = InteractionFeedbackPresenter()
    aiming = render(snapshot())
    presenter.update(event, now=2.0)
    assert presenter.update(boundary, now=2.01) == boundary
    assert presenter.update(aiming, now=2.02) == aiming


@pytest.mark.parametrize("event", [
    render(snapshot(outcomes=(outcome(),))),
    render(snapshot(outcomes=(outcome(executed=False, error_code="unavailable"),))),
])
def test_repeated_identical_event_does_not_extend_its_hold(event):
    presenter = InteractionFeedbackPresenter()
    aiming = render(snapshot())
    presenter.update(aiming, now=0.0)
    presenter.update(event, now=1.0)
    assert presenter.update(event, now=1.1) == event
    assert presenter.update(event, now=2.6) == aiming
    assert presenter.update(event, now=10.0) == aiming


def test_new_click_after_an_aim_frame_restarts_read_time():
    presenter = InteractionFeedbackPresenter()
    clicked = render(snapshot(outcomes=(outcome(),)))
    aiming = render(snapshot())
    presenter.update(clicked, now=1.0)
    presenter.update(aiming, now=1.2)
    assert presenter.update(clicked, now=1.6) == clicked
    assert presenter.update(aiming, now=1.8) == clicked
    assert presenter.update(aiming, now=2.31) == aiming


def test_presenter_cannot_hold_an_old_outcome_across_clock_discontinuity():
    presenter = InteractionFeedbackPresenter()
    clicked = render(snapshot(outcomes=(outcome(),)))
    aiming = render(snapshot())
    presenter.update(clicked, now=10.0)
    assert presenter.update(aiming, now=9.0) == aiming
    assert presenter.update(aiming, now=9.1) == aiming

from core.action_state_machine import ActionState
from core.intent_arbiter import IntentArbiter, IntentOwner


NOT_APPROACHING = {"distance": 100, "velocity": 0, "is_approaching": False}
APPROACHING = {"distance": 50, "velocity": -250, "is_approaching": True}


def test_pointer_transition_owns_shortcut_lanes_through_transient_non_pointer_noise():
    arbiter = IntentArbiter()

    pointing = arbiter.update(
        gesture="point", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.0,
    )
    noisy_transition = arbiter.update(
        gesture="peace", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.1,
    )

    assert pointing.owner is IntentOwner.POINTER
    assert pointing.effective_pointer_gesture == "point"
    assert pointing.allow_pointer is True
    assert pointing.allow_combo is False
    assert pointing.allow_dynamic is False
    assert noisy_transition.owner is IntentOwner.POINTER
    assert noisy_transition.effective_pointer_gesture == "point"
    assert noisy_transition.allow_pointer is True
    assert noisy_transition.allow_combo is False
    assert noisy_transition.allow_dynamic is False


def test_pointer_candidate_blocks_shortcuts_before_a_pinch_is_classified():
    arbiter = IntentArbiter()

    decision = arbiter.update(
        gesture="point", pinch_info=APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.0,
    )

    assert decision.owner is IntentOwner.POINTER
    assert decision.allow_pointer is True
    assert decision.allow_combo is False
    assert decision.allow_dynamic is False


def test_drag_owns_control_even_when_classifier_temporarily_reports_a_shortcut_pose():
    arbiter = IntentArbiter()

    decision = arbiter.update(
        gesture="peace", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.DRAGGING, hand_present=True, now=1.0,
    )

    assert decision.owner is IntentOwner.POINTER
    assert decision.allow_combo is False
    assert decision.allow_dynamic is False


def test_non_pointer_shortcuts_require_neutral_rearm_after_pointer_control():
    arbiter = IntentArbiter()
    arbiter.update(
        gesture="point", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.0,
    )

    still_claimed = arbiter.update(
        gesture="peace", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.25,
    )
    first_neutral = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.3,
    )
    second_neutral = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.4,
    )
    rearmed = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.5,
    )
    decision = arbiter.update(
        gesture="peace", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.6,
    )

    assert still_claimed.owner is IntentOwner.POINTER
    assert still_claimed.allow_combo is False
    assert first_neutral.allow_combo is False
    assert second_neutral.allow_combo is False
    assert rearmed.owner is IntentOwner.NEUTRAL
    assert decision.owner is IntentOwner.NEUTRAL
    assert decision.allow_pointer is False
    assert decision.allow_combo is True
    assert decision.allow_dynamic is True


def test_composite_commit_requires_a_neutral_rearm_before_shortcuts_can_run_again():
    arbiter = IntentArbiter()
    arbiter.mark_composite_committed()

    blocked = arbiter.update(
        gesture="peace", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.0,
    )
    first_neutral = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.1,
    )
    second_neutral = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.2,
    )
    rearmed = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=True, now=1.3,
    )

    assert blocked.owner is IntentOwner.WAIT_NEUTRAL
    assert blocked.allow_combo is False
    assert blocked.allow_dynamic is False
    assert first_neutral.allow_dynamic is False
    assert second_neutral.allow_dynamic is False
    assert rearmed.owner is IntentOwner.NEUTRAL
    assert rearmed.allow_combo is True
    assert rearmed.allow_dynamic is True


def test_hand_loss_resets_pointer_claim_and_disables_all_dispatch_lanes():
    arbiter = IntentArbiter()
    arbiter.update(
        gesture="pinch", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.CLICKING, hand_present=True, now=1.0,
    )

    decision = arbiter.update(
        gesture="none", pinch_info=NOT_APPROACHING,
        pointer_state=ActionState.MOVING, hand_present=False, now=1.1,
    )

    assert decision.owner is IntentOwner.NEUTRAL
    assert decision.allow_pointer is False
    assert decision.allow_combo is False
    assert decision.allow_dynamic is False

"""Replay pointer evidence through the real arbiter and input state machine."""

import pytest

from core.action_state_machine import ActionState, ActionStateMachine
from core.control_session import ActivationMode, ControlSession, SessionState
from core.intent_arbiter import IntentArbiter, IntentOwner


def pinch_info(closed):
    return {
        "distance": 10 if closed else 100,
        "velocity": 0,
        "is_approaching": False,
        "is_pinching": closed,
    }


class Replay:
    def __init__(self):
        self.machine = ActionStateMachine(drag_threshold=0.1)
        self.arbiter = IntentArbiter()

    def frame(self, gesture, now, *, closed=True, pos=(100, 100), motion_pos=None):
        info = pinch_info(closed)
        decision = self.arbiter.update(
            gesture=gesture, pinch_info=info, pointer_state=self.machine.state,
            hand_present=True, now=now,
        )
        result = None
        if decision.allow_pointer:
            result = self.machine.update(
                decision.effective_pointer_gesture, pos, info, timestamp=now,
                motion_pos=motion_pos,
            )
        return decision, result

    def drag(self):
        self.frame("pinch", 1.0)
        _, started = self.frame("pinch_hold", 1.1, motion_pos=(120, 100))
        assert started["action"] == "drag_start"


def test_drag_uses_live_hand_motion_while_click_target_is_frozen():
    replay = Replay()
    replay.drag()
    _, moved = replay.frame("pinch_hold", 1.2, motion_pos=(160, 120))
    assert moved["action"] == "drag"
    assert moved["pos"] == (160, 120)


def test_drag_zone_filter_uses_live_output_and_releases_at_last_allowed_position():
    replay = Replay()
    replay.drag()
    replay.machine.add_zone_rule(150, 0, 100, 200, ["click"])
    _, blocked = replay.frame("pinch_hold", 1.2, motion_pos=(180, 100))
    _, release = replay.frame("point", 1.3, closed=False, motion_pos=(180, 100))
    assert blocked["action"] == "none"
    assert release["action"] == "drag_end"
    assert release["pos"] == (100, 100)


def test_denied_drag_start_does_not_establish_a_native_drag_lifecycle():
    replay = Replay()
    replay.machine.add_zone_rule(50, 50, 100, 100, ["click"])
    replay.frame("pinch", 1.0)
    _, blocked = replay.frame("pinch_hold", 1.1, motion_pos=(120, 100))
    assert blocked["action"] == "none"
    assert replay.machine.state is ActionState.CLICKING


def test_opening_jump_cannot_start_drag_with_a_stale_pinch_label():
    replay = Replay()
    replay.frame("pinch", 1.0)
    _, holding = replay.frame("pinch_hold", 1.2)
    assert holding["action"] == "none"
    _, opening = replay.frame(
        "pinch_hold", 1.3, closed=False, pos=(200, 200), motion_pos=(200, 200)
    )
    _, released = replay.frame("pinch_hold", 1.35, closed=False, pos=(200, 200))
    assert opening["action"] == released["action"] == "none"
    assert replay.machine.state is ActionState.MOVING


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("release_label", ["open_hand", "pinch_hold"])
def test_physical_opening_releases_drag_once_within_bounded_time(fps, release_label):
    replay = Replay()
    replay.drag()
    replay.frame("pinch_hold", 1.2, motion_pos=(150, 120))
    releases = []
    for index in range(int(fps * 0.3)):
        now = 1.3 + index / fps
        _, result = replay.frame(
            release_label, now, closed=False, pos=(400, 400), motion_pos=(400, 400)
        )
        if result is not None and result["action"] == "drag_end":
            releases.append((now, result["pos"]))
        assert result is None or result["action"] not in {"drag", "drag_start", "left_click"}
    assert len(releases) == 1
    assert releases[0][0] - 1.3 <= 0.04 + 1 / fps + 1e-9
    assert releases[0][1] == (150, 120)


def test_one_noisy_open_frame_does_not_release_or_move_drag():
    replay = Replay()
    replay.drag()
    _, noise = replay.frame("open_hand", 1.2, closed=False, motion_pos=(400, 400))
    _, recovered = replay.frame("pinch_hold", 1.23, closed=True, motion_pos=(130, 100))
    assert noise["action"] == "none"
    assert recovered["action"] == "drag"
    assert recovered["pos"] == (130, 100)


def test_confirmed_opening_clicks_once_even_while_pose_label_lags():
    replay = Replay()
    replay.frame("pinch", 1.0)
    _, first = replay.frame("pinch_hold", 1.1, closed=False)
    _, release = replay.frame("pinch_hold", 1.15, closed=False)
    _, stale = replay.frame("pinch_hold", 1.2, closed=False)
    assert first["action"] == stale["action"] == "none"
    assert release["action"] == "left_click"
    assert replay.machine.state is ActionState.MOVING


def test_release_confirmation_delay_does_not_consume_the_click_duration_budget():
    replay = Replay()
    replay.frame("pinch", 1.0)
    _, opening = replay.frame("pinch_hold", 1.28, closed=False)
    _, confirmed = replay.frame("pinch_hold", 1.33, closed=False)
    assert opening["action"] == "none"
    assert confirmed["action"] == "left_click"


def test_ambiguous_neutral_cancels_a_click_instead_of_committing_it():
    arbiter = IntentArbiter()
    machine = ActionStateMachine()
    machine.update("pinch", (100, 100), timestamp=1.0)
    decisions = []
    for now in (1.05, 1.08, 1.11):
        decision = arbiter.update(
            gesture="none", pinch_info={}, pointer_state=machine.state,
            hand_present=True, now=now,
        )
        result = machine.update(decision.effective_pointer_gesture, (100, 100), timestamp=now)
        decisions.append(decision.effective_pointer_gesture)
        assert result["action"] == "none"
    assert decisions[-1] == "cancel"
    assert machine.state is ActionState.MOVING


def test_persistent_non_pointer_noise_has_a_timeout_even_without_neutral():
    arbiter = IntentArbiter()
    machine = ActionStateMachine()
    machine.update("pinch", (0, 0), timestamp=1.0)
    machine.update("pinch_hold", (20, 0), timestamp=1.4)
    actions = []
    for now in (1.5, 1.6, 1.76):
        decision = arbiter.update(
            gesture="peace", pinch_info={}, pointer_state=machine.state,
            hand_present=True, now=now,
        )
        actions.append(machine.update(decision.effective_pointer_gesture, (20, 0), timestamp=now)["action"])
    assert actions == ["drag", "drag", "drag_end"]


def test_contextual_scroll_can_follow_pointing_and_return_without_neutral():
    replay = Replay()
    pointing, _ = replay.frame("point", 1.0, closed=False)
    scrolling, result = replay.frame("thumb_down", 1.1, closed=False)
    pointing_again, _ = replay.frame("point", 1.2, closed=False)
    assert pointing.allow_pointer and pointing_again.allow_pointer
    assert scrolling.owner is IntentOwner.CONTEXTUAL
    assert scrolling.allow_contextual
    assert not scrolling.allow_pointer and not scrolling.allow_combo and not scrolling.allow_dynamic
    assert result is None


@pytest.mark.parametrize("state", [ActionState.CLICKING, ActionState.DRAGGING])
def test_scroll_pose_cannot_steal_a_held_pointer(state):
    decision = IntentArbiter().update(
        gesture="thumb_up", pinch_info=pinch_info(True), pointer_state=state,
        hand_present=True, now=1.0,
    )
    assert decision.allow_pointer
    assert not decision.allow_contextual and not decision.allow_combo and not decision.allow_dynamic


def make_session(mode=ActivationMode.GESTURE_OR_SHORTCUT):
    return ControlSession(
        mode=mode, activation_gesture="open_hand", exit_gesture="fist",
        stability_seconds=0.3, no_hand_timeout_seconds=2.0,
    )


def test_either_mode_latches_gesture_activation_through_pointer_and_scroll():
    session = make_session()
    assert session.update("open_hand", True, False, 1.0) is SessionState.INACTIVE
    assert session.update("open_hand", True, False, 1.31) is SessionState.ARMED
    assert session.update("point", True, False, 1.32) is SessionState.POINTER
    assert session.update("thumb_down", True, False, 1.8) is SessionState.POINTER
    assert session.update("fist", True, False, 2.0) is SessionState.INACTIVE
    assert session.update("point", True, False, 2.1) is SessionState.INACTIVE


def test_either_mode_shortcut_activation_still_requires_holding_the_shortcut():
    session = make_session()
    assert session.update("point", True, True, 1.0) is SessionState.ARMED
    assert session.update("point", True, True, 1.1) is SessionState.POINTER
    assert session.update("point", True, False, 1.2) is SessionState.INACTIVE


def test_hand_loss_clears_the_gesture_activation_latch():
    session = make_session()
    session.update("open_hand", True, False, 1.0)
    session.update("open_hand", True, False, 1.31)
    assert session.update("none", False, False, 3.4) is SessionState.INACTIVE
    assert session.update("point", True, False, 3.5) is SessionState.INACTIVE


def test_cancel_can_release_drag_without_a_current_position():
    machine = ActionStateMachine()
    machine.update("pinch", (10, 10), timestamp=1.0)
    machine.update("pinch_hold", (30, 10), timestamp=1.4)
    result = machine.update("cancel", None, timestamp=1.5)
    assert result["action"] == "drag_end"
    assert result["pos"] == (10, 10)
    assert machine.state is ActionState.MOVING

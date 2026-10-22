import math

import pytest

from core.action_state_machine import ActionState, ActionStateMachine
from core.gesture_classifier import GestureClassifier


@pytest.mark.parametrize("invalid_timestamp", (9.0, 10.0, math.nan, math.inf, -math.inf))
def test_invalid_or_non_increasing_timestamp_cannot_turn_pinch_release_into_click(invalid_timestamp):
    machine = ActionStateMachine()
    machine.update("pinch", (20, 20), timestamp=10.0)

    result = machine.update("point", (20, 20), timestamp=invalid_timestamp)

    assert result["action"] == "none"
    assert machine.state is ActionState.MOVING
    assert machine.update("point", (20, 20), timestamp=9.5)["action"] == "none"
    assert machine.update("point", (20, 20), timestamp=11.0)["action"] == "move_cursor"


def test_invalid_timestamp_ends_an_active_drag_without_leaving_drag_state():
    machine = ActionStateMachine(move_threshold=1, drag_threshold=0.1)
    machine.update("pinch", (0, 0), timestamp=1.0)
    machine.update("pinch_hold", (2, 0), timestamp=1.2)

    result = machine.update("pinch_hold", (3, 0), timestamp=math.nan)

    assert result["action"] == "drag_end"
    assert machine.state is ActionState.MOVING


def test_classifier_uses_the_explicit_frame_timestamp_for_pinch_velocity():
    classifier = GestureClassifier(clock=lambda: 999.0)
    landmarks = [(0.0, 0.0, 0.0)] * 21
    landmarks[4] = (0.0, 0.0, 0.0)
    landmarks[8] = (100.0, 0.0, 0.0)
    classifier.get_pinch_info(landmarks, timestamp=1.0)
    landmarks[8] = (50.0, 0.0, 0.0)

    info = classifier.get_pinch_info(landmarks, timestamp=1.5)

    assert info["velocity"] == pytest.approx(-100.0)

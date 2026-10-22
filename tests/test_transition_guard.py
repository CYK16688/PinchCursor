"""The transition guard: a pass-through pinch must never become a click."""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from core.hand_dynamics import DynamicAssessment
from gui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(*, guard=True, state=ActionState.MOVING):
    window = MainWindow.__new__(MainWindow)
    window.config = SimpleNamespace(get=lambda key: {"transition_guard": guard} if key == "temporal" else {})
    window.action_machine = SimpleNamespace(state=state)
    return window


def _assessment(*, transition=False, confidence=0.9):
    return DynamicAssessment(
        pinch_ratio=0.2,
        pinch_confidence=confidence,
        transition=transition,
        others_rate=0.0,
        wrist_speed=0.0,
    )


def test_a_passing_pinch_is_downgraded_to_pointer_movement(app):
    window = _window()

    gesture = MainWindow._apply_dynamics(window, "pinch", _assessment(transition=True))

    assert gesture == "point"


def test_a_confident_pinch_passes_through_untouched(app):
    window = _window()

    assert MainWindow._apply_dynamics(window, "pinch", _assessment()) == "pinch"


def test_a_weak_pinch_does_not_click(app):
    window = _window()

    gesture = MainWindow._apply_dynamics(
        window, "pinch", _assessment(confidence=0.3)
    )

    assert gesture == "point"


def test_a_held_pinch_is_never_downgraded_by_low_confidence(app):
    # pinching and holding is already deliberate; only transitions veto it.
    window = _window()

    gesture = MainWindow._apply_dynamics(
        window, "pinch_hold", _assessment(confidence=0.2)
    )

    assert gesture == "pinch_hold"


def test_an_active_click_or_drag_is_never_disturbed(app):
    window = _window(state=ActionState.CLICKING)

    gesture = MainWindow._apply_dynamics(window, "pinch", _assessment(transition=True))

    assert gesture == "pinch"


def test_the_guard_can_be_turned_off(app):
    window = _window(guard=False)

    gesture = MainWindow._apply_dynamics(window, "pinch", _assessment(transition=True))

    assert gesture == "pinch"


def test_other_gestures_are_untouched(app):
    window = _window()

    assert MainWindow._apply_dynamics(window, "fist", _assessment(transition=True)) == "fist"
    assert MainWindow._apply_dynamics(window, "point", None) == "point"

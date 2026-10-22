"""Aiming assist: the lock position may move, nothing before it may."""

from types import SimpleNamespace

from core.action_state_machine import ActionState, ActionStateMachine
from core.assist.target_model import TargetModel
from gui.main_window import MainWindow
from platform_services.contracts import UIContext


class ProbeProvider:
    """Stands in for the accessibility provider's bounded hit-test probe."""

    def __init__(self, contexts):
        self.contexts = contexts
        self.calls = []

    def probe_targets(self, x, y, radius=120):
        self.calls.append((x, y, radius))
        return list(self.contexts)


def _window(provider, *, enabled=True):
    window = MainWindow.__new__(MainWindow)
    window.platform_services = SimpleNamespace(context_provider=provider)
    window.target_model = TargetModel() if enabled else None
    return window


def _button(x, y, w=80, h=30):
    return UIContext(
        category="clickable",
        native_role="AXButton",
        source="probe",
        bounds=(x, y, w, h),
    )


def test_assist_snaps_to_a_nearby_button():
    provider = ProbeProvider([_button(100, 100)])
    window = _window(provider)

    # 12 px left of the frame and 8 px above it; the frame is inset by 2 px
    # so the cursor lands inside the button rather than on its edge.
    assert MainWindow._snap_cursor_position(window, (88, 92)) == (102, 102)


def test_assist_keeps_the_raw_position_when_the_choice_is_ambiguous():
    # Two identical buttons equidistant from the pointer: no safe winner.
    provider = ProbeProvider([_button(40, 100, 40, 30), _button(160, 100, 40, 30)])
    window = _window(provider)

    assert MainWindow._snap_cursor_position(window, (120, 115)) is None


def test_assist_is_inert_without_a_probe_capable_provider_or_model():
    class ContextOnly:
        def get_context(self, x=None, y=None):
            return UIContext(category="generic")

    assert MainWindow._snap_cursor_position(_window(ContextOnly()), (10, 10)) is None
    assert MainWindow._snap_cursor_position(
        _window(ProbeProvider([_button(10, 10)]), enabled=False), (10, 10)
    ) is None


def test_assist_ignores_targets_without_geometry():
    provider = ProbeProvider([UIContext(category="clickable", native_role="AXButton")])
    window = _window(provider)

    assert MainWindow._snap_cursor_position(window, (10, 10)) is None


def test_machine_locks_at_the_assisted_position_on_pinch():
    provider = ProbeProvider([_button(200, 200)])
    window = _window(provider)
    machine = ActionStateMachine(clock=lambda: 1.0)
    machine.snap_provider = MainWindow._snap_cursor_position.__get__(window)

    result = machine.update("pinch", (188, 192), {"distance": 10, "velocity": 0, "is_approaching": False}, timestamp=1.0)

    assert machine.state is ActionState.CLICKING
    assert result["pos"] == (202, 202)


def test_machine_keeps_the_raw_position_when_assist_declines():
    provider = ProbeProvider([])
    window = _window(provider)
    machine = ActionStateMachine(clock=lambda: 1.0)
    machine.snap_provider = MainWindow._snap_cursor_position.__get__(window)

    result = machine.update("pinch", (188, 192), {"distance": 10, "velocity": 0, "is_approaching": False}, timestamp=1.0)

    assert result["pos"] == (188, 192)


def test_assisted_snap_is_not_mistaken_for_hand_movement():
    """A snap can move the cursor ~20 px; that must not start a drag."""
    provider = ProbeProvider([_button(200, 200)])
    window = _window(provider)
    machine = ActionStateMachine(clock=lambda: 1.0, drag_threshold=0.3, move_threshold=8)
    machine.snap_provider = MainWindow._snap_cursor_position.__get__(window)
    pinch = {"distance": 10, "velocity": 0, "is_approaching": False}

    machine.update("pinch", (188, 192), pinch, timestamp=1.0)
    machine.update("pinch", (188, 192), pinch, timestamp=2.0)

    assert machine.state is ActionState.CLICKING


def test_real_hand_movement_after_a_snap_still_drags():
    provider = ProbeProvider([_button(200, 200)])
    window = _window(provider)
    machine = ActionStateMachine(clock=lambda: 1.0, drag_threshold=0.3, move_threshold=8)
    machine.snap_provider = MainWindow._snap_cursor_position.__get__(window)
    pinch = {"distance": 10, "velocity": 0, "is_approaching": False}

    machine.update("pinch", (188, 192), pinch, timestamp=1.0)
    machine.update("pinch", (215, 192), pinch, timestamp=2.0)

    assert machine.state is ActionState.DRAGGING


def test_machine_survives_a_broken_assist_provider():
    def explode(_pos):
        raise RuntimeError("accessibility went away")

    machine = ActionStateMachine(clock=lambda: 1.0)
    machine.snap_provider = explode

    result = machine.update("pinch", (10, 10), {"distance": 10, "velocity": 0, "is_approaching": False}, timestamp=1.0)

    assert result["pos"] == (10, 10)

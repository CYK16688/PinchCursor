import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from core.intent_arbiter import IntentDecision, IntentOwner
from core.mediapipe_worker import LandmarkFrame
from gui import main_window
from platform_services.contracts import ActionResult


def test_process_frame_uses_one_worker_timestamp_across_the_control_lane():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    observed = {}

    def tracker_update(_landmarks, _shape, **kwargs):
        observed["tracker"] = kwargs["timestamp"]
        return (100, 100), True

    def classify(_landmarks, **kwargs):
        observed["classifier"] = kwargs["timestamp"]
        return "point"

    def pinch_info(_landmarks, **kwargs):
        observed["pinch"] = kwargs["timestamp"]
        return {"distance": 100, "velocity": 0, "is_approaching": False}

    def session_update(**kwargs):
        observed["session"] = kwargs["now"]

    def arbiter_update(**kwargs):
        observed["arbiter"] = kwargs["now"]
        return IntentDecision(
            owner=IntentOwner.POINTER,
            effective_pointer_gesture="point",
            allow_pointer=True,
            allow_combo=False,
            allow_dynamic=False,
        )

    def machine_update(*_args, **kwargs):
        observed["machine"] = kwargs["timestamp"]
        return {"action": "move_cursor", "pos": (100, 100), "is_locked": False}

    def smooth(x, y, **kwargs):
        observed["smoother"] = kwargs["timestamp"]
        return x, y

    try:
        window.is_running = True
        window.control_session.state = window.control_session.state.POINTER
        window.config.set("dynamic_gestures", "enabled", False)
        window._update_power_mode = lambda _landmarks: None
        window.tracker.update = tracker_update
        window._check_edge_lost = lambda _landmarks, now: observed.setdefault("edge", now)
        window.classifier.classify = classify
        window.classifier.get_pinch_info = pinch_info
        window.control_session.update = session_update
        window.intent_arbiter.update = arbiter_update
        window.action_machine.update = machine_update
        window.smoother.smooth = smooth
        window.action_coordinator.dispatch = lambda _request: ActionResult(True)
        window._refresh_control_session_status = lambda: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None

        frame = type("Frame", (), {"shape": (480, 640, 3)})()
        window.process_frame(
            LandmarkFrame(frame=frame, landmarks=[(0.0, 0.0, 0.0)] * 21, timestamp_ms=1234)
        )

        assert set(observed.values()) == {1.234}
    finally:
        window.close()


def test_invalid_worker_timestamp_resets_pointer_safety_state_without_dispatch():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    released = []
    try:
        window.is_running = True
        window.action_machine.state = ActionState.DRAGGING
        window.control_session.state = window.control_session.state.POINTER
        window._last_worker_timestamp_ms = 1000
        window.action_coordinator.stop = lambda: released.append(True) or ActionResult(True)
        frame = type("Frame", (), {"shape": (10, 10, 3)})()

        window.process_frame(LandmarkFrame(frame=frame, landmarks=[], timestamp_ms=1000))

        assert released == [True]
        assert window.action_machine.state is ActionState.MOVING
        assert window.control_session.state is window.control_session.state.INACTIVE
        assert window._last_worker_timestamp_ms == 1000
    finally:
        window.close()

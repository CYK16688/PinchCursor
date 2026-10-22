import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from core.control_session import SessionState
from gui import main_window
from platform_services.contracts import ActionRequest, ActionResult
from platform_services.macos.input_controller import MacOSInputController


class RecordingNative:
    def __init__(self):
        self.events = []

    def post_mouse(self, event_type, x, y, button):
        self.events.append((event_type, x, y, button))


def _lost_frame():
    frame = type("Frame", (), {"shape": (10, 10, 3)})()
    return type("LandmarkFrame", (), {"frame": frame, "landmarks": []})()


def _stub_lost_frame_processing(window):
    window._update_power_mode = lambda _landmarks, **_kwargs: None
    window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), False)
    window._check_edge_lost = lambda _landmarks, _now: None
    window.classifier.classify = lambda _landmarks, **_kwargs: "pinch_hold"
    window._refresh_control_session_status = lambda **_kwargs: None
    window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: None
    window._get_status_text = lambda _detected: "test"
    window._render_hud = lambda **_kwargs: None
    window._draw_landmarks = lambda frame, _landmarks: frame
    window._draw_edge_hint = lambda frame, **_kwargs: frame
    window.display_frame = lambda _frame: None


def test_predicted_position_after_tracking_loss_releases_drag_and_blocks_input_dispatch():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = main_window.MainWindow()
    dispatched = []
    releases = []
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.action_machine.state = ActionState.DRAGGING
        window.dynamic_landmark_frames.extend(([(0.0, 0.0, 0.0)] * 21,) * 2)
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        window.action_coordinator.stop = lambda: releases.append(True) or ActionResult(True)
        _stub_lost_frame_processing(window)

        window.process_frame(_lost_frame())

        assert releases == [True]
        assert dispatched == []
        assert window.action_machine.state is ActionState.MOVING
        assert not window.dynamic_landmark_frames
    finally:
        window.close()
        app.processEvents()


def test_repeated_tracking_loss_emits_one_native_mouse_up_for_an_active_drag():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = main_window.MainWindow()
    native = RecordingNative()
    controller = MacOSInputController(native)
    try:
        controller.execute(ActionRequest(action="drag_start", x=10, y=20))
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.action_machine.state = ActionState.DRAGGING
        window.action_coordinator.stop = controller.release_drag
        _stub_lost_frame_processing(window)

        window.process_frame(_lost_frame())
        window.process_frame(_lost_frame())

        assert native.events == [
            ("left_down", 10, 20, "left"),
            ("left_up", 10, 20, "left"),
        ]
    finally:
        window.close()
        app.processEvents()

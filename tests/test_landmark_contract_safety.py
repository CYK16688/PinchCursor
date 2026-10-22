import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from core.hand_detector import HandDetector
from core.mediapipe_worker import LandmarkFrame
from gui import main_window
from gui.i18n import translate
from platform_services.contracts import ActionRequest, ActionResult
from platform_services.macos.input_controller import MacOSInputController


class _Landmark:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


def _result(landmarks):
    return SimpleNamespace(hand_landmarks=[landmarks])


@pytest.mark.parametrize(
    "points",
    (
        [_Landmark(0.5, 0.5, 0.0)] * 20,
        [_Landmark(0.5, 0.5, 0.0)] * 22,
        [_Landmark(math.nan, 0.5, 0.0)] * 21,
        [_Landmark(math.inf, 0.5, 0.0)] * 21,
    ),
)
def test_hand_detector_rejects_landmarks_that_do_not_meet_the_21_point_contract(points):
    detector = HandDetector.__new__(HandDetector)

    assert detector.get_landmarks(_result(points), (480, 640, 3)) is None


def test_hand_detector_returns_exactly_21_finite_pixel_landmarks():
    detector = HandDetector.__new__(HandDetector)
    points = [_Landmark(index / 40, index / 50, index / 100) for index in range(21)]

    landmarks = detector.get_landmarks(_result(points), (480, 640, 3))

    assert len(landmarks) == 21
    assert landmarks[8] == (128, 76, 0.08)


@pytest.mark.parametrize(
    "landmarks",
    (
        [(0.0, 0.0, 0.0)] * 20,
        [(0.0, 0.0, 0.0)] * 22,
        [(math.nan, 0.0, 0.0)] * 21,
        [(0.0, 0.0, math.inf)] * 21,
    ),
)
def test_main_window_fails_closed_when_a_worker_frame_breaks_the_landmark_contract(landmarks):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    released = []
    dispatched = []
    try:
        window.is_running = True
        window.action_coordinator.stop = lambda: released.append(True) or ActionResult(True)
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        window._update_power_mode = lambda _landmarks: None
        window._check_edge_lost = lambda _landmarks, _now: None
        window._refresh_control_session_status = lambda: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None
        called = []
        window.tracker.update = lambda *_args, **_kwargs: called.append("tracker") or (None, False)
        window.classifier.classify = lambda *_args, **_kwargs: called.append("classifier") or "none"
        window.classifier.get_pinch_info = lambda *_args, **_kwargs: called.append("pinch") or None
        window.intent_arbiter.update = lambda *_args, **_kwargs: called.append("arbiter")
        frame = np.zeros((20, 20, 3), dtype=np.uint8)

        window.process_frame(LandmarkFrame(frame=frame, landmarks=landmarks, timestamp_ms=1000))

        assert released == [True]
        assert dispatched == []
        assert called == []
    finally:
        window.close()


def test_empty_landmark_list_is_treated_consistently_as_hand_loss_for_edge_feedback():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    try:
        window.was_hand_detected = True
        window.tracker.at_edge = True
        window.tracker.edge_direction = (1, 0)
        window.tracker.last_pos = (10, 10)

        window._check_edge_lost([], 5.0)

        assert window.was_hand_detected is False
        assert window.edge_lost_time == 5.0
    finally:
        window.close()


def test_repeated_invalid_landmark_frames_emit_only_one_native_drag_release():
    class Native:
        def __init__(self):
            self.events = []

        def post_mouse(self, event_type, x, y, button):
            self.events.append((event_type, x, y, button))

    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    native = Native()
    controller = MacOSInputController(native)
    try:
        controller.execute(ActionRequest(action="drag_start", x=10, y=20))
        window.is_running = True
        window.action_coordinator.stop = controller.release_drag
        window._update_power_mode = lambda _landmarks: None
        window._check_edge_lost = lambda _landmarks, _now: None
        window._refresh_control_session_status = lambda: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window.display_frame = lambda _frame: None
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        invalid = [(math.nan, 0.0, 0.0)] * 21

        window.process_frame(LandmarkFrame(frame=frame, landmarks=invalid, timestamp_ms=1000))
        window.process_frame(LandmarkFrame(frame=frame, landmarks=invalid, timestamp_ms=1001))

        assert native.events == [
            ("left_down", 10, 20, "left"),
            ("left_up", 10, 20, "left"),
        ]
    finally:
        window.close()


def test_detector_help_text_advertises_only_the_supported_mediapipe_backend():
    for locale in ("zh_CN", "en_US"):
        hint = translate("settings.advanced.global.detector_hint", locale=locale)

        assert "MediaPipe" in hint
        assert "YOLO" not in hint

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.control_session import SessionState
from gui import main_window


class ResettableMatcher:
    def __init__(self):
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1


class ResettableComboDetector:
    def __init__(self):
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1


def _window_with_partial_dynamic_observation():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = main_window.MainWindow()
    matcher = ResettableMatcher()
    combo_detector = ResettableComboDetector()
    window.dynamic_runtime_matcher = matcher
    window.combo_detector = combo_detector
    window.dynamic_landmark_frames.extend(([(0.0, 0.0, 0.0)] * 21,) * 2)
    return app, window, matcher, combo_detector


@pytest.mark.parametrize("boundary", ("stop", "worker_error"))
def test_control_stop_boundaries_clear_partial_dynamic_observation(boundary):
    app, window, matcher, combo_detector = _window_with_partial_dynamic_observation()
    try:
        if boundary == "stop":
            window.is_running = True
            window.toggle_running()
        else:
            window.is_running = True
            window._on_worker_error("camera disconnected")

        assert not window.dynamic_landmark_frames
        assert matcher.reset_calls == 1
        assert combo_detector.reset_calls >= 1
    finally:
        window.close()
        app.processEvents()


def test_session_gate_close_clears_partial_dynamic_observation():
    app, window, matcher, combo_detector = _window_with_partial_dynamic_observation()
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.control_session.update = lambda **_kwargs: setattr(
            window.control_session, "state", SessionState.INACTIVE
        )
        window._update_power_mode = lambda _landmarks, **_kwargs: None
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: (None, False)
        window._check_edge_lost = lambda _landmarks, _now: None
        window.classifier.classify = lambda _landmarks, **_kwargs: "fist"
        window._refresh_control_session_status = lambda **_kwargs: None
        window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None
        frame = type("Frame", (), {"shape": (10, 10, 3)})()
        landmark_frame = type("LandmarkFrame", (), {"frame": frame, "landmarks": []})()

        window.process_frame(landmark_frame)

        assert not window.dynamic_landmark_frames
        assert matcher.reset_calls >= 1
        assert combo_detector.reset_calls >= 1
    finally:
        window.close()
        app.processEvents()

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from gui import main_window
from platform_services.contracts import ActionResult, UIContext
from utils.config_manager import ConfigManager


class ScrollableContext:
    def get_context(self, x=None, y=None):
        return UIContext(
            category="scrollable", native_role="AXWebArea", source="test", target_id="web-area"
        )

    def is_gesture_allowed(self, gesture, x=None, y=None):
        return True

    def is_action_allowed(self, action, x=None, y=None):
        return True


def _window_with_scrollable_target(tmp_path, monkeypatch):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    window = main_window.MainWindow()
    window.control_session.state = window.control_session.state.POINTER
    window.action_machine.state = ActionState.MOVING
    window.gesture_grace_period = 0
    window.platform_services = window.platform_services.__class__(
        capabilities=window.platform_services.capabilities,
        input_controller=window.platform_services.input_controller,
        context_provider=ScrollableContext(),
        permission_provider=window.platform_services.permission_provider,
        camera_service=window.platform_services.camera_service,
        hold_shortcut_monitor=window.platform_services.hold_shortcut_monitor,
    )
    window.action_coordinator.services = window.platform_services
    window.contextual_intent_controller.dwell_seconds = 0
    return window


def _stub_frame_processing(window):
    window._update_power_mode = lambda _landmarks, **_kwargs: None
    window._check_edge_lost = lambda _landmarks, _now: None
    window.classifier.classify = lambda _landmarks, **_kwargs: "none"
    window._refresh_control_session_status = lambda **_kwargs: None
    window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: None
    window._get_status_text = lambda _detected: "test"
    window._render_hud = lambda **_kwargs: None
    window._draw_landmarks = lambda frame, _landmarks: frame
    window._draw_edge_hint = lambda frame, **_kwargs: frame
    window.display_frame = lambda _frame: None


def _lost_landmark_frame():
    frame = type("Frame", (), {"shape": (10, 10, 3)})()
    return type("LandmarkFrame", (), {"frame": frame, "landmarks": []})()


def test_scroll_target_requires_a_point_candidate_before_thumb_dispatch(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _window_with_scrollable_target(tmp_path, monkeypatch)
    requests = []
    try:
        window.action_coordinator.dispatch = lambda request: requests.append(request) or ActionResult(True)

        # A thumb pose with no previously pointed, stable target has no static
        # macOS action and must not dispatch anything.
        window.execute_action("thumb_down", (100, 100), (480, 640, 3))
        assert requests == []

        # A stable point candidate enables only the contextual scroll action.
        window.execute_action("point", (100, 100), (480, 640, 3))
        window.execute_action("point", (100, 100), (480, 640, 3))
        window.execute_action("thumb_down", (100, 100), (480, 640, 3))

        assert requests[-1].action == "scroll_down"
        assert window.hud.message == "Scroll down"
    finally:
        window.close()


def test_stopping_control_clears_the_armed_contextual_candidate(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _window_with_scrollable_target(tmp_path, monkeypatch)
    try:
        window.execute_action("point", (100, 100), (480, 640, 3))
        window.execute_action("point", (100, 100), (480, 640, 3))
        assert window.contextual_intent_controller._candidate is not None

        window.is_running = True
        window.toggle_running()

        assert window.contextual_intent_controller._candidate is None
    finally:
        window.close()


def test_opening_settings_clears_the_armed_contextual_candidate(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _window_with_scrollable_target(tmp_path, monkeypatch)

    class CancelledSettings:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", CancelledSettings)
    monkeypatch.setattr(window, "_stop_video_worker", lambda **_kwargs: None)
    monkeypatch.setattr(window, "_start_video_worker", lambda **_kwargs: True)
    try:
        window.execute_action("point", (100, 100), (480, 640, 3))
        window.execute_action("point", (100, 100), (480, 640, 3))
        assert window.contextual_intent_controller._candidate is not None

        window.is_running = True
        window.open_settings()

        assert window.contextual_intent_controller._candidate is None
    finally:
        window.close()


def test_lost_pointer_position_clears_the_armed_contextual_candidate(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _window_with_scrollable_target(tmp_path, monkeypatch)
    try:
        window.execute_action("point", (100, 100), (480, 640, 3))
        window.execute_action("point", (100, 100), (480, 640, 3))
        assert window.contextual_intent_controller._candidate is not None

        window.is_running = True
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: (None, False)
        _stub_frame_processing(window)

        window.process_frame(_lost_landmark_frame())

        assert window.contextual_intent_controller._candidate is None
    finally:
        window.close()


def test_tracker_loss_clears_candidate_even_when_a_predicted_position_remains(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _window_with_scrollable_target(tmp_path, monkeypatch)
    try:
        window.execute_action("point", (100, 100), (480, 640, 3))
        window.execute_action("point", (100, 100), (480, 640, 3))
        assert window.contextual_intent_controller._candidate is not None

        window.is_running = True
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), False)
        _stub_frame_processing(window)

        window.process_frame(_lost_landmark_frame())

        assert window.contextual_intent_controller._candidate is None
    finally:
        window.close()


def test_predicted_pointer_position_does_not_feed_dynamic_shortcuts(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _window_with_scrollable_target(tmp_path, monkeypatch)

    class UnexpectedDynamicMatcher:
        def __init__(self):
            self.calls = 0

        def ingest(self, *_args, **_kwargs):
            self.calls += 1
            return None

    matcher = UnexpectedDynamicMatcher()
    try:
        window.is_running = True
        window.dynamic_runtime_matcher = matcher
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), False)
        _stub_frame_processing(window)

        window.process_frame(_lost_landmark_frame())

        assert matcher.calls == 0
        assert not window.dynamic_landmark_frames
    finally:
        window.close()

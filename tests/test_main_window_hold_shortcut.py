import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.control_session import ActivationMode
from gui import main_window
from gui.i18n import tr
from platform_services.contracts import (
    AuthorizationState,
    PermissionSnapshot,
    PlatformCapabilities,
    PlatformServices,
)
from platform_services.null import (
    GenericUIContextProvider,
    UnavailableCameraService,
    UnavailableInputController,
    UnavailablePermissionProvider,
)
from utils.config_manager import ConfigManager


class FakeHoldMonitor:
    def __init__(self, start_result=True):
        self.configured = []
        self.start_count = 0
        self.stop_count = 0
        self.held = False
        self.start_result = start_result

    def configure(self, shortcut):
        self.configured.append(shortcut)
        return bool(shortcut)

    def start(self):
        self.start_count += 1
        return self.start_result

    def stop(self):
        self.stop_count += 1
        self.held = False

    def is_held(self):
        return self.held


def _services(monitor):
    permissions = UnavailablePermissionProvider()
    return PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test",
            architecture="test",
            permissions=PermissionSnapshot(
                camera=AuthorizationState.GRANTED,
                accessibility=AuthorizationState.GRANTED,
            ),
        ),
        input_controller=UnavailableInputController("test"),
        context_provider=GenericUIContextProvider(),
        permission_provider=permissions,
        camera_service=UnavailableCameraService(),
        hold_shortcut_monitor=monitor,
    )


def test_main_window_starts_hold_monitor_only_after_worker_start_and_stops_on_normal_stop(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    monitor = FakeHoldMonitor()
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "hold_shortcut")
    config.set("control_session", "hold_shortcut", "cmd+a")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services(monitor))
    window = main_window.MainWindow()
    monkeypatch.setattr(window, "_start_video_worker", lambda: True)
    try:
        window.is_running = True
        window._start_after_camera_permission()
        assert monitor.configured[-1] == "cmd+a"
        assert monitor.start_count == 1

        window.toggle_running()
        assert monitor.stop_count >= 1
    finally:
        window.close()


def test_main_window_passes_monitor_held_state_to_control_session_per_frame(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monitor = FakeHoldMonitor()
    monitor.held = True
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "hold_shortcut")
    config.set("control_session", "hold_shortcut", "cmd+a")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services(monitor))
    window = main_window.MainWindow()
    try:
        monitor.held = True
        captured = {}
        window.is_running = True
        window.control_session.update = lambda **kwargs: captured.update(kwargs)
        window._update_power_mode = lambda landmarks, **_kwargs: None
        window.tracker.update = lambda landmarks, shape, **_kwargs: (None, False)
        window._check_edge_lost = lambda landmarks, now: None
        window.classifier.classify = lambda landmarks, **_kwargs: "none"
        window._refresh_control_session_status = lambda **_kwargs: None
        window.classifier.get_pinch_info = lambda landmarks, **_kwargs: None
        window._get_status_text = lambda detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda frame: None
        frame = type("Frame", (), {"shape": (10, 10, 3)})()
        landmark_frame = type("LandmarkFrame", (), {"frame": frame, "landmarks": []})()

        window.process_frame(landmark_frame)

        assert captured["shortcut_held"] is True
    finally:
        window.close()


def test_session_exit_frame_releases_drag_even_without_a_pointer_position(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    released = []
    try:
        window.is_running = True
        window.control_session.state = main_window.SessionState.POINTER
        window.control_session.update = lambda **_kwargs: setattr(
            window.control_session, "state", main_window.SessionState.INACTIVE
        )
        window.action_coordinator.stop = lambda: released.append(True)
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

        assert released == [True]
    finally:
        window.close()


def test_main_window_stops_monitor_when_settings_refresh_reconfigures_session(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monitor = FakeHoldMonitor()
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "hold_shortcut")
    config.set("control_session", "hold_shortcut", "cmd+a")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services(monitor))
    window = main_window.MainWindow()
    try:
        assert monitor.configured[-1] == "cmd+a"
        config.set("control_session", "mode", ActivationMode.GESTURE.value)
        window._refresh_control_session_from_config()
        assert monitor.stop_count >= 1
    finally:
        window.close()


def test_start_reconfigures_recreated_monitor_and_starts_it_only_after_worker_success(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    initial_monitor = FakeHoldMonitor()
    refreshed_monitor = FakeHoldMonitor()
    monitors = iter((initial_monitor, refreshed_monitor))
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "hold_shortcut")
    config.set("control_session", "hold_shortcut", "cmd+a")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services(next(monitors)))
    window = main_window.MainWindow()
    monkeypatch.setattr(window, "_start_video_worker", lambda: False)
    try:
        window.toggle_running()

        assert refreshed_monitor.configured == ["cmd+a"]
        assert refreshed_monitor.start_count == 0

        window.is_running = True
        monkeypatch.setattr(window, "_start_video_worker", lambda: True)
        window._start_after_camera_permission()
        assert refreshed_monitor.start_count == 1
    finally:
        window.close()


def test_hold_shortcut_start_failure_is_visible_and_stops_running_session(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monitor = FakeHoldMonitor(start_result=False)
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "hold_shortcut")
    config.set("control_session", "hold_shortcut", "cmd+a")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services(monitor))
    window = main_window.MainWindow()
    stopped_workers = []
    monkeypatch.setattr(window, "_start_video_worker", lambda: True)
    monkeypatch.setattr(window, "_stop_video_worker", lambda: stopped_workers.append(True))
    try:
        window.is_running = True
        window._start_after_camera_permission()

        assert monitor.start_count == 1
        assert window.is_running is False
        assert stopped_workers == [True]
        assert window.status_indicator.text() == tr("main.hold_shortcut_unavailable")
    finally:
        window.close()


def test_saving_settings_while_running_restarts_hold_shortcut_monitor(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monitor = FakeHoldMonitor()
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "hold_shortcut")
    config.set("control_session", "hold_shortcut", "cmd+a")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services(monitor))
    window = main_window.MainWindow()

    class AcceptedSettings:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 1

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", AcceptedSettings)
    monkeypatch.setattr(window, "_start_video_worker", lambda: True)
    try:
        window.is_running = True
        window.open_settings()

        assert monitor.start_count == 1
    finally:
        window.close()

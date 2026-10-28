import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from gui import main_window
from gui.i18n import tr
from core.control_session import SessionState
from core.static_gesture_template import StaticGestureMatcher
from platform_services.contracts import ActionResult, PlatformCapabilities, PlatformServices
from platform_services.null import (
    GenericUIContextProvider,
    NullHoldShortcutMonitor,
    UnavailableInputController,
    UnavailablePermissionProvider,
)
from utils.config_manager import ConfigManager


class UnavailableSelectedCameraService:
    def __init__(self):
        self.open_calls = []

    def list_devices(self):
        return []

    def open_selected(self, device_id, width, height):
        self.open_calls.append((device_id, width, height))
        return None


class FakeDetector:
    def release(self):
        pass


def test_hud_dispatch_failure_uses_fixed_safe_message_not_raw_diagnostic(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    window = main_window.MainWindow()
    try:
        raw_reason = "RAW_DIAGNOSTIC_MARKER <AXValue=secret> frame=123"

        window._update_hud_after_dispatch(
            "custom_hotkey",
            ActionResult(False, raw_reason, "unknown_runtime_failure"),
            (12, 24),
        )

        assert window.hud.message == tr("main.control_unavailable")
        assert raw_reason not in window.hud.message
        assert "AXValue" not in window.hud.message
        assert "frame=" not in window.hud.message
    finally:
        window.close()


def _wait_until(predicate, timeout_ms=3000):
    """Wait for a worker-thread side effect instead of guessing a duration.

    A fixed 100 ms wait is enough on an idle machine and too short when the
    whole suite is running, which made these two tests intermittently red.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(10)
    return predicate()


def _services_with_camera(camera_service):
    permissions = UnavailablePermissionProvider()
    return PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test",
            architecture="test",
            permissions=permissions.snapshot(),
        ),
        input_controller=UnavailableInputController("test"),
        context_provider=GenericUIContextProvider(),
        permission_provider=permissions,
        camera_service=camera_service,
        hold_shortcut_monitor=NullHoldShortcutMonitor(),
    )


def test_main_window_reports_selected_camera_unavailable_without_opening_fallback(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("camera", "device_id", "usb-missing")
    config.set("camera", "id", 2)
    service = UnavailableSelectedCameraService()
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services_with_camera(service))
    monkeypatch.setattr(main_window, "create_detector", lambda *_args, **_kwargs: FakeDetector())
    legacy_calls = []
    monkeypatch.setattr(
        main_window,
        "open_camera",
        lambda camera_id: legacy_calls.append(camera_id) or object(),
    )

    window = main_window.MainWindow()
    try:
        window.is_running = True
        window._start_after_camera_permission()
        # Wait for the *outcome*, not the call: the worker opens the camera
        # first and only then reports the failure that must stop control.
        _wait_until(lambda: service.open_calls and window.is_running is False)

        assert service.open_calls == [("usb-missing", 640, 480)]
        assert legacy_calls == []
        assert window.is_running is False
        # The state bullet moved out of the text and into the themed dot.
        assert window.status_indicator.text() == tr("main.selected_camera_unavailable")
        assert window.state_dot.property("semantic") == "denied"
    finally:
        window.close()


def test_camera_start_failure_resets_control_session_and_releases_drag(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("camera", "device_id", "usb-missing")
    service = UnavailableSelectedCameraService()
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: _services_with_camera(service))
    monkeypatch.setattr(main_window, "create_detector", lambda *_args, **_kwargs: FakeDetector())
    window = main_window.MainWindow()
    release_calls = []
    try:
        window.control_session.state = SessionState.POINTER
        window.action_coordinator.stop = lambda: release_calls.append(True)
        window.is_running = True

        window._start_after_camera_permission()
        _wait_until(lambda: window.control_session.state is SessionState.INACTIVE)

        assert window.control_session.state is SessionState.INACTIVE
        assert release_calls == [True]
    finally:
        window.close()


def test_main_window_defers_worker_and_camera_until_start():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    try:
        assert window.video_worker is None
    finally:
        window.close()


def test_start_returns_before_slow_detector_and_camera_initialization(monkeypatch):
    import time

    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    try:
        window.is_running = True
        monkeypatch.setattr(main_window, "create_detector", lambda *_args, **_kwargs: time.sleep(0.2) or FakeDetector())
        monkeypatch.setattr(main_window, "open_configured_camera", lambda *_args, **_kwargs: time.sleep(0.2) or None)

        started = time.monotonic()
        assert window._start_video_worker() is True

        assert time.monotonic() - started < 0.1
    finally:
        window._stop_video_worker()
        window.close()


def test_worker_error_resets_control_session_and_releases_drag():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    release_calls = []
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.action_coordinator.stop = lambda: release_calls.append(True)

        window._on_worker_error("camera disconnected")

        assert window.control_session.state is SessionState.INACTIVE
        assert release_calls == [True]
    finally:
        window.close()


def test_opening_settings_releases_an_active_drag_before_pausing_worker(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    release_calls = []
    try:
        window.is_running = True
        window._stop_video_worker = lambda **_kwargs: None
        window._start_video_worker = lambda: True
        window.action_coordinator.stop = lambda: release_calls.append(True)

        class FakeSettingsDialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return 0

        monkeypatch.setattr("gui.settings_dialog.SettingsDialog", FakeSettingsDialog)
        window.open_settings()

        assert release_calls == [True]
    finally:
        window.close()


def test_main_window_restores_persisted_static_activation_template_and_arms(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "settings.json"
    matcher = StaticGestureMatcher()
    pose = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    template = matcher.create_template(
        "Custom start", [pose], threshold=0.05, template_id="custom-start"
    )
    config = ConfigManager(config_path=path)
    config.set("control_session", "custom_static_templates", [{
        "template_id": template.template_id,
        "name": template.name,
        "feature_vector": list(template.feature_vector),
        "threshold": template.threshold,
    }])
    config.set("control_session", "activation_template_id", template.template_id)
    config.set("control_session", "exit_template_id", template.template_id)
    config.save()
    persisted_config = ConfigManager(config_path=path)
    monkeypatch.setattr(main_window, "ConfigManager", lambda: persisted_config)

    window = main_window.MainWindow()
    try:
        assert window.control_session.activation_template == template
        assert window.control_session.exit_template == template
        assert window.control_session.update(
            "none", True, False, 0.0, landmarks=pose
        ) is SessionState.INACTIVE
        assert window.control_session.update(
            "none", True, False, 0.31, landmarks=pose
        ) is SessionState.ARMED
    finally:
        window.close()


def test_main_window_rebuilds_control_session_after_saved_template_selection(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "settings.json"
    matcher = StaticGestureMatcher()
    pose = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    template = matcher.create_template(
        "Custom start", [pose], threshold=0.05, template_id="custom-start"
    )
    config = ConfigManager(config_path=path)
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    window = main_window.MainWindow()
    try:
        assert window.control_session.activation_template is None
        config.set("control_session", "custom_static_templates", [{
            "template_id": template.template_id,
            "name": template.name,
            "feature_vector": list(template.feature_vector),
            "threshold": template.threshold,
        }])
        config.set("control_session", "activation_template_id", template.template_id)
        window._refresh_control_session_from_config()
        assert window.control_session.activation_template == template
    finally:
        window.close()


def test_main_window_refresh_replaces_active_template_after_config_save(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "settings.json"
    matcher = StaticGestureMatcher()
    first_pose = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    second_pose = [(float(i * i), float((i % 4) * 11), float(i % 3)) for i in range(21)]
    first_template = matcher.create_template(
        "First trigger", [first_pose], threshold=0.05, template_id="first-trigger"
    )
    second_template = matcher.create_template(
        "Second trigger", [second_pose], threshold=0.05, template_id="second-trigger"
    )
    config = ConfigManager(config_path=path)
    config.set("control_session", "custom_static_templates", [{
        "template_id": first_template.template_id,
        "name": first_template.name,
        "feature_vector": list(first_template.feature_vector),
        "threshold": first_template.threshold,
    }])
    config.set("control_session", "activation_template_id", first_template.template_id)
    config.save()
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    window = main_window.MainWindow()
    try:
        assert window.control_session.activation_template == first_template

        config.set("control_session", "custom_static_templates", [{
            "template_id": second_template.template_id,
            "name": second_template.name,
            "feature_vector": list(second_template.feature_vector),
            "threshold": second_template.threshold,
        }])
        config.set("control_session", "activation_template_id", second_template.template_id)
        config.save()
        window._refresh_control_session_from_config()

        assert window.control_session.activation_template == second_template
        assert window.custom_static_templates == {second_template.template_id: second_template}
    finally:
        window.close()


@pytest.mark.parametrize(
    "custom_templates",
    [
        {"not": "a template list"},
        "not a template list",
        [
            {"template_id": "not-numeric", "name": "Bad", "feature_vector": ["x"] * 63},
            {"template_id": "not-finite", "name": "Bad", "feature_vector": [float("nan")] * 63},
            {"template_id": "boolean-vector", "name": "Bad", "feature_vector": [True] * 63},
            {"template_id": "wrong-size", "name": "Bad", "feature_vector": [0.0] * 62},
            {"template_id": "infinite-threshold", "name": "Bad", "feature_vector": [0.0] * 63, "threshold": float("inf")},
            {"template_id": "zero-threshold", "name": "Bad", "feature_vector": [0.0] * 63, "threshold": 0.0},
            {"template_id": "negative-threshold", "name": "Bad", "feature_vector": [0.0] * 63, "threshold": -0.1},
            {"template_id": "string-threshold", "name": "Bad", "feature_vector": [0.0] * 63, "threshold": "0.1"},
        ],
    ],
)
def test_main_window_ignores_malformed_persisted_static_templates(
    tmp_path, monkeypatch, custom_templates
):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "custom_static_templates", custom_templates)
    config.set("control_session", "activation_template_id", "not-numeric")
    config.set("control_session", "exit_template_id", "not-numeric")
    config.save()
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    window = main_window.MainWindow()
    try:
        assert window.custom_static_templates == {}
        assert window.control_session.activation_template is None
        assert window.control_session.exit_template is None
        assert window.control_session.update(
            "open_hand", True, False, 0.0, landmarks=[(0.0, 0.0, 0.0)] * 21
        ) is SessionState.INACTIVE
    finally:
        window.close()

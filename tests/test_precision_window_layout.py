import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from gui import main_window
from gui.i18n import DEFAULT_LOCALE, current_locale, set_locale, tr
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
)


class GrantedPermissions:
    def snapshot(self):
        return PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.GRANTED,
        )

    def request_accessibility_prompt(self):
        return False


class MissingAccessibilityPermissions:
    def snapshot(self):
        return PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.DENIED,
        )

    def request_accessibility_prompt(self):
        return False


def _services_with_missing_accessibility(**_kwargs):
    permissions = MissingAccessibilityPermissions()
    return PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos",
            architecture="arm64",
            permissions=permissions.snapshot(),
        ),
        input_controller=UnavailableInputController("not used by this layout test"),
        context_provider=GenericUIContextProvider(),
        permission_provider=permissions,
        camera_service=UnavailableCameraService(),
    )


def _services_with_granted_permissions(**_kwargs):
    permissions = GrantedPermissions()
    return PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos",
            architecture="arm64",
            permissions=permissions.snapshot(),
        ),
        input_controller=UnavailableInputController("not used by this layout test"),
        context_provider=GenericUIContextProvider(),
        permission_provider=permissions,
        camera_service=UnavailableCameraService(),
    )


def setup_function():
    set_locale(DEFAULT_LOCALE)


def test_precision_main_window_has_one_primary_control_and_no_training_button(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_missing_accessibility)
    window = main_window.MainWindow()
    try:
        assert window.primary_control_button.text() == "授予辅助功能权限"
        assert window.session_card.objectName() == "sessionCard"
        assert window.minimumWidth() >= 1200
        assert not hasattr(window, "collect_btn")
    finally:
        window.close()


def test_precision_main_window_retranslates_existing_controls(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    config = main_window.ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_missing_accessibility)
    window = main_window.MainWindow()
    try:
        assert window.windowTitle() == "PinchCursor"
        assert window.settings_btn.text() == "设置"
        assert window.camera_summary.text() == "请在设置中选择摄像头"

        config.set("ui", "language", "en_US")
        set_locale(config.get("ui", "language"))
        window.retranslate_ui()

        assert window.windowTitle() == "PinchCursor"
        assert window.settings_btn.text() == "Settings"
        assert window.primary_control_button.text() == "Grant Accessibility access"
        # Permissions are two rows with their own state, not one run-on sentence:
        # a blocked permission must be readable without parsing prose.
        assert window.permission_rows["camera"][1].text() == "Camera"
        assert window.permission_rows["camera"][2].text() == "Granted"
        assert window.permission_rows["accessibility"][1].text() == "Accessibility"
        assert window.permission_rows["accessibility"][2].text() == "Denied"
        assert window.camera_summary.text() == "Select a camera in Settings"
    finally:
        window.close()


def test_precision_console_has_change_actions_for_configuration_summaries(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_missing_accessibility)
    window = main_window.MainWindow()
    try:
        # Each summary row is itself the control that opens its settings section,
        # so there is no separate "更改" button to count.
        opened = []
        monkeypatch.setattr(window, "open_settings", lambda section_id=None: opened.append(section_id))
        for name in ("activation", "camera", "permissions"):
            window.summary_rows[name].clicked.emit()
        assert opened == ["control", "camera", "permissions"]
        assert window.camera_summary.text() == "请在设置中选择摄像头"
    finally:
        window.close()


def test_precision_console_hides_permissions_when_nothing_blocks_start(monkeypatch):
    """Two "granted" lines are noise on a console that is ready to run."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_granted_permissions)
    window = main_window.MainWindow()
    try:
        assert window.permission_row.isHidden() is True
    finally:
        window.close()


def test_precision_console_shows_permissions_when_one_is_missing(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_missing_accessibility)
    window = main_window.MainWindow()
    try:
        assert window.permission_row.isHidden() is False
    finally:
        window.close()


def test_precision_console_falls_back_to_safe_permission_copy_for_unknown_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_missing_accessibility)
    window = main_window.MainWindow()
    try:
        set_locale("en_US")

        assert window._permission_state_text("unexpected") == "Unavailable"
    finally:
        window.close()


def test_main_window_localizes_camera_denial_and_hold_shortcut_status(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "create_platform_services", _services_with_missing_accessibility)
    window = main_window.MainWindow()
    try:
        set_locale("en_US")

        window._on_camera_permission_result(False)
        assert window.status_indicator.text() == "● Camera access was not granted"

        window.is_running = True
        window._start_video_worker = lambda: True
        window._start_hold_shortcut_monitor = lambda: False
        window._start_after_camera_permission()
        assert window.status_indicator.text() == "Hold shortcut unavailable — control stopped"
    finally:
        window.close()


def test_precision_console_shows_the_camera_persisted_by_settings(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])

    class CameraService:
        def list_devices(self):
            from platform_services.contracts import CameraDevice
            return [
                CameraDevice("built-in", "Built-in camera", "built_in", True),
                CameraDevice("external", "USB camera", "external", True),
            ]

    permissions = MissingAccessibilityPermissions()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos",
            architecture="arm64",
            permissions=permissions.snapshot(),
        ),
        input_controller=UnavailableInputController("not used by this layout test"),
        context_provider=GenericUIContextProvider(),
        permission_provider=permissions,
        camera_service=CameraService(),
    )
    config = main_window.ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: services)
    window = main_window.MainWindow()
    try:
        assert not hasattr(window, "home_camera_selector")
        assert config.get("camera", "device_id") == ""
        assert window.camera_summary.text() == "请在设置中选择摄像头"

        config.set("camera", "device_id", "external")
        window._refresh_precision_console()

        assert window.camera_summary.text() == "USB camera"
    finally:
        window.close()

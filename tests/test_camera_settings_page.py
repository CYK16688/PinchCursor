import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.camera_settings_page import CameraSettingsPage
from gui.i18n import DEFAULT_LOCALE, set_locale
from platform_services.contracts import CameraDevice
from utils.config_manager import ConfigManager


class FakeCameraService:
    def __init__(self):
        self.calls = 0

    def list_devices(self):
        self.calls += 1
        return [
            CameraDevice("built-in", "Built-in camera", "built_in", True),
            CameraDevice("external", "USB camera", "external", False),
        ]


def test_camera_page_persists_selected_stable_device_id_only_when_applied(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    camera_service = FakeCameraService()
    page = CameraSettingsPage(config, camera_service)
    try:
        assert camera_service.calls == 1
        assert config.get("camera", "device_id") == ""

        page.select_device("built-in")
        assert config.get("camera", "device_id") == ""

        page.apply_to_config()
        assert config.get("camera", "device_id") == "built-in"
    finally:
        page.close()


def test_camera_page_retranslates_static_copy_without_translating_device_name(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("camera", "device_id", "built-in")
    page = CameraSettingsPage(config, FakeCameraService())
    try:
        assert page.title_label.text() == "摄像头"
        assert page.refresh_button.text() == "刷新摄像头"
        assert page.selected_status.text() == "已选择：Built-in camera · 可用"

        set_locale("en_US")
        page.retranslate_ui()

        assert page.title_label.text() == "Camera"
        assert page.refresh_button.text() == "Refresh cameras"
        assert page.selected_status.text() == "Selected: Built-in camera · Available"
    finally:
        page.close()


def test_camera_page_names_selected_device_and_requested_resolution(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("camera", "device_id", "built-in")
    page = CameraSettingsPage(config, FakeCameraService())
    try:
        assert page.selected_status.text() == "已选择：Built-in camera · 可用"
        assert page.resolution_note.text() == "将在下次会话应用请求的分辨率"

        page.select_device("external")

        assert page.selected_status.text() == "已选择：USB camera · 不可用"
    finally:
        page.close()

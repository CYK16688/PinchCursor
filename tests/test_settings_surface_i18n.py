import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from gui.i18n import set_locale
from gui.settings_dialog import SettingsDialog
from utils.config_manager import ConfigManager


def test_current_settings_surfaces_retranslate_without_mutating_staged_camera_selection(tmp_path):
    app = QApplication.instance() or QApplication([])
    set_locale("zh_CN")
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.open_section("gestures")
        selected_device_id = dialog.camera_page.selected_device_id
        width = dialog.camera_page.width_input.value()
        height = dialog.camera_page.height_input.value()

        set_locale("en_US")
        dialog.retranslate_ui()

        visible_text = [label.text() for label in dialog.findChildren(QLabel)]
        assert dialog.current_section_id == "gestures"
        assert dialog.camera_page.title_label.text() == "Camera"
        assert dialog.dynamic_gesture_page.title_label.text() == "Dynamic shortcuts"
        assert "Core pointer controls" in visible_text
        assert dialog.camera_page.selected_device_id == selected_device_id
        assert dialog.camera_page.width_input.value() == width
        assert dialog.camera_page.height_input.value() == height
    finally:
        dialog.close()

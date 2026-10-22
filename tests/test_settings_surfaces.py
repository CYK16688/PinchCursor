import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from gui.i18n import tr
from gui.settings_dialog import SettingsDialog
from utils.config_manager import ConfigManager


def test_every_settings_section_has_a_named_operational_surface(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        expected_titles = {
            "control": tr("settings.control.title"),
            "gestures": tr("gestures.core"),
            "camera": tr("camera.title"),
            "feedback": tr("feedback.title"),
            "permissions": tr("settings.permissions.title"),
            "advanced": tr("settings.advanced.title"),
        }
        for section, title in expected_titles.items():
            dialog.open_section(section)
            labels = [label.text() for label in dialog.sections.currentWidget().findChildren(QLabel)]
            assert title in labels
    finally:
        dialog.close()


def test_control_selectors_include_and_persist_custom_static_template_ids(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "custom_static_templates", [{
        "template_id": "custom-start",
        "name": "Custom start",
        "feature_vector": [0.0] * 63,
        "threshold": 0.05,
    }])
    config.set("control_session", "activation_template_id", "custom-start")
    config.set("control_session", "exit_template_id", "custom-start")
    dialog = SettingsDialog(config)
    try:
        activation_index = dialog.activation_gesture.findData("custom-start")
        exit_index = dialog.exit_gesture.findData("custom-start")

        assert activation_index >= 0
        assert exit_index >= 0
        assert dialog.activation_gesture.currentData() == "custom-start"
        assert dialog.exit_gesture.currentData() == "custom-start"
        dialog.activation_gesture.setCurrentIndex(activation_index)
        dialog.exit_gesture.setCurrentIndex(exit_index)
        dialog.save_settings()

        assert config.get("control_session", "activation_template_id") == "custom-start"
        assert config.get("control_session", "exit_template_id") == "custom-start"
        assert config.get("control_session", "activation_gesture") == "open_hand"
        assert config.get("control_session", "exit_gesture") == "fist"

        dialog.activation_gesture.setCurrentIndex(dialog.activation_gesture.findData("peace"))
        dialog.exit_gesture.setCurrentIndex(dialog.exit_gesture.findData("point"))
        dialog.save_settings()

        assert config.get("control_session", "activation_template_id") == ""
        assert config.get("control_session", "exit_template_id") == ""
        assert config.get("control_session", "activation_gesture") == "peace"
        assert config.get("control_session", "exit_gesture") == "point"
    finally:
        dialog.close()


def test_custom_static_trigger_is_staged_until_settings_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    template = {
        "template_id": "staged-start",
        "name": "Staged start",
        "feature_vector": [0.0] * 63,
        "threshold": 0.05,
    }
    try:
        dialog.stage_static_template(template)

        assert config.get("control_session", "custom_static_templates") == []
        assert dialog.activation_gesture.findData("staged-start") >= 0

        dialog.save_settings()

        assert config.get("control_session", "custom_static_templates") == [template]
    finally:
        dialog.close()


def test_permissions_page_exposes_explicit_camera_request_action(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        dialog.open_section("permissions")
        labels = [button.text() for button in dialog.sections.currentWidget().findChildren(QPushButton)]

        assert tr("settings.permissions.request_camera") in labels
    finally:
        dialog.close()


def test_permissions_camera_request_never_starts_control(tmp_path):
    app = QApplication.instance() or QApplication([])

    class Parent(QWidget):
        def __init__(self):
            super().__init__()
            self.permission_requests = 0
            self.starts = 0

        def request_camera_permission(self):
            self.permission_requests += 1

        def request_camera_permission_and_start(self):
            self.starts += 1

    parent = Parent()
    dialog = SettingsDialog(ConfigManager(config_path=tmp_path / "settings.json"), parent=parent)
    try:
        dialog._request_camera_from_parent()

        assert parent.permission_requests == 1
        assert parent.starts == 0
    finally:
        dialog.close()
        parent.close()

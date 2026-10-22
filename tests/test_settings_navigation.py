import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

from gui import main_window
from gui.settings_dialog import SettingsDialog
from utils.config_manager import ConfigManager


def test_settings_can_open_camera_section(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.open_section("camera")

        assert dialog.current_section_id == "camera"
    finally:
        dialog.close()


def test_settings_save_applies_control_and_camera_page_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.session_mode.setCurrentIndex(dialog.session_mode.findData("always"))
        dialog.stability_seconds.setValue(450)
        dialog.camera_page.width_input.setValue(1280)
        dialog.camera_page.height_input.setValue(720)

        dialog.save_settings()

        assert config.get("control_session", "mode") == "always"
        assert config.get("control_session", "stability_seconds") == 0.45
        assert config.get("camera", "width") == 1280
        assert config.get("camera", "height") == 720
    finally:
        dialog.close()


def test_control_page_only_shows_fields_relevant_to_the_selected_mode(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        dialog.session_mode.setCurrentIndex(dialog.session_mode.findData("hold_shortcut"))

        assert not dialog.hold_shortcut.isHidden()
        assert dialog.activation_gesture.isHidden()
        assert not dialog.exit_gesture.isHidden()

        dialog.session_mode.setCurrentIndex(dialog.session_mode.findData("always"))

        assert dialog.activation_gesture.isHidden()
        assert dialog.hold_shortcut.isHidden()
        assert not dialog.always_active_notice.isHidden()
    finally:
        dialog.close()


def test_restore_defaults_resets_control_camera_and_feedback_without_writing_config(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.session_mode.setCurrentIndex(dialog.session_mode.findData("always"))
        dialog.camera_page.width_input.setValue(1280)
        dialog.feedback_page.mode_combo.setCurrentIndex(dialog.feedback_page.mode_combo.findData("quiet"))

        dialog.reset_defaults()

        assert dialog.session_mode.currentData() == "gesture"
        assert dialog.camera_page.width_input.value() == 640
        assert dialog.feedback_page.mode_combo.currentData() == "standard"
        assert config.get("control_session", "mode") == "gesture"
    finally:
        dialog.close()


def test_contextual_intent_preference_is_staged_until_settings_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.intent_actions_check.setChecked(False)

        assert config.get("context_aware", "intent_actions_enabled") is True
        dialog.save_settings()

        assert config.get("context_aware", "intent_actions_enabled") is False
    finally:
        dialog.close()


def test_language_selection_is_staged_until_settings_save_or_cancel(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en_US"))

        assert config.get("ui", "language") == "zh_CN"
        dialog.reject()

        assert config.get("ui", "language") == "zh_CN"
    finally:
        dialog.close()


def test_settings_dialog_retranslates_control_permissions_and_children_without_mutating_staged_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    template = {
        "template_id": "custom-start",
        "name": "用户触发",
        "feature_vector": [0.0] * 63,
        "threshold": 0.05,
    }
    try:
        dialog.stage_static_template(template)
        dialog.session_mode.setCurrentIndex(dialog.session_mode.findData("hold_shortcut"))
        dialog.hold_shortcut.setText("ctrl+shift+p")
        dialog.dynamic_gesture_page.enabled_check.setChecked(True)
        dialog.dynamic_gesture_page.action_selector.setCurrentIndex(
            dialog.dynamic_gesture_page.action_selector.findData("custom_hotkey")
        )

        from gui.i18n import set_locale
        set_locale("en_US")
        dialog.retranslate_ui()

        assert dialog.windowTitle() == "Gesture Control Settings"
        assert dialog.title_label.text() == "Settings"
        assert dialog.reset_button.text() == "Restore defaults"
        assert dialog.control_title_label.text() == "Control session"
        assert dialog.permissions_title_label.text() == "Permissions"
        assert dialog.camera_page.title_label.text() == "Camera"
        assert dialog.feedback_page.title_label.text() == "Feedback"
        assert dialog.dynamic_gesture_page.title_label.text() == "Dynamic shortcuts"
        assert dialog.session_mode.currentData() == "hold_shortcut"
        assert dialog.hold_shortcut.text() == "ctrl+shift+p"
        assert dialog.activation_gesture.findData("custom-start") >= 0
        assert dialog.dynamic_gesture_page.enabled_check.isChecked() is True
        assert dialog.dynamic_gesture_page.action_selector.currentData() == "custom_hotkey"
        assert config.get("control_session", "hold_shortcut") == ""
    finally:
        dialog.close()


def test_settings_advanced_retranslates_without_mutating_staged_context_or_zone_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    original_zone_rules = config.get("zone_rules")
    dialog = SettingsDialog(config)
    try:
        dialog.context_checkboxes["text_input"]["point"].setChecked(True)
        dialog._add_zone_rule()
        zone = dialog.zones_list.itemAt(0).widget().zone_data
        zone["x"].setValue(123)
        zone["drag"].setChecked(True)

        from gui.i18n import set_locale
        set_locale("en_US")
        dialog.retranslate_ui()

        visible_text = [label.text() for label in dialog.findChildren(QLabel)]
        visible_text.extend(button.text() for button in dialog.findChildren(QPushButton))
        visible_text.extend(group.title() for group in dialog.findChildren(QGroupBox))
        assert "Mouse control" in visible_text
        assert "Add combo" in visible_text
        assert "Add zone rule" in visible_text
        assert "X:" in visible_text
        assert dialog.context_checkboxes["text_input"]["point"].isChecked() is True
        assert zone["x"].value() == 123
        assert zone["drag"].isChecked() is True
        assert config.get("zone_rules") == original_zone_rules
    finally:
        dialog.close()


def test_settings_save_persists_the_selected_language(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en_US"))

        dialog.save_settings()

        assert config.get("ui", "language") == "en_US"
    finally:
        dialog.close()


def test_saved_language_refreshes_the_live_main_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    class AcceptedSettings:
        def __init__(self, live_config, *_args, **_kwargs):
            self.live_config = live_config

        def exec(self):
            self.live_config.set("ui", "language", "en_US")
            return 1

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", AcceptedSettings)
    window = main_window.MainWindow()
    try:
        assert window.windowTitle() == "手势控制"

        window.open_settings()

        assert window.windowTitle() == "Gesture Control"
        assert window.settings_btn.text() == "Settings"
    finally:
        window.close()


def test_cancelled_language_selection_leaves_live_main_window_unchanged(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    class CancelledSettings:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", CancelledSettings)
    window = main_window.MainWindow()
    try:
        window.open_settings()

        assert window.windowTitle() == "手势控制"
        assert window.settings_btn.text() == "设置"
    finally:
        window.close()


def test_main_settings_button_ignores_clicked_checked_argument(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    opened_sections = []

    class CancelledSettings:
        def __init__(self, *_args, **_kwargs):
            pass

        def open_section(self, section_id):
            opened_sections.append(section_id)

        def exec(self):
            return 0

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", CancelledSettings)
    window = main_window.MainWindow()
    try:
        window.settings_btn.click()

        assert opened_sections == []
    finally:
        window.close()


def test_open_settings_does_not_print_raw_dialog_exception(tmp_path, monkeypatch, capsys):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    marker = "RAW_SETTINGS_DIAGNOSTIC <AXValue=secret>"

    class BrokenSettings:
        def __init__(self, *_args, **_kwargs):
            pass

        def open_section(self, _section_id):
            raise RuntimeError(marker)

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", BrokenSettings)
    window = main_window.MainWindow()
    try:
        window.open_settings("camera")

        captured = capsys.readouterr()
        assert marker not in captured.err
        assert marker not in captured.out
    finally:
        window.close()

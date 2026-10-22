import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from gui.dynamic_gesture_settings_page import DynamicGestureSettingsPage
from gui.i18n import set_locale, tr
from gui.settings_dialog import SettingsDialog
from utils.config_manager import ConfigManager


def _record(name="Swipe up"):
    return {
        "template_id": name.lower().replace(" ", "-"),
        "name": name,
        "action": "scroll_up",
        "hotkey": "",
        "samples": [[[0.0] * 63, [0.1] * 63]],
        "threshold": 0.18,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
    }


def test_dynamic_action_constants_keep_display_text_and_stable_action_ids():
    assert DynamicGestureSettingsPage.ACTIONS == (
        ("Scroll up", "scroll_up"),
        ("Scroll down", "scroll_down"),
        ("Custom shortcut", "custom_hotkey"),
    )


def test_dynamic_page_stages_add_and_delete_without_mutating_config_until_apply(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    page = DynamicGestureSettingsPage(config)
    try:
        page.stage_add(_record())
        assert config.get("dynamic_gestures", "templates") == []
        page.stage_delete("swipe-up")
        assert page.staged_templates == []
        assert config.get("dynamic_gestures", "templates") == []

        page.stage_add(_record())
        page.apply_to_config()
        assert config.get("dynamic_gestures", "templates")[0]["name"] == "Swipe up"
    finally:
        page.close()


def test_dynamic_shortcut_enablement_is_staged_until_apply(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    page = DynamicGestureSettingsPage(config)
    try:
        assert page.enabled_check.isChecked() is False
        page.enabled_check.setChecked(True)
        assert config.get("dynamic_gestures", "enabled") is False

        page.apply_to_config()
        assert config.get("dynamic_gestures", "enabled") is True
    finally:
        page.close()


def test_settings_cancel_leaves_dynamic_config_unchanged_and_save_applies_staged_templates(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    first = SettingsDialog(config)
    try:
        first.dynamic_gesture_page.stage_add(_record())
        first.reject()
        assert config.get("dynamic_gestures", "templates") == []
    finally:
        first.close()

    second = SettingsDialog(config)
    try:
        second.dynamic_gesture_page.stage_add(_record())
        second.save_settings()
        assert config.get("dynamic_gestures", "templates")[0]["template_id"] == "swipe-up"
    finally:
        second.close()


def test_dynamic_page_retranslates_static_copy_without_mutating_staged_templates(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = DynamicGestureSettingsPage(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        page.enabled_check.setChecked(True)
        localized_record = _record("localized-template")
        localized_record["name"] = "用户模板"
        page.stage_add(localized_record)
        page.action_selector.setCurrentIndex(page.action_selector.findData("custom_hotkey"))

        assert page.title_label.text() == "动态快捷手势"
        assert page.record_button.text() == "录制动态快捷手势"
        assert page.list_label.text() == "用户模板"

        set_locale("en_US")
        page.retranslate_ui()

        assert page.title_label.text() == "Dynamic shortcuts"
        assert page.record_button.text() == "Record dynamic shortcut"
        assert page.action_selector.currentData() == "custom_hotkey"
        assert page.enabled_check.isChecked() is True
        assert page.staged_templates[0]["name"] == "用户模板"
        assert any(
            button.text() == tr("settings.dynamic.delete")
            for button in page.findChildren(QPushButton)
        )
    finally:
        page.close()


def test_dynamic_shortcuts_live_inside_gestures_surface_with_exact_actions(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        assert "dynamic" not in dialog.section_ids
        dialog.open_section("gestures")
        assert dialog.gesture_page is not None
        # The dynamic section must live inside the gestures surface, not as
        # a separate settings section. It sits inside that page's scroll
        # content now, so assert ancestry rather than direct parentage.
        node = dialog.dynamic_gesture_page
        while node is not None and node is not dialog.gesture_page:
            node = node.parent()
        assert node is dialog.gesture_page
        action_labels = [dialog.dynamic_gesture_page.action_selector.itemText(i)
                         for i in range(dialog.dynamic_gesture_page.action_selector.count())]
        assert action_labels == [
            tr("settings.dynamic.action.scroll_up"),
            tr("settings.dynamic.action.scroll_down"),
            tr("settings.dynamic.action.custom_hotkey"),
        ]
        assert any(
            button.text() == tr("settings.dynamic.record")
            for button in dialog.gesture_page.findChildren(QPushButton)
        )
    finally:
        dialog.close()


def test_worker_unavailable_releases_capture_and_detector(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    page = DynamicGestureSettingsPage(config)

    class Capture:
        def __init__(self): self.released = False
        def isOpened(self): return False
        def release(self): self.released = True

    class Detector:
        def __init__(self): self.released = False
        def release(self): self.released = True

    capture, detector = Capture(), Detector()
    monkeypatch.setattr("core.detector_factory.create_detector", lambda *args: detector)
    monkeypatch.setattr("platform_services.camera_selection.open_configured_camera", lambda *args, **kwargs: capture)
    from gui.dynamic_gesture_record_dialog import DynamicGestureRecordDialog
    dialog = DynamicGestureRecordDialog()
    try:
        assert page._start_recording_worker(dialog) is None
        assert capture.released is True
        assert detector.released is True
        assert dialog.preview.text() == "无法打开所选摄像头"
    finally:
        dialog.close()
        page.close()


def test_dynamic_shortcut_rows_expose_a_delete_action(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = DynamicGestureSettingsPage(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        page.stage_add(_record())

        assert any(
            button.text() == tr("settings.dynamic.delete")
            for button in page.findChildren(QPushButton)
        )
    finally:
        page.close()


def test_cleanup_releases_detector_even_when_worker_is_absent():
    app = QApplication.instance() or QApplication([])
    from gui.dynamic_gesture_record_dialog import DynamicGestureRecordDialog
    dialog = DynamicGestureRecordDialog()

    class Detector:
        def __init__(self): self.released = False
        def release(self): self.released = True

    detector = Detector()
    dialog.recording_detector = detector
    try:
        DynamicGestureSettingsPage._cleanup_recording_worker(None, dialog)
        assert detector.released is True
    finally:
        dialog.close()

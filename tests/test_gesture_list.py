import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from gui.i18n import set_locale, tr
from gui.gesture_list import GestureList
from gui.settings_dialog import SettingsDialog
from utils.config_manager import ConfigManager


def test_gesture_list_retranslates_fixed_copy_without_changing_action_ids_or_staged_details(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    try:
        enabled, action = widget.rows["thumb_up"]
        action.setCurrentIndex(action.findData("custom_hotkey"))
        editor = widget.open_details("thumb_up")
        editor.hotkey_input.setText("cmd+up")

        set_locale("en_US")
        widget.retranslate_ui()

        assert widget.group_labels() == [tr("gestures.core"), tr("gestures.optional")]
        assert action.currentData() == "custom_hotkey"
        assert editor.windowTitle() == f"{tr('gesture.thumb_up')} {tr('gesture.details')}"
        assert editor.hotkey_input.text() == "cmd+up"
        assert editor.cancel_button.text() == tr("common.cancel")
        assert editor.apply_button.text() == tr("common.apply")
    finally:
        widget.close()


def test_gesture_details_edit_stages_shortcut_without_inert_sensitivity(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    try:
        editor = widget.open_details("thumb_up")
        editor.hotkey_input.setText("cmd+up")
        editor.accept()
        widget.apply_to_config(config)

        assert config.get_gesture("thumb_up")["hotkey"] == "cmd+up"
        assert "sensitivity" not in config.get_gesture("thumb_up")
    finally:
        widget.close()


def test_gesture_rows_do_not_select_actions_unsupported_by_the_active_platform(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(
        config.get("gestures"), supported_actions=frozenset({"move_cursor", "left_click"})
    )
    try:
        enabled, action = widget.rows["thumb_up"]

        assert enabled.isChecked() is False
        assert action.currentData() == "none"
        assert action.findData("volume_up") == -1
    finally:
        widget.close()


def test_optional_gestures_exclude_pointer_lifecycle_actions(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    try:
        _, action = widget.rows["thumb_up"]
        action_ids = {action.itemData(index) for index in range(action.count())}

        assert "move_cursor" not in action_ids
        assert "drag" not in action_ids
        assert {"left_click", "right_click", "custom_hotkey"}.issubset(action_ids)
    finally:
        widget.close()


def test_core_pointer_controls_are_fixed_contracts_not_remappable(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    try:
        assert not set(widget.CORE_POINTER_IDS).intersection(widget.rows)
        assert widget.core_contracts == {
            "point": "Move pointer",
            "pinch": "Click",
            "pinch_hold": "Drag",
        }
    finally:
        widget.close()


def test_gesture_details_are_staged_until_settings_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    original = config.get_gesture("thumb_up")["hotkey"]
    dialog = SettingsDialog(config)
    try:
        editor = dialog.gesture_page.open_details("thumb_up")
        editor.hotkey_input.setText("cmd+up")
        editor.accept()

        dialog.reject()

        assert config.get_gesture("thumb_up")["hotkey"] == original
    finally:
        dialog.close()


def test_gesture_details_reuses_one_active_editor_and_discards_it_when_finished(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    try:
        editor = widget.open_details("thumb_up")

        assert widget.open_details("thumb_up") is editor
        assert widget._open_editors["thumb_up"] is editor

        editor.accept()

        assert "thumb_up" not in widget._open_editors
        assert widget.open_details("thumb_up") is not editor
    finally:
        widget.close()


def test_gesture_details_cancel_discards_editor_without_mutating_staged_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    original = dict(widget.gestures["thumb_up"])
    try:
        editor = widget.open_details("thumb_up")
        editor.hotkey_input.setText("cmd+up")
        editor.reject()

        assert "thumb_up" not in widget._open_editors
        assert widget.gestures["thumb_up"] == original
    finally:
        widget.close()


def test_finished_editor_cannot_overwrite_a_newer_staged_gesture_details_edit(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget = GestureList(config.get("gestures"))
    try:
        old_editor = widget.open_details("thumb_up")
        old_editor.hotkey_input.setText("cmd+old")
        old_editor.accept()

        newer_editor = widget.open_details("thumb_up")
        newer_editor.hotkey_input.setText("cmd+new")
        newer_editor.accept()

        old_editor.hotkey_input.setText("cmd+stale")
        widget._finish_details("thumb_up", old_editor, QDialog.Accepted)

        assert widget.gestures["thumb_up"]["hotkey"] == "cmd+new"
    finally:
        widget.close()


def test_reset_does_not_reenable_an_unsupported_default_action(tmp_path, monkeypatch):
    from gui import settings_dialog
    from platform_services.contracts import PlatformCapabilities
    from platform_services.null import UnavailablePermissionProvider

    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    capabilities = PlatformCapabilities(
        platform="test", architecture="test", supported_actions=frozenset({"move_cursor", "left_click"})
    )
    permissions = UnavailablePermissionProvider()
    monkeypatch.setattr(
        settings_dialog,
        "create_platform_services",
        lambda: type("Services", (), {
            "capabilities": capabilities,
            "camera_service": None,
            "permission_provider": permissions,
        })(),
    )
    dialog = SettingsDialog(config)
    try:
        dialog.reset_defaults()
        enabled, action = dialog.gesture_page.rows["thumb_up"]

        assert enabled.isChecked() is False
        assert action.currentData() == "none"
    finally:
        dialog.close()


def test_the_click_versus_drag_window_is_adjustable():
    """hold_time decides whether a pinch is a click or a drag; it must be editable.

    It used to be read-only text, so the single number that governs whether
    clicking feels reliable could not be changed from inside the app at all.
    """
    from copy import deepcopy

    from gui.gesture_list import GestureList
    from utils.config_manager import DEFAULT_CONFIG, ConfigManager

    gestures = deepcopy(DEFAULT_CONFIG["gestures"])
    gestures["pinch_hold"]["hold_time"] = 0.3
    widget = GestureList(gestures)
    spin = getattr(widget, "_hold_time_spin", None)

    assert spin is not None, "the hold time must be a control, not a label"
    assert spin.value() == 0.3
    # The useful band for a click-versus-drag boundary; below ~0.15 s every
    # press becomes a drag, above ~1 s a drag takes too long to start.
    assert 0.1 <= spin.minimum() <= 0.2
    assert 0.6 <= spin.maximum() <= 1.2


def test_an_adjusted_hold_time_is_persisted(tmp_path):
    from copy import deepcopy

    from gui.gesture_list import GestureList
    from utils.config_manager import DEFAULT_CONFIG, ConfigManager

    widget = GestureList(deepcopy(DEFAULT_CONFIG["gestures"]))
    widget._hold_time_spin.setValue(0.55)

    config = ConfigManager(config_path=tmp_path / "settings.json")
    widget.apply_to_config(config)

    assert config.get_gesture("pinch_hold")["hold_time"] == 0.55

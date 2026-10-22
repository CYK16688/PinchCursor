import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.combo_card import ComboCard
from gui.settings_dialog import SettingsDialog
from utils.config_manager import ConfigManager, DEFAULT_CONFIG, normalize_gesture_combos


def _dynamic_record():
    return {
        "template_id": "swipe-up",
        "name": "Swipe up",
        "action": "scroll_up",
        "hotkey": "",
        "samples": [[[0.0] * 63, [0.1] * 63]],
        "threshold": 0.18,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
    }


def test_restore_defaults_resets_every_visible_advanced_setting_before_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("detection", "confidence", 0.82)
    config.set("detection", "tracking_confidence", 0.91)
    config.set("context_aware", "enabled", False)
    config.set("context_aware", "intent_actions_enabled", False)
    config.set("context_aware", "control_gestures", {"generic": []})
    config.set("zone_rules", None, [{"x": 4, "y": 5, "w": 6, "h": 7, "allowed": ["click"]}])
    config.set("gesture_combos", None, [{"id": "legacy", "gesture1": "peace", "gesture2": "thumb_up", "action": "screenshot"}])
    config.set("dynamic_gestures", None, {"enabled": True, "templates": [_dynamic_record()]})
    dialog = SettingsDialog(config)
    try:
        dialog.reset_defaults()
        dialog.save_settings()

        assert config.get("detection") == DEFAULT_CONFIG["detection"]
        assert config.get("context_aware") == DEFAULT_CONFIG["context_aware"]
        assert config.get("zone_rules") == DEFAULT_CONFIG["zone_rules"]
        assert config.get("gesture_combos") == DEFAULT_CONFIG["gesture_combos"]
        assert config.get("dynamic_gestures") == DEFAULT_CONFIG["dynamic_gestures"]
    finally:
        dialog.close()


def test_combo_surface_and_persistence_accept_only_executable_discrete_actions(tmp_path):
    app = QApplication.instance() or QApplication([])
    card = ComboCard()
    try:
        assert [card.action_combo.itemData(index) for index in range(card.action_combo.count())] == [
            "left_click", "right_click", "double_click", "middle_click",
            "scroll_up", "scroll_down", "custom_hotkey",
        ]
    finally:
        card.close()

    assert normalize_gesture_combos([
        {"id": "unsupported", "gesture1": "peace", "gesture2": "thumb_up", "action": "screenshot"},
        {"id": "click", "gesture1": "peace", "gesture2": "thumb_up", "action": "left_click"},
        {"id": "supported", "gesture1": "peace", "gesture2": "thumb_up", "action": "scroll_up"},
    ]) == [
        {
            "id": "click", "gesture1": "peace", "gesture2": "thumb_up",
            "action": "left_click", "hotkey": "",
        },
        {
            "id": "supported", "gesture1": "peace", "gesture2": "thumb_up",
            "action": "scroll_up", "hotkey": "",
        },
    ]


def test_dynamic_page_passes_selected_action_to_the_recording_dialog(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    page = dialog.dynamic_gesture_page
    observed = []

    class Dialog:
        def __init__(self, parent=None):
            from PySide6.QtWidgets import QComboBox
            self.action_selector = QComboBox()
            for action in ("scroll_up", "scroll_down", "custom_hotkey"):
                self.action_selector.addItem(action, action)
            self.preview = type("Preview", (), {"setText": lambda *_args: None})()
            self.state = type("State", (), {"FAILED": "failed"})()
            self.saved_record = None

        def exec(self):
            observed.append(self.action_selector.currentData())
            return False

    monkeypatch.setattr("gui.dynamic_gesture_settings_page.DynamicGestureRecordDialog", Dialog)
    monkeypatch.setattr(page, "_start_recording_worker", lambda _dialog: None)
    monkeypatch.setattr(page, "_cleanup_recording_worker", lambda *_args: None)
    try:
        page.action_selector.setCurrentIndex(page.action_selector.findData("custom_hotkey"))
        page.open_recording()
        assert observed == ["custom_hotkey"]
    finally:
        dialog.close()


def test_legacy_optional_gesture_sensitivity_is_pruned_as_inert_configuration(tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set_gesture("thumb_up", "sensitivity", 72)
    config.save()

    assert "sensitivity" not in config.get_gesture("thumb_up")


def test_restore_defaults_then_cancel_preserves_all_advanced_configuration(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    original = {
        "detection": {"confidence": 0.82, "tracking_confidence": 0.91, "detector_type": "mediapipe"},
        "context_aware": {"enabled": False, "intent_actions_enabled": False, "control_gestures": {"generic": []}},
        "zone_rules": [{"x": 4, "y": 5, "w": 6, "h": 7, "allowed": ["click"]}],
        "gesture_combos": [{"id": "saved", "gesture1": "peace", "gesture2": "thumb_up", "action": "scroll_up", "hotkey": ""}],
        "dynamic_gestures": {"enabled": True, "templates": [_dynamic_record()]},
    }
    for section, value in original.items():
        config.set(section, None, value)
    dialog = SettingsDialog(config)
    try:
        dialog.reset_defaults()
        dialog.reject()

        assert config.get("detection") == original["detection"]
        assert config.get("context_aware") == original["context_aware"]
        assert config.get("zone_rules") == original["zone_rules"]
        assert config.get("gesture_combos") == original["gesture_combos"]
        assert config.get("dynamic_gestures") == original["dynamic_gestures"]
    finally:
        dialog.close()


def test_repeated_restore_defaults_does_not_duplicate_staged_zone_widgets(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("zone_rules", None, [
        {"x": 1, "y": 2, "w": 3, "h": 4, "allowed": ["click"]},
        {"x": 5, "y": 6, "w": 7, "h": 8, "allowed": ["drag"]},
    ])
    dialog = SettingsDialog(config)
    try:
        dialog.reset_defaults()
        dialog.reset_defaults()

        assert dialog.zones_list.count() == len(DEFAULT_CONFIG["zone_rules"])
    finally:
        dialog.close()


def test_restore_defaults_removes_custom_trigger_options_and_ids(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    template = {
        "template_id": "custom-start",
        "name": "Custom start",
        "feature_vector": [0.0] * 63,
        "threshold": 0.2,
    }
    try:
        assert dialog.stage_static_template(template) is True
        assert dialog.activation_gesture.findData("custom-start") >= 0
        assert dialog.exit_gesture.findData("custom-start") >= 0

        dialog.activation_gesture.setCurrentIndex(dialog.activation_gesture.findData("custom-start"))
        dialog.exit_gesture.setCurrentIndex(dialog.exit_gesture.findData("custom-start"))
        dialog.reset_defaults()

        assert dialog.activation_gesture.findData("custom-start") == -1
        assert dialog.exit_gesture.findData("custom-start") == -1
        assert dialog._selected_template_id(dialog.activation_gesture) == ""
        assert dialog._selected_template_id(dialog.exit_gesture) == ""

        dialog.save_settings()
        assert config.get("control_session", "activation_template_id") == ""
        assert config.get("control_session", "exit_template_id") == ""
        assert config.get("control_session", "custom_static_templates") == []
    finally:
        dialog.close()


def test_legacy_volume_gesture_bindings_are_pruned_as_unsupported(tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set_gesture("thumb_up", "enabled", True)
    config.set_gesture("thumb_up", "action", "volume_up")
    config.set_gesture("thumb_down", "enabled", True)
    config.set_gesture("thumb_down", "action", "volume_down")
    config.save()

    assert config.get_gesture("thumb_up")["enabled"] is False
    assert config.get_gesture("thumb_up")["action"] == "none"
    assert config.get_gesture("thumb_down")["enabled"] is False
    assert config.get_gesture("thumb_down")["action"] == "none"

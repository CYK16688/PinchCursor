import json

from utils.config_manager import CURRENT_SCHEMA_VERSION, ConfigManager


def test_missing_config_creates_current_versioned_defaults(tmp_path):
    manager = ConfigManager(config_path=tmp_path / "settings.json")

    assert manager.get("schema_version") == CURRENT_SCHEMA_VERSION
    assert manager.get("gestures", "point")["action"] == "move_cursor"


def test_ui_language_defaults_to_simplified_chinese(tmp_path):
    manager = ConfigManager(config_path=tmp_path / "settings.json")

    assert manager.get("ui", "language") == "zh_CN"


def test_invalid_persisted_ui_language_falls_back_to_simplified_chinese(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"ui": {"language": "fr_FR"}}), encoding="utf-8")

    manager = ConfigManager(config_path=path)

    assert manager.get("ui", "language") == "zh_CN"


def test_saved_english_ui_language_persists_as_a_supported_locale(tmp_path):
    path = tmp_path / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("ui", "language", "en_US")
    manager.save()

    saved = json.loads(path.read_text(encoding="utf-8"))
    reloaded = ConfigManager(config_path=path)

    assert saved["ui"]["language"] == "en_US"
    assert reloaded.get("ui", "language") == "en_US"


def test_dynamic_template_keeps_unicode_name_separate_from_stable_id_after_save_and_reload(tmp_path):
    path = tmp_path / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("dynamic_gestures", None, {
        "enabled": True,
        "templates": [{
            "template_id": "swipe-up",
            "name": "向上滑动",
            "action": "scroll_up",
            "hotkey": "",
            "samples": [[[0.0] * 63, [0.1] * 63]],
            "threshold": 0.18,
            "cooldown_seconds": 0.75,
            "min_motion_energy": 0.05,
        }],
    })
    manager.save()

    reloaded = ConfigManager(config_path=path)
    template = reloaded.get("dynamic_gestures", "templates")[0]

    assert template["template_id"] == "swipe-up"
    assert template["name"] == "向上滑动"


def test_invalid_ui_language_set_directly_is_normalized_before_save(tmp_path):
    path = tmp_path / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("ui", "language", "fr_FR")
    manager.save()

    reloaded = ConfigManager(config_path=path)

    assert reloaded.get("ui", "language") == "zh_CN"


def test_legacy_optional_pointer_lifecycle_binding_is_pruned_on_save(tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set_gesture("thumb_up", "enabled", True)
    config.set_gesture("thumb_up", "action", "drag")
    config.set_gesture("thumb_up", "hotkey", "cmd+d")
    config.save()

    gesture = config.get_gesture("thumb_up")
    assert gesture["enabled"] is False
    assert gesture["action"] == "none"
    assert gesture["hotkey"] == ""


def test_persisted_custom_hotkeys_are_canonicalized_and_unsupported_bindings_are_pruned(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "control_session": {"mode": "hold_shortcut", "hold_shortcut": "command + shift + P"},
        "gestures": {
            "peace": {"action": "custom_hotkey", "hotkey": "cmd+bogus+p"},
            "thumb_up": {"action": "custom_hotkey", "hotkey": "ctrl+option+p"},
            "thumb_down": {"action": "volume_down", "hotkey": "cmd+p"},
        },
        "gesture_combos": [
            {"id": "invalid", "gesture1": "peace", "gesture2": "thumb_up", "action": "custom_hotkey", "hotkey": "cmd+bogus+p"},
            {"id": "missing", "gesture1": "peace", "gesture2": "thumb_down", "action": "custom_hotkey", "hotkey": ""},
            {"id": "canonical", "gesture1": "peace", "gesture2": "thumb_down", "action": "custom_hotkey", "hotkey": "command + shift + p"},
        ],
    }), encoding="utf-8")

    manager = ConfigManager(config_path=path)
    manager.save()

    assert manager.get("control_session", "hold_shortcut") == "cmd+shift+p"
    assert manager.get_gesture("peace")["hotkey"] == ""
    assert manager.get_gesture("thumb_up")["hotkey"] == "ctrl+alt+p"
    assert manager.get_gesture("thumb_down")["enabled"] is False
    assert manager.get_gesture("thumb_down")["action"] == "none"
    assert manager.get_gesture("thumb_down")["hotkey"] == ""
    assert manager.get("gesture_combos") == [
        {"id": "canonical", "gesture1": "peace", "gesture2": "thumb_down", "action": "custom_hotkey", "hotkey": "cmd+shift+p"}
    ]


def test_core_pointer_gestures_are_removed_from_legacy_generic_combinations_on_load_and_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "gesture_combos": [
            {"id": "legacy-click", "gesture1": "point", "gesture2": "pinch", "action": "left_click"},
            {"id": "safe", "gesture1": "peace", "gesture2": "thumb_up", "action": "scroll_up"},
        ]
    }), encoding="utf-8")

    manager = ConfigManager(config_path=path)
    manager.save()
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert manager.get("gesture_combos") == [
        {"id": "safe", "gesture1": "peace", "gesture2": "thumb_up", "action": "scroll_up", "hotkey": ""}
    ]
    assert saved["gesture_combos"] == manager.get("gesture_combos")

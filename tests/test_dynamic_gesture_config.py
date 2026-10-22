import json

from utils.config_manager import ConfigManager


def _safe_template(action="scroll_up", hotkey=""):
    return {
        "template_id": "swipe-up",
        "name": "Swipe up",
        "action": action,
        "hotkey": hotkey,
        "samples": [[[0.0] * 63, [0.1] * 63]],
        "threshold": 0.18,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
        "rgb_frames": ["must never persist"],
    }


def test_dynamic_gesture_config_loads_only_safe_supported_templates_and_saves_no_rgb(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "dynamic_gestures": {
            "enabled": False,
            "defaults": {"threshold": 0.2, "unknown": "discard"},
            "templates": [
                _safe_template(),
                _safe_template(action="forward"),
                _safe_template(action="custom_hotkey", hotkey=""),
                _safe_template(action="custom_hotkey", hotkey="ctrl+shift+p"),
                _safe_template(action="custom_hotkey", hotkey="cmd+bogus+p"),
                _safe_template(action="custom_hotkey", hotkey="command + shift + P"),
                {"template_id": "unsafe/id", "name": "Bad", "action": "scroll_down", "samples": []},
            ],
        }
    }), encoding="utf-8")

    manager = ConfigManager(config_path=path)
    dynamic = manager.get("dynamic_gestures")

    assert dynamic["enabled"] is False
    assert set(dynamic) == {"enabled", "defaults", "templates"}
    assert dynamic["defaults"] == {
        "threshold": 0.2,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
        "neutral_rearm_frames": 3,
        "end_neutral_frames": 2,
        "max_recording_frames": 180,
        "max_duration_seconds": 3.0,
    }
    assert [(item["action"], item["hotkey"]) for item in dynamic["templates"]] == [
        ("scroll_up", ""),
        ("custom_hotkey", "ctrl+shift+p"),
        ("custom_hotkey", "cmd+shift+p"),
    ]

    manager.save()
    saved = json.loads(path.read_text(encoding="utf-8"))["dynamic_gestures"]
    assert saved == dynamic
    assert "rgb_frames" not in json.dumps(saved)


def test_dynamic_gesture_config_normalizes_programmatic_unsafe_values_on_save(tmp_path):
    path = tmp_path / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("dynamic_gestures", None, {
        "enabled": "not-a-bool",
        "defaults": {"threshold": float("inf")},
        "templates": [_safe_template(action="volume_up")],
    })

    manager.save()

    saved = json.loads(path.read_text(encoding="utf-8"))["dynamic_gestures"]
    assert saved["enabled"] is False
    assert saved["templates"] == []
    assert saved["defaults"] == {
        "threshold": 0.18,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
        "neutral_rearm_frames": 3,
        "end_neutral_frames": 2,
        "max_recording_frames": 180,
        "max_duration_seconds": 3.0,
    }


def test_dynamic_shortcuts_default_to_disabled_until_explicitly_enabled(tmp_path):
    manager = ConfigManager(config_path=tmp_path / "settings.json")

    assert manager.get("dynamic_gestures", "enabled") is False

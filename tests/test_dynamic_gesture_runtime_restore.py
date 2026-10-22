import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui import main_window
from utils.config_manager import ConfigManager


def _record():
    return {
        "template_id": "saved-swipe",
        "name": "Saved swipe",
        "action": "scroll_up",
        "hotkey": "",
        "samples": [[[0.0] * 63, [0.1] * 63]],
        "threshold": 0.18,
        "cooldown_seconds": 0.75,
        "min_motion_energy": 0.05,
    }


def test_main_window_restores_only_saved_dynamic_shortcuts(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("dynamic_gestures", None, {
        "enabled": True,
        "defaults": {
            "neutral_rearm_frames": 2,
            "end_neutral_frames": 3,
            "max_recording_frames": 12,
            "max_duration_seconds": 1.5,
        },
        "templates": [_record()],
    })
    config.save()
    persisted = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: persisted)

    window = main_window.MainWindow()
    try:
        assert [template.template_id for template in window.dynamic_templates] == ["saved-swipe"]
        assert window.dynamic_runtime_matcher is not None
        assert window.dynamic_intent_lifecycle.neutral_rearm_frames == 2
        assert window.dynamic_intent_lifecycle.end_neutral_frames == 3
        assert window.dynamic_intent_lifecycle.max_recording_frames == 12
        assert window.dynamic_intent_lifecycle.max_duration_seconds == 1.5
    finally:
        window.close()

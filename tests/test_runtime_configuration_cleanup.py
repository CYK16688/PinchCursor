import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.gesture_classifier import GestureClassifier
from gui import main_window
from utils.config_manager import ConfigManager


def test_legacy_ambiguous_call_gesture_is_not_advertised_or_configurable(tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")

    assert "call" not in GestureClassifier().gestures
    assert "call" not in config.get("gestures")


def test_fresh_config_omits_inert_mouse_speed_and_legacy_action_mode_toggle(tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")

    assert "mouse_speed" not in config.get("global_sensitivity")
    assert "enabled" not in config.get("action_mode")


def test_legacy_call_yolo_and_inert_mouse_speed_settings_are_pruned_on_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"gestures":{"call":{"enabled":true,"action":"save"}},'
        '"detection":{"detector_type":"yolo"},'
        '"global_sensitivity":{"mouse_speed":2.0}}',
        encoding="utf-8",
    )

    config = ConfigManager(config_path=path)
    config.save()

    assert "call" not in config.get("gestures")
    assert config.get("detection", "detector_type") == "mediapipe"
    assert "mouse_speed" not in config.get("global_sensitivity")


def test_main_window_applies_persisted_zone_rules_to_live_pointer_machine(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("zone_rules", None, [
        {"x": 10, "y": 20, "w": 100, "h": 80, "allowed": ["click"]},
    ])
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    window = main_window.MainWindow()
    try:
        assert window.action_machine.zone_rules == [
            {"rect": (10, 20, 100, 80), "allowed": {"click"}},
        ]
    finally:
        window.close()
        app.processEvents()


def test_runtime_configuration_refreshes_live_pointer_and_detector_settings(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("global_sensitivity", "smoothing", 0.012)
    config.set("detection", "detector_type", "mediapipe")
    config.set("detection", "confidence", 0.82)
    config.set("detection", "tracking_confidence", 0.61)
    config.set("action_mode", "dwell_threshold", 0.42)
    config.set("action_mode", "move_threshold", 13)
    config.set("action_mode", "drag_threshold", 0.55)
    config.set("zone_rules", None, [
        {"x": 0, "y": 0, "w": 50, "h": 50, "allowed": ["drag"]},
    ])
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)

    window = main_window.MainWindow()
    try:
        window._refresh_runtime_configuration()

        # The smoothing preference drives ``mincutoff`` (resting jitter), not
        # ``beta`` (high-speed follow). It used to be wired to beta, which made
        # the dial do nothing measurable to a still hand.
        from utils.smoothing import CURSOR_SMOOTHING_BETA, mincutoff_for_smoothing

        assert window.smoother.filter_x.beta == CURSOR_SMOOTHING_BETA
        assert window.smoother.filter_x.mincutoff == pytest.approx(
            mincutoff_for_smoothing(0.012, default=window.preset.smoothing_mincutoff)
        )
        assert window.detector_type == "mediapipe"
        assert window.detection_confidence == 0.82
        assert window.tracking_confidence == 0.61
        assert window.action_machine.dwell_threshold == 0.42
        assert window.action_machine.move_threshold == 13
        assert window.action_machine.drag_threshold == 0.55
        assert window.action_machine.zone_rules == [
            {"rect": (0, 0, 50, 50), "allowed": {"drag"}},
        ]
    finally:
        window.close()
        app.processEvents()

"""The two resource profiles, and that switching one changes real numbers."""

import pathlib
import tempfile

import pytest
from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionStateMachine
from core.performance import DEFAULT_MODE, MODES, PERFORMANCE, STANDARD, preset_for
from gui.main_window import MainWindow
from utils.config_manager import ConfigManager


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_unknown_modes_fall_back_to_standard():
    assert preset_for(None) is STANDARD
    assert preset_for("turbo") is STANDARD
    assert DEFAULT_MODE == "standard"
    assert set(MODES) == {"standard", "performance"}


def test_performance_profile_is_strictly_more_demanding():
    assert PERFORMANCE.camera_width > STANDARD.camera_width
    assert PERFORMANCE.camera_height > STANDARD.camera_height
    assert PERFORMANCE.preview_fps > STANDARD.preview_fps
    assert PERFORMANCE.delegate == "gpu"
    assert PERFORMANCE.color_format == "rgba"
    # Lower cutoff = steadier cursor; that is the trade the profile makes.
    assert PERFORMANCE.smoothing_mincutoff < STANDARD.smoothing_mincutoff


def test_standard_profile_keeps_cpu_and_rgb():
    assert STANDARD.delegate == "cpu"
    assert STANDARD.color_format == "rgb"
    assert STANDARD.camera_width == 640


def test_window_applies_the_profile(app, tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("performance", "mode", "performance")
    window = _stub_window(config)

    MainWindow._refresh_runtime_configuration(window)

    assert window.preset.is_performance
    assert window.PREVIEW_FPS == PERFORMANCE.preview_fps
    assert window.detection_confidence == PERFORMANCE.detection_confidence
    assert window.tracking_confidence == PERFORMANCE.tracking_confidence


def test_switching_back_restores_the_configured_confidences(app, tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("detection", "confidence", 0.85)
    config.set("detection", "tracking_confidence", 0.4)
    config.set("performance", "mode", "standard")
    window = _stub_window(config)

    MainWindow._refresh_runtime_configuration(window)

    assert window.PREVIEW_FPS == STANDARD.preview_fps
    assert window.detection_confidence == 0.85
    assert window.tracking_confidence == 0.4


def _stub_window(config):
    """Just enough window for the runtime refresh, without building the UI."""
    from types import SimpleNamespace

    window = MainWindow.__new__(MainWindow)
    window.config = config
    window.classifier = _FakeClassifier()
    window.action_machine = ActionStateMachine()
    window.telemetry = None
    window.platform_services = SimpleNamespace(context_provider=None)
    return window


class _FakeClassifier:
    pinch_enter_ratio = 0.29
    pinch_exit_ratio = 0.42
    pinch_threshold = 35
    hold_threshold = 0.3
    confirm_threshold = 3
    min_switch_interval = 0.15
    exit_threshold = 4
    cooldown_time = 0.2

    def set_pinch_calibration(self, enter, exit):
        pass

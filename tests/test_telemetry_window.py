"""Window wiring for telemetry: opt-in, and it never touches control flow."""

import pathlib
import tempfile

import pytest
from PySide6.QtWidgets import QApplication

from core.telemetry import TelemetryStore
from gui.main_window import MainWindow
from platform_services.contracts import UIContext
from utils.config_manager import ConfigManager


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_actions_are_recorded_with_context_and_outcome(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window.telemetry = TelemetryStore(tmp_path / "t.sqlite3", enabled=True)

    MainWindow._record_telemetry_action(
        window,
        action="left_click",
        executed=True,
        gesture="pinch",
        context=UIContext(category="clickable", native_role="AXButton"),
        x=120,
        y=240,
        latency_ms=7.5,
    )

    row = window.telemetry.recent(1)[0]
    assert row["action"] == "left_click"
    assert row["category"] == "clickable"
    assert row["role"] == "AXButton"
    assert row["executed"] == 1
    assert row["x"] == 120


def test_a_missing_context_is_recorded_as_empty_not_dropped(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window.telemetry = TelemetryStore(tmp_path / "t.sqlite3", enabled=True)

    MainWindow._record_telemetry_action(
        window,
        action="scroll_down",
        executed=False,
        gesture="thumb_down",
        context=None,
        x=5,
        y=6,
        latency_ms=1.0,
    )

    row = window.telemetry.recent(1)[0]
    assert row["category"] == ""
    assert row["executed"] == 0


def test_recording_is_inert_when_telemetry_is_off(tmp_path):
    window = MainWindow.__new__(MainWindow)
    window.telemetry = TelemetryStore(tmp_path / "t.sqlite3", enabled=False)

    MainWindow._record_telemetry_action(
        window, action="left_click", executed=True, gesture="pinch", context=None,
        x=1, y=2, latency_ms=1.0,
    )

    assert window.telemetry.summary()["total"] == 0
    assert not (tmp_path / "t.sqlite3").exists()


def test_refresh_opens_the_store_only_when_configured(app, tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    window = MainWindow.__new__(MainWindow)
    window.config = config
    window.telemetry = None

    MainWindow._refresh_telemetry(window)
    assert window.telemetry.enabled is False

    config.set("telemetry", "enabled", True)
    MainWindow._refresh_telemetry(window)

    assert window.telemetry.enabled is True
    assert pathlib.Path(window.telemetry.path) == tmp_path / "telemetry.sqlite3"


def test_refresh_reuses_the_same_store_when_only_the_flag_changes(app, tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    window = MainWindow.__new__(MainWindow)
    window.config = config
    window.telemetry = None
    MainWindow._refresh_telemetry(window)
    first = window.telemetry

    config.set("telemetry", "enabled", True)
    MainWindow._refresh_telemetry(window)

    assert window.telemetry is first

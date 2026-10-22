"""Startup wiring for the adaptation pass: evidence in, bounded step out."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from utils.config_manager import ConfigManager


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeStore:
    """Just the surface `_apply_adaptive_tuning` is allowed to touch."""

    def __init__(self, summary, enabled=True):
        self._summary = summary
        self.enabled = enabled
        self.recorded = []

    def summary(self):
        if isinstance(self._summary, Exception):
            raise self._summary
        return self._summary

    def record(self, kind, **fields):
        self.recorded.append((kind, fields))


def _window(tmp_path, summary, *, enabled=True, assist=None):
    window = MainWindow.__new__(MainWindow)
    window.config = ConfigManager(config_path=str(tmp_path / "settings.json"))
    if assist:
        window.config.config["pointer_assist"].update(assist)
    window.telemetry = _FakeStore(summary, enabled=enabled)
    window.action_machine = SimpleNamespace(snap_provider=None)
    return window


def _click_summary(clicks, misses, snaps=0, mean=None):
    return {
        "total": clicks + snaps,
        "actions": {"left_click": clicks},
        "click_misses": misses,
        "snaps": snaps,
        "mean_snap_distance": mean,
        "executed_rate": 1.0,
        "mean_latency_ms": 5.0,
    }


def test_learned_values_win_over_the_configured_ones():
    values = MainWindow._effective_assist_values(
        {"max_snap_distance": 40.0, "min_confidence": 0.55,
         "learned": {"max_snap_distance": 31.0, "min_confidence": 0.6,
                     "base_max_snap_distance": 40.0, "base_min_confidence": 0.55}}
    )

    assert values == (31.0, 0.6)


def test_a_manual_config_change_discards_the_stale_adaptation():
    values = MainWindow._effective_assist_values(
        {"max_snap_distance": 50.0, "min_confidence": 0.55,
         "learned": {"max_snap_distance": 31.0, "min_confidence": 0.6,
                     "base_max_snap_distance": 40.0, "base_min_confidence": 0.55}}
    )

    assert values == (50.0, 0.55)


def test_malformed_learned_values_fall_back_to_the_config():
    values = MainWindow._effective_assist_values(
        {"max_snap_distance": 40.0, "min_confidence": 0.55,
         "learned": {"max_snap_distance": "oops", "min_confidence": None}}
    )

    assert values == (40.0, 0.55)


def test_a_high_miss_rate_is_written_to_config_and_applied(tmp_path):
    window = _window(
        tmp_path,
        _click_summary(50, 12, snaps=25, mean=35.0),
        assist={"max_snap_distance": 40.0, "min_confidence": 0.55},
    )

    tuning = window._apply_adaptive_tuning()

    assert tuning is not None and tuning.changed is True
    learned = window.config.get("pointer_assist")["learned"]
    assert learned["max_snap_distance"] == pytest.approx(34.0)
    assert learned["min_confidence"] == pytest.approx(0.58)
    assert learned["clicks"] == 50
    # the model the app actually uses was rebuilt from the learned values
    assert window.target_model.max_snap_distance == pytest.approx(34.0)
    assert window.target_model.min_confidence == pytest.approx(0.58)
    # and the decision was persisted, not just held in memory
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["pointer_assist"]["learned"]["reason"] == "over_reach"


def test_a_decided_pass_is_recorded_for_the_diagnostics_page(tmp_path):
    window = _window(tmp_path, _click_summary(50, 12, snaps=25, mean=35.0),
                     assist={"max_snap_distance": 40.0})

    window._apply_adaptive_tuning()

    kinds = [kind for kind, _ in window.telemetry.recorded]
    assert "tune" in kinds
    fields = window.telemetry.recorded[-1][1]
    assert fields["action"] == "over_reach"


def test_disabled_telemetry_never_adapts(tmp_path):
    window = _window(tmp_path, _click_summary(50, 12, snaps=25, mean=35.0), enabled=False)

    assert window._apply_adaptive_tuning() is None
    assert window.config.get("pointer_assist")["learned"] == {}


def test_thin_evidence_changes_nothing_and_records_nothing(tmp_path):
    window = _window(tmp_path, _click_summary(9, 5))

    tuning = window._apply_adaptive_tuning()

    assert tuning is not None and tuning.changed is False
    assert window.config.get("pointer_assist")["learned"] == {}
    assert window.telemetry.recorded == []


def test_the_same_evidence_is_never_applied_twice(tmp_path):
    """A cumulative summary must not ratchet at every launch."""
    window = _window(tmp_path, _click_summary(50, 12, snaps=25, mean=35.0),
                     assist={"max_snap_distance": 40.0, "min_confidence": 0.55})

    first = window._apply_adaptive_tuning()
    second = window._apply_adaptive_tuning()

    assert first.changed is True
    assert second is None
    assert window.config.get("pointer_assist")["learned"]["max_snap_distance"] == pytest.approx(34.0)


def test_more_clicks_make_the_tuner_act_again(tmp_path):
    window = _window(tmp_path, _click_summary(50, 12, snaps=25, mean=35.0),
                     assist={"max_snap_distance": 40.0, "min_confidence": 0.55})
    window._apply_adaptive_tuning()

    window.telemetry = _FakeStore(_click_summary(80, 14, snaps=40, mean=30.0))
    third = window._apply_adaptive_tuning()

    assert third is not None
    assert third.clicks == 80


def test_a_real_store_summary_drives_the_same_decision(tmp_path):
    """The mapping from stored events to the tuner's inputs is part of the deal."""
    from core.telemetry import TelemetryStore

    store = TelemetryStore(str(tmp_path / "t.sqlite3"), enabled=True)
    stamp = 1000.0
    # 30 isolated clicks: far enough apart in time to never look like a redo.
    for index in range(30):
        store.record("action", timestamp=stamp, action="left_click", executed=True,
                     x=100 + index * 40, y=200)
        stamp += 10.0
    # 10 pairs: a click, then a click 0.4 s later on a different control.
    for index in range(10):
        store.record("action", timestamp=stamp, action="left_click", executed=True, x=400, y=300)
        stamp += 0.4
        store.record("action", timestamp=stamp, action="left_click", executed=True, x=900, y=700)
        stamp += 10.0
    for index in range(10):
        store.record("assist", timestamp=stamp + index, snap_distance=35.0, confidence=0.7)

    window = MainWindow.__new__(MainWindow)
    window.config = ConfigManager(config_path=str(tmp_path / "settings.json"))
    window.config.config["pointer_assist"].update(
        {"max_snap_distance": 40.0, "min_confidence": 0.55}
    )
    window.telemetry = store
    window.action_machine = SimpleNamespace(snap_provider=None)

    tuning = window._apply_adaptive_tuning()

    assert tuning.clicks == 50
    assert tuning.misses == 10
    assert tuning.reason == "over_reach"
    assert window.config.get("pointer_assist")["learned"]["max_snap_distance"] == pytest.approx(34.0)
    store.close()


def test_the_settings_hint_describes_the_learned_values(tmp_path):
    from types import SimpleNamespace as NS

    from gui.settings_dialog import SettingsDialog

    config = ConfigManager(config_path=str(tmp_path / "settings.json"))
    config.config["pointer_assist"]["learned"] = {
        "max_snap_distance": 34.0,
        "min_confidence": 0.58,
        "clicks": 50,
        "misses": 12,
        "reason": "over_reach",
    }

    text = SettingsDialog._assist_learned_text(NS(config=config))

    assert "34" in text and "0.58" in text and "50" in text


def test_the_settings_hint_explains_the_empty_case(tmp_path):
    from types import SimpleNamespace as NS

    from gui.settings_dialog import SettingsDialog

    config = ConfigManager(config_path=str(tmp_path / "settings.json"))
    text = SettingsDialog._assist_learned_text(NS(config=config))

    assert "40" in text


def test_a_damaged_summary_is_not_a_startup_failure(tmp_path):
    window = _window(tmp_path, RuntimeError("database is locked"))

    assert window._apply_adaptive_tuning() is None


def test_tuning_respects_a_disabled_assist(tmp_path):
    window = _window(tmp_path, _click_summary(50, 12, snaps=25, mean=35.0),
                     assist={"enabled": False})

    assert window._apply_adaptive_tuning() is None

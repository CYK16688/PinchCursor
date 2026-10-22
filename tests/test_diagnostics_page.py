"""Diagnostics page: reads the local telemetry log without ever creating it."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.telemetry import TelemetryStore
from gui.diagnostics_page import DiagnosticsPage
from gui.i18n import tr


@pytest.fixture
def app():
    """One offscreen QApplication for every widget test in this module."""
    return QApplication.instance() or QApplication([])


def _seed(path, events):
    """Write events through the real store, then close so they are on disk."""
    store = TelemetryStore(path, enabled=True)
    for event in events:
        store.record(**event)
    store.close()


def test_missing_database_shows_empty_copy_and_is_not_created(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    page = DiagnosticsPage(str(path))
    try:
        assert page.empty_label.text() == tr("settings.advanced.diagnostics.empty")
        assert not page.empty_label.isHidden()
        assert not page.form.isRowVisible(1)
        assert not path.exists()
    finally:
        page.close()


def test_refresh_reports_click_repeat_click_and_snap_counts(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    now = time.time()
    # Pinning timestamps keeps the "quick redo" rule deterministic; they stay
    # near the present so the store's retention window does not drop them.
    _seed(
        path,
        [
            {
                "kind": "action",
                "action": "left_click",
                "executed": True,
                "x": 100,
                "y": 100,
                "timestamp": now,
            },
            {
                "kind": "action",
                "action": "left_click",
                "executed": True,
                "x": 160,
                "y": 100,
                "timestamp": now + 0.5,
            },
            {"kind": "action", "action": "right_click", "executed": False, "timestamp": now + 1.0},
            {"kind": "assist", "snap_distance": 12.0, "timestamp": now + 1.5},
            {"kind": "assist", "snap_distance": 4.0, "timestamp": now + 2.0},
        ],
    )
    page = DiagnosticsPage(str(path))
    try:
        page.refresh_button.click()

        assert page.clicks_value.text() == "3"
        assert page.misses_value.text() == "1"
        assert page.snaps_value.text() == "2"
        assert page.empty_label.isHidden()
        assert page.form.isRowVisible(1)
    finally:
        page.close()


def test_success_rate_and_latency_are_formatted_with_one_decimal(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    _seed(
        path,
        [
            {"kind": "action", "action": "left_click", "executed": True, "latency_ms": 10.0},
            {"kind": "action", "action": "left_click", "executed": False, "latency_ms": 15.0},
        ],
    )
    page = DiagnosticsPage(str(path))
    try:
        assert page.executed_value.text() == "50.0%"
        assert page.latency_value.text() == "12.5 ms"
    finally:
        page.close()


def test_data_size_is_reported_in_kilobytes(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    _seed(
        path,
        [
            {"kind": "action", "action": "left_click", "executed": True},
            {"kind": "action", "action": "left_click", "executed": True},
        ],
    )
    page = DiagnosticsPage(str(path))
    try:
        assert page.size_value.text().endswith(" KB")
        assert page.size_value.text() != "—"
    finally:
        page.close()


def test_missing_rates_render_as_a_dash(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    # Assist-only rows produce no attempted action and no latency sample, which
    # is the case the store reports as None rather than zero.
    _seed(path, [{"kind": "assist", "snap_distance": 3.0}])

    page = DiagnosticsPage(str(path))
    try:
        assert page.snaps_value.text() == "1"
        assert page.executed_value.text() == "—"
        assert page.latency_value.text() == "—"
    finally:
        page.close()


def test_corrupt_database_degrades_to_empty_instead_of_raising(tmp_path, app):
    path = tmp_path / "telemetry.sqlite3"
    garbage = b"this is not a sqlite database" * 64
    path.write_bytes(garbage)

    page = DiagnosticsPage(str(path))
    try:
        page.refresh()
        assert page.empty_label.text() == tr("settings.advanced.diagnostics.empty")
        assert not page.empty_label.isHidden()
        assert not page.form.isRowVisible(1)
        # Opening a damaged log must not replace it with a fresh empty one.
        assert path.read_bytes() == garbage
    finally:
        page.close()

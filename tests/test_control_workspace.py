"""Integrated console checks with synthetic observations and unavailable devices."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton

from core.action_state_machine import ActionState
from gui import main_window
from gui.i18n import tr
from platform_services.contracts import AuthorizationState
from tests.test_gesture_reference_panel import _window, app
from tests.test_interaction_feedback import outcome, snapshot
from utils.config_manager import ConfigManager


@pytest.fixture
def workspace(app, monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    window.hud_timer.stop()
    yield window
    window.is_running = False
    window.close()


def test_observations_and_actual_dispatch_results_reach_the_visible_panel(workspace, monkeypatch):
    window = workspace
    clock = [10.0]
    monkeypatch.setattr(main_window.time, "monotonic", lambda: clock[0])
    window.is_running = True

    def present(frame, outcomes=None):
        clock[0] += 0.1
        window._present_control_snapshot(frame, outcomes=outcomes)
        return window.interaction_panel.title.text()

    assert present(snapshot(pinch_phase="candidate")) == tr("interaction.candidate")
    assert present(snapshot(pinch_phase="confirmed")) == tr("interaction.confirmed")
    assert present(snapshot(pinch_phase="released")) == tr("interaction.released")
    assert present(snapshot(), outcomes=(outcome(),)) == tr("interaction.clicked")
    # Coalesced dispatch evidence can belong to an older frame than the preview.
    assert window.last_action_value.text() == window._action_label("left_click")
    assert present(snapshot()) == tr("interaction.clicked")
    assert present(snapshot(hand_present=False)) == tr("interaction.hand_lost")
    assert present(snapshot()) == tr("interaction.aiming")

    failed = outcome(executed=False, error_code="unsupported_action")
    assert present(snapshot(pinch_phase="released"), outcomes=(failed,)) == tr("interaction.not_executed")
    assert present(snapshot()) == tr("interaction.not_executed")
    assert present(snapshot(pointer_state=ActionState.DRAGGING, pinch_phase="confirmed")) == tr("interaction.dragging")
    assert window.interaction_panel.hint.text() == tr("interaction.release_to_drop")
    assert present(snapshot()) == tr("interaction.aiming")


def _rect_in(widget, ancestor):
    return widget.rect().translated(widget.mapTo(ancestor, QPoint(0, 0)))


@pytest.mark.parametrize("size", [(1000, 660), (1200, 760)])
@pytest.mark.parametrize("locale", ["zh_CN", "en_US"])
@pytest.mark.parametrize("blocked", [False, True], ids=["ready", "permission-needed"])
def test_console_fits_supported_viewports(app, monkeypatch, tmp_path, size, locale, blocked):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("ui", "language", locale)
    window = _window(monkeypatch, tmp_path, config=config)
    window.hud_timer.stop()
    try:
        if blocked:
            provider = window.platform_services.permission_provider
            permissions = replace(provider.snapshot(), accessibility=AuthorizationState.DENIED)
            monkeypatch.setattr(provider, "snapshot", lambda: permissions)
            window._refresh_permission_status()
            window._refresh_precision_console()
        window.resize(*size)
        window.show()
        app.processEvents()
        assert window.size() == QSize(*size), "Layout enlarged the requested viewport"
        central = window.centralWidget()
        controls = [window.primary_control_button, window.settings_btn,
                    window.gesture_reference, *window.summary_rows.values()]
        for widget in controls:
            assert widget.isVisible()
            assert central.rect().contains(_rect_in(widget, central)), widget.objectName()
            assert widget.width() > 0 and widget.height() > 0
        for index, widget in enumerate(controls):
            for other in controls[index + 1:]:
                assert not _rect_in(widget, central).intersects(_rect_in(other, central))
        cards = [window.session_card, window.setup_card, window.gesture_reference,
                 window.findChild(type(window.session_card), "previewFrame")]
        for index, card in enumerate(cards):
            for other in cards[index + 1:]:
                assert not _rect_in(card, central).intersects(_rect_in(other, central))
        for row in window.summary_rows.values():
            assert isinstance(row, QPushButton)
            assert row.accessibleName()
            for label in row.findChildren(QLabel):
                assert row.rect().contains(_rect_in(label, row)), (locale, label.text())
        assert window.permission_row.isVisible() is blocked
        for tile in window.gesture_reference.rows.values():
            if tile.isVisible():
                assert window.gesture_reference.rect().contains(_rect_in(tile, window.gesture_reference))
    finally:
        window.close()


def test_escape_stops_active_control_and_never_starts_it(workspace, app, monkeypatch):
    window = workspace
    calls = []

    def toggle():
        calls.append(window.is_running)
        window.is_running = not window.is_running

    monkeypatch.setattr(window, "toggle_running", toggle)
    window.show()
    window.activateWindow()
    window.raise_()
    window.primary_control_button.setFocus()
    app.processEvents()
    assert window.isActiveWindow()
    window.is_running = True
    QTest.keyClick(window, Qt.Key_Escape)
    assert calls == [True]
    assert not window.is_running
    QTest.keyClick(window, Qt.Key_Escape)
    assert calls == [True]


def test_settings_entries_have_names_and_open_the_expected_sections(workspace, monkeypatch):
    window = workspace
    opened = []
    monkeypatch.setattr(window, "open_settings", lambda section=None: opened.append(section))
    assert window.settings_btn.accessibleName() == tr("main.settings")
    assert window.settings_btn.shortcut() == QKeySequence(QKeySequence.StandardKey.Preferences)
    window.settings_btn.click()
    for row in window.summary_rows.values():
        assert row.accessibleName()
        row.click()
    window.gesture_reference.configure.click()
    assert opened == [None, "pointer", "activation", "camera", "gestures"]


def test_candidate_preview_keeps_pointer_hud_until_confirmed_target(workspace, monkeypatch):
    from types import SimpleNamespace
    import numpy as np
    from gui.hud_state import HudState

    window = workspace
    window.is_running = True
    markers = []
    monkeypatch.setattr(window, '_draw_aiming_indicator',
                        lambda frame, pos: markers.append(pos) or frame)
    preview = SimpleNamespace(frame=np.zeros((480, 640, 3), dtype=np.uint8), landmarks=[])
    candidate = snapshot(pinch_phase='candidate', pointer_state=ActionState.LOCKING,
                         locked_position=None, preview_locked_position=None)
    window._present_control_snapshot(candidate, preview)
    assert window.hud.current_state(candidate.timestamp) is HudState.POINTER
    assert window.interaction_panel.title.text() == tr('interaction.candidate')
    assert markers == []

    confirmed = replace(candidate, timestamp=1.1, pinch_phase='confirmed',
                        pointer_state=ActionState.CLICKING, locked_position=(100, 100),
                        preview_locked_position=(120, 80))
    window._present_control_snapshot(confirmed, preview)
    assert window.hud.current_state(confirmed.timestamp) is HudState.LOCKING
    assert markers == [(120, 80)]

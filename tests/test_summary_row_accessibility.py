"""The console must be operable without a mouse.

macOS expects ⌘, to open preferences and Return to trigger the default action.
Clickable summary rows had ``focusPolicy`` 0 and no key handling, so the only
entry points into Settings besides the gear were invisible to keyboard and
VoiceOver users.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QAccessible, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from gui.summary_row import SummaryRow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _key(widget, key):
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))


def _mouse(widget, event_type, x, y):
    local = QPointF(x, y)
    return QMouseEvent(
        event_type, local, local, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )


def test_a_summary_row_can_take_keyboard_focus(app):
    row = SummaryRow()
    assert row.focusPolicy() != Qt.NoFocus


def test_summary_exposes_a_native_accessible_button_and_press_action(app):
    row = SummaryRow()
    row.setAccessibleName("Pointer & click")
    interface = QAccessible.queryAccessibleInterface(row)
    assert interface.role() == QAccessible.Role.Button
    assert interface.text(QAccessible.Text.Name) == "Pointer & click"
    action = interface.actionInterface()
    assert "Press" in action.actionNames() or "press" in action.actionNames()


@pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter])
def test_a_summary_row_activates_from_the_keyboard(app, key):
    row = SummaryRow()
    fired = []
    row.clicked.connect(lambda: fired.append(True))

    _key(row, key)

    assert fired == [True]


def test_a_summary_row_ignores_unrelated_keys(app):
    row = SummaryRow()
    fired = []
    row.clicked.connect(lambda: fired.append(True))

    _key(row, Qt.Key_A)

    assert fired == []


def test_a_drag_that_ends_over_the_row_does_not_fire(app):
    """A press started elsewhere must not open Settings on release."""
    row = SummaryRow()
    row.resize(200, 60)
    fired = []
    row.clicked.connect(lambda: fired.append(True))

    row.mousePressEvent(_mouse(row, QEvent.MouseButtonPress, 5000, 5000))
    row.mouseReleaseEvent(_mouse(row, QEvent.MouseButtonRelease, 10, 10))

    assert fired == []


def test_a_click_started_and_released_inside_fires(app):
    row = SummaryRow()
    row.resize(200, 60)
    fired = []
    row.clicked.connect(lambda: fired.append(True))

    row.mousePressEvent(_mouse(row, QEvent.MouseButtonPress, 10, 10))
    row.mouseReleaseEvent(_mouse(row, QEvent.MouseButtonRelease, 12, 12))

    assert fired == [True]

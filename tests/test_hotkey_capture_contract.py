"""The shortcut field must emit tokens the runtime can actually persist.

The capture field used to map the macOS system modifier to ``win``, which
``normalize_hotkey`` rejects. ``normalize_gesture_combos`` then failed closed and
deleted the entire combination on Save, so a user who recorded ⌘+P watched their
combo disappear with no message.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from gui.hotkey_input import HotkeyInput
from utils.config_manager import normalize_gesture_combos
from utils.hotkey_validation import normalize_hotkey


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _capture(modifiers, key):
    field = HotkeyInput()
    field.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, modifiers))
    return field.text()


def test_the_meta_modifier_captures_as_cmd_on_macos(app):
    text = _capture(Qt.MetaModifier, Qt.Key_P)
    assert text == "cmd+p"
    # The token is not merely cosmetic: validation has to accept it.
    assert normalize_hotkey(text) == "cmd+p"


def test_a_captured_chord_survives_combination_normalization(app):
    hotkey = _capture(Qt.MetaModifier | Qt.ShiftModifier, Qt.Key_K)
    combo = [{
        "id": "c1",
        "gesture1": "peace",
        "gesture2": "fist",
        "action": "custom_hotkey",
        "hotkey": hotkey,
    }]
    assert normalize_gesture_combos(combo), "saving must not drop the user's combination"


def test_multi_character_key_labels_are_not_accepted(app):
    """Only a real terminal key may end a chord."""
    # A plain modifier is ignored entirely rather than captured as text.
    assert _capture(Qt.ControlModifier, Qt.Key_Control) == ""

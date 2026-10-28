"""Reusable read-only shortcut capture field.

The field emits the same canonical token vocabulary that
``utils/hotkey_validation.normalize_hotkey`` accepts, because a chord the user
can type here must be a chord the runtime can persist and inject. On macOS the
system modifier is ⌘ and the canonical token for it is ``cmd``; emitting ``win``
made every ⌘ combination invalid, and validation then discarded the entire combo
on save without telling the user.
"""

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLineEdit

# The Command key on macOS, the Windows key elsewhere. Both normalize to the
# same persisted token so a settings file stays meaningful across platforms.
_META_TOKEN = "cmd" if sys.platform == "darwin" else "win"


class HotkeyInput(QLineEdit):
    """Capture a canonical shortcut chord without accepting free-form text."""

    hotkeyChanged = Signal()

    MODIFIERS = {
        Qt.ControlModifier: "ctrl",
        Qt.AltModifier: "alt",
        Qt.ShiftModifier: "shift",
        Qt.MetaModifier: _META_TOKEN,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return

        parts = [name for modifier, name in self.MODIFIERS.items() if modifiers & modifier]
        key_text = self._get_key_text(key)
        if key_text:
            parts.append(key_text)
        if parts:
            self.setText("+".join(parts))
            self.hotkeyChanged.emit()

    @staticmethod
    def _get_key_text(key):
        special_keys = {
            Qt.Key_Space: "space",
            Qt.Key_Return: "enter",
            Qt.Key_Enter: "enter",
            Qt.Key_Tab: "tab",
            Qt.Key_Escape: "escape",
            Qt.Key_Backspace: "backspace",
            Qt.Key_Delete: "delete",
            Qt.Key_Insert: "insert",
            Qt.Key_Home: "home",
            Qt.Key_End: "end",
            Qt.Key_PageUp: "pageup",
            Qt.Key_PageDown: "pagedown",
            Qt.Key_Up: "up",
            Qt.Key_Down: "down",
            Qt.Key_Left: "left",
            Qt.Key_Right: "right",
        }
        if key in special_keys:
            return special_keys[key]
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            return f"f{key - Qt.Key_F1 + 1}"
        # A single character only: QKeySequence().toString() can return a
        # modifier-prefixed or multi-character label that is not a terminal key,
        # and a token like that fails validation later without an explanation.
        text = QKeySequence(key).toString().lower()
        return text if len(text) == 1 else None

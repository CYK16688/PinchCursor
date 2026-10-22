"""Reusable read-only shortcut capture field."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLineEdit


class HotkeyInput(QLineEdit):
    """Capture a canonical shortcut chord without accepting free-form text."""

    hotkeyChanged = Signal()

    MODIFIERS = {
        Qt.ControlModifier: "ctrl",
        Qt.AltModifier: "alt",
        Qt.ShiftModifier: "shift",
        Qt.MetaModifier: "win",
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
        return QKeySequence(key).toString().lower() or None

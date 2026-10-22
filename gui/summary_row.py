"""A settings summary that is itself the control that changes it.

The console used to end each summary row with a separate "更改" text button.
Three small links beside the one real action compete for attention, and the word
adds nothing the row does not already say. Making the row the target removes the
label and enlarges the hit area — which also suits a pointer driven by hand
tracking, where small targets cost disproportionately.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame


class SummaryRow(QFrame):
    """One fact about the current session, clickable to edit it in Settings."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("summaryRow")
        self.setCursor(Qt.PointingHandCursor)
        # Hover feedback needs the widget to receive enter/leave events.
        self.setAttribute(Qt.WA_Hover, True)

    def mouseReleaseEvent(self, event):
        """Act only on a release inside the row, like a real button."""
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

"""A settings summary that is itself the control that changes it.

The console used to end each summary row with a separate "更改" text button.
Three small links beside the one real action compete for attention, and the word
adds nothing the row does not already say. Making the row the target removes the
label and enlarges the hit area — which also suits a pointer driven by hand
tracking, where small targets cost disproportionately.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy


class SummaryRow(QPushButton):
    """One fact about the current session, clickable to edit it in Settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("summaryRow")
        self.setCursor(Qt.PointingHandCursor)
        # Hover feedback needs the widget to receive enter/leave events.
        self.setAttribute(Qt.WA_Hover, True)
        # These rows are the only way into Settings besides the gear, so they
        # have to be reachable without a mouse: tab to the row, Space/Return to
        # open it. A clickable widget that cannot take focus is invisible to
        # keyboard and VoiceOver users alike.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoDefault(False)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        size = super().sizeHint()
        return size.expandedTo(self.layout().totalSizeHint()) if self.layout() else size

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        return size.expandedTo(self.layout().totalMinimumSize()) if self.layout() else size

    def heightForWidth(self, width):
        layout = self.layout()
        if layout and layout.hasHeightForWidth():
            return max(self.minimumSizeHint().height(), layout.totalHeightForWidth(width))
        return self.sizeHint().height()

    def keyPressEvent(self, event):
        """Activate on Space or Return, the two keys a button answers to."""
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

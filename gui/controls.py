"""A switch for enabling a feature, and the rules for when to use which control.

The settings surface used one control — a checkbox — for three different jobs,
which is why configuring the app felt harder than it is:

* **Switch** (``ToggleSwitch``) — one feature, on or off, applied immediately to
  the whole feature: "Usage data", "Enable dynamic shortcuts". A switch reads as
  a state you flip, which is exactly what these are.
* **Checkbox** (``QCheckBox``) — one item chosen out of several in a set:
  "which gestures are allowed in a scrollable area". A list of these is a
  multi-select, and a column of switches there would look like a rack of
  individual features instead of one set.
* **Segmented control** (``SegmentedControl``) — a short, mutually exclusive
  choice where all options deserve to be visible: activation mode, pointer
  mapping. A combo box hides the alternatives behind a click, which makes the
  two-value choice look heavier than it is.

Keeping the rule in one place stops the surface from drifting back to
"everything is a checkbox".
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QPushButton, QSizePolicy, QWidget


class ToggleSwitch(QAbstractButton):
    """An animated on/off switch with a label, for enabling one feature."""

    TRACK_WIDTH = 40
    TRACK_HEIGHT = 22
    KNOB_MARGIN = 3

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setText(text)
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"knobOffset", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        """Reserve the track plus the painted label, which Qt cannot measure itself.

        The label is custom-painted, so QAbstractButton does not account for it
        and a long caption ("Record usage data on this machine") would be clipped
        to the track's own width.
        """
        metrics = self.fontMetrics()
        label_width = metrics.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(
            self.TRACK_WIDTH + (10 + label_width if label_width else 0),
            max(self.TRACK_HEIGHT, metrics.height()),
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:
        """Set state without animating, so restored settings do not flicker."""
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def get_knob_offset(self) -> float:
        return self._offset

    def set_knob_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    knobOffset = Property(float, get_knob_offset, set_knob_offset)

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        track = QRectF(0, (self.height() - self.TRACK_HEIGHT) / 2, self.TRACK_WIDTH, self.TRACK_HEIGHT)
        radius = self.TRACK_HEIGHT / 2
        path = QPainterPath()
        path.addRoundedRect(track, radius, radius)

        enabled = self.isEnabled()
        if not enabled:
            track_colour = QColor(255, 255, 255, 18)
        elif self.isChecked():
            track_colour = QColor("#3D63D8" if self.underMouse() else "#3457B5")
        else:
            track_colour = QColor(255, 255, 255, 34 if self.underMouse() else 26)
        painter.fillPath(path, track_colour)

        if self.hasFocus():
            painter.setPen(QColor("#5E8CFF"))
            painter.drawPath(path)

        knob_size = self.TRACK_HEIGHT - self.KNOB_MARGIN * 2
        travel = self.TRACK_WIDTH - knob_size - self.KNOB_MARGIN * 2
        knob_x = track.left() + self.KNOB_MARGIN + travel * self._offset
        knob = QRectF(knob_x, track.top() + self.KNOB_MARGIN, knob_size, knob_size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF") if enabled else QColor(255, 255, 255, 110))
        painter.drawEllipse(knob)

        if self.text():
            painter.setPen(QColor("#F5F7FA") if enabled else QColor("#8B93A1"))
            text_rect = self.rect().adjusted(self.TRACK_WIDTH + 10, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self.text())


class SegmentedControl(QWidget):
    """A short, mutually exclusive choice with every option visible."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setObjectName("segmentedControl")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def addItem(self, text: str, data=None) -> None:  # noqa: N802 - Qt naming
        button = QPushButton(text)
        button.setObjectName("segmentButton")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("data", data)
        button.clicked.connect(lambda _checked=False, index=len(self._buttons): self.setCurrentIndex(index))
        self._buttons.append(button)
        self._layout.addWidget(button)
        if len(self._buttons) == 1:
            button.setChecked(True)
        self._refresh_positions()

    def _refresh_positions(self) -> None:
        """Re-derive the corner radii after the list changed."""
        for index, button in enumerate(self._buttons):
            if len(self._buttons) == 1:
                position = "only"
            elif index == 0:
                position = "first"
            elif index == len(self._buttons) - 1:
                position = "last"
            else:
                position = "middle"
            button.setProperty("position", position)
            button.style().unpolish(button)
            button.style().polish(button)

    def count(self) -> int:
        return len(self._buttons)

    def currentIndex(self) -> int:  # noqa: N802 - Qt naming
        for index, button in enumerate(self._buttons):
            if button.isChecked():
                return index
        return -1

    def currentData(self):  # noqa: N802 - Qt naming
        index = self.currentIndex()
        return None if index < 0 else self._buttons[index].property("data")

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt naming
        if not 0 <= index < len(self._buttons):
            return
        for position, button in enumerate(self._buttons):
            button.setChecked(position == index)
        self.currentIndexChanged.emit(index)

    def setCurrentData(self, data) -> None:  # noqa: N802 - Qt naming
        for index, button in enumerate(self._buttons):
            if button.property("data") == data:
                self.setCurrentIndex(index)
                return

    def findData(self, data) -> int:  # noqa: N802 - Qt naming
        for index, button in enumerate(self._buttons):
            if button.property("data") == data:
                return index
        return -1

    def setItemText(self, index: int, text: str) -> None:  # noqa: N802 - Qt naming
        if 0 <= index < len(self._buttons):
            self._buttons[index].setText(text)

    def itemData(self, index: int):  # noqa: N802 - Qt naming
        return None if not 0 <= index < len(self._buttons) else self._buttons[index].property("data")

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt naming
        super().setEnabled(enabled)
        for button in self._buttons:
            button.setEnabled(enabled)

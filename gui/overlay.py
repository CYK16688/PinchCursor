"""Pointer-adjacent, non-intercepting desktop gesture feedback HUD."""

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QWidget

from gui.hud_state import HudState
from gui.i18n import tr


class GestureOverlay(QWidget):
    """Small pointer-adjacent status signal that never captures desktop input."""

    STATE_TRANSLATION_KEYS = {
        HudState.POINTER: "hud.pointer",
        HudState.LOCKING: "hud.locking",
        HudState.CLICKED: "hud.clicked",
        HudState.DRAGGING: "hud.dragging",
        HudState.SECONDARY_CLICK: "hud.secondary_click",
        HudState.VOLUME: "hud.volume",
        HudState.CONTEXTUAL: "hud.contextual",
        HudState.ERROR: "hud.error",
    }
    STATE_COLORS = {
        HudState.POINTER: QColor("#5E8CFF"),
        HudState.LOCKING: QColor("#F5B942"),
        HudState.CLICKED: QColor("#47D7A1"),
        HudState.DRAGGING: QColor("#5E8CFF"),
        HudState.SECONDARY_CLICK: QColor("#B98CFF"),
        HudState.VOLUME: QColor("#5E8CFF"),
        HudState.CONTEXTUAL: QColor("#5E8CFF"),
        HudState.ERROR: QColor("#FF6B6B"),
    }
    STATE_ICONS = {
        HudState.POINTER: "point",
        HudState.LOCKING: "pinch",
        HudState.CLICKED: "pinch",
        HudState.DRAGGING: "grab",
        HudState.SECONDARY_CLICK: "peace",
        HudState.VOLUME: "thumb_volume",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_state = HudState.HIDDEN
        self.message = ""
        self._anchor = None
        self._native_panel = None
        self.base_size = (168, 54)
        self.setFixedSize(*self.base_size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.label = QLabel(self)
        self.label.setObjectName("hudLabel")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFont(QFont("SF Pro Display", 11, QFont.DemiBold))
        self.label.setGeometry(10, 8, 148, 38)

    def set_feedback_preferences(self, opacity=0.92, scale=1.0):
        """Apply persisted visual preferences without changing input behavior."""
        self.setWindowOpacity(max(0.4, min(float(opacity), 1.0)))
        width = round(self.base_size[0] * max(0.8, min(float(scale), 1.6)))
        height = round(self.base_size[1] * max(0.8, min(float(scale), 1.6)))
        self.setFixedSize(width, height)
        horizontal_padding = max(8, round(width * 0.06))
        self.label.setGeometry(horizontal_padding, 8, width - horizontal_padding * 2, height - 16)

    def show_state(self, state, anchor, message=""):
        self.current_state = state
        self.message = message
        if state is HudState.HIDDEN or anchor is None:
            self.hide()
            return
        self._anchor = anchor
        self.label.setText(message or self.state_label(state))
        self._position_near(anchor)
        self.show()
        self._ensure_native_panel()
        if self._native_panel is not None:
            self._native_panel.raise_panel()
        else:
            self.raise_()
        self.update()

    def state_label(self, state):
        """Translate a stable HUD state without treating runtime text as a key."""
        try:
            state = HudState(state)
        except (TypeError, ValueError):
            return ""
        return tr(self.STATE_TRANSLATION_KEYS.get(state, "")) if state is not HudState.HIDDEN else ""

    def retranslate_ui(self):
        """Refresh default feedback copy while preserving explicit runtime messages."""
        if self.current_state is not HudState.HIDDEN and not self.message:
            self.label.setText(self.state_label(self.current_state))

    def hide_feedback(self):
        self.current_state = HudState.HIDDEN
        self.hide()

    def icon_name_for_state(self, state):
        """Return the stable outline-icon contract for a HUD state."""
        try:
            state = HudState(state)
        except ValueError:
            return ""
        return self.STATE_ICONS.get(state, "")

    def _position_near(self, anchor):
        screen = self.screen()
        geometry = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x = min(max(anchor[0] + 18, geometry.left()), geometry.right() - self.width() + 1)
        y = min(max(anchor[1] + 18, geometry.top()), geometry.bottom() - self.height() + 1)
        self.move(x, y)

    def enable_macos_global_panel(self, native):
        """Enable a native all-Spaces panel only when the macOS adapter is available."""
        from platform_services.macos.hud_panel import MacOSHudPanelController

        self._native_panel = MacOSHudPanelController(native)

    def _ensure_native_panel(self):
        if self._native_panel is not None and self._native_panel.panel is None:
            self._native_panel.attach(self)

    def paintEvent(self, event):
        if self.current_state is HudState.HIDDEN:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = self.STATE_COLORS.get(self.current_state, QColor("#5E8CFF"))
        body = QRect(4, 4, self.width() - 8, self.height() - 8)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.setBrush(QColor(18, 20, 25, 238))
        painter.drawRoundedRect(body, 17, 17)
        painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        self._draw_outline_icon(painter, self.icon_name_for_state(self.current_state))

    @staticmethod
    def _draw_outline_icon(painter, icon_name):
        """Render the fixed-grid outline vocabulary for core HUD hand states."""
        if icon_name == "point":
            path = QPainterPath()
            path.moveTo(16, 38); path.lineTo(16, 19); path.quadTo(16, 14, 20, 14)
            path.quadTo(24, 14, 24, 19); path.lineTo(24, 29); path.lineTo(29, 24)
            path.quadTo(33, 21, 36, 25); path.lineTo(39, 29); path.quadTo(42, 32, 39, 35)
            path.lineTo(31, 43); path.quadTo(27, 47, 21, 44); path.closeSubpath()
            painter.drawPath(path)
        elif icon_name in {"pinch", "grab"}:
            painter.drawEllipse(13, 16, 15, 15)
            painter.drawEllipse(28, 24, 12, 12)
            painter.drawLine(22, 29, 29, 29)
            if icon_name == "grab":
                painter.drawLine(17, 38, 37, 38)
                painter.drawLine(20, 42, 34, 42)
        elif icon_name == "peace":
            painter.drawLine(20, 40, 20, 17); painter.drawLine(20, 17, 15, 12)
            painter.drawLine(28, 40, 28, 17); painter.drawLine(28, 17, 33, 12)
            painter.drawArc(16, 31, 16, 14, 180 * 16, -180 * 16)
        elif icon_name == "thumb_volume":
            painter.drawLine(13, 27, 19, 27); painter.drawLine(19, 27, 25, 20)
            painter.drawLine(19, 27, 25, 34); painter.drawArc(23, 18, 15, 18, -45 * 16, 90 * 16)
        else:
            painter.drawEllipse(15, 18, 18, 18)

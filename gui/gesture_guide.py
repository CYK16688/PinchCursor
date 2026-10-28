"""Compact action-first reference, built from the actual gesture bindings."""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gui import icons
from gui.gesture_icons_svg import GestureIconsSVG
from gui.i18n import tr
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtCore import QRectF


class GestureGuide(QFrame):
    configure_requested = Signal()

    CORE = ("point", "pinch", "pinch_hold", "thumb_up", "thumb_down")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gestureReference")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.hint = QLabel()
        self.hint.setObjectName("gestureReferenceHint")
        self.more = QPushButton()
        self.more.setObjectName("quietButton")
        self.more.setCheckable(True)
        self.more.toggled.connect(self._toggle_extra)
        self.configure = QPushButton()
        self.configure.setObjectName("quietButton")
        self.configure.setIcon(icons.icon("gear", "#C6CBD5", 14))
        self.configure.setIconSize(QSize(14, 14))
        self.configure.clicked.connect(self.configure_requested)
        heading.addWidget(self.title)
        heading.addWidget(self.hint)
        heading.addStretch()
        heading.addWidget(self.more)
        heading.addWidget(self.configure)
        layout.addLayout(heading)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        layout.addLayout(self.grid)
        self.extra = QWidget()
        self.extra_grid = QGridLayout(self.extra)
        self.extra_grid.setContentsMargins(0, 0, 0, 0)
        self.extra_grid.setSpacing(8)
        self.extra.hide()
        layout.addWidget(self.extra)
        self.rows = {}

    def _toggle_extra(self, expanded):
        self.extra.setVisible(expanded)
        self.more.setAccessibleDescription(tr("main.guide.expanded" if expanded else "main.guide.collapsed"))

    def set_bindings(self, bindings, gesture_label, action_label):
        for grid in (self.grid, self.extra_grid):
            while grid.count():
                item = grid.takeAt(0)
                if item.widget() is not None:
                    item.widget().hide()
                    item.widget().deleteLater()
        self.rows = {}
        core_count = extra_count = 0
        for gesture, action in bindings:
            tile = QFrame()
            tile.setObjectName("gestureGuideTile")
            body = QVBoxLayout(tile)
            body.setContentsMargins(10, 10, 10, 10)
            body.setSpacing(5)
            top = QHBoxLayout()
            top.setSpacing(6)
            glyph = QLabel()
            glyph.setFixedSize(22, 22)
            renderer = GestureIconsSVG.get_renderer(gesture, "#AFC5FF")
            if renderer is not None:
                pixmap = QPixmap(44, 44)
                pixmap.setDevicePixelRatio(2)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter, QRectF(0, 0, 22, 22))
                painter.end()
                glyph.setPixmap(pixmap)
            core = gesture in self.CORE
            title = QLabel(tr(f"main.guide.{gesture}.action") if core else action_label(action))
            title.setObjectName("guideAction")
            title.setWordWrap(True)
            detail = QLabel(tr(f"main.guide.{gesture}.pose") if core else gesture_label(gesture))
            detail.setObjectName("guidePose")
            detail.setWordWrap(True)
            top.addWidget(glyph)
            top.addWidget(title, 1)
            body.addLayout(top)
            body.addWidget(detail)
            body.addStretch()
            tile.setAccessibleName(f"{title.text()} — {detail.text()}")
            tile.setToolTip(tr(f"main.guide.{gesture}.hint") if core else tile.accessibleName())
            if core:
                self.grid.addWidget(tile, 0, core_count)
                self.grid.setColumnStretch(core_count, 1)
                core_count += 1
            else:
                self.extra_grid.addWidget(tile, extra_count // 3, extra_count % 3)
                extra_count += 1
            self.rows[gesture] = tile
        self.title.setText(tr("main.gesture_reference"))
        self.hint.clear()
        self.hint.hide()
        self.more.setText(tr("main.guide.more", count=extra_count))
        self.more.setVisible(extra_count > 0)
        self.extra.setVisible(extra_count > 0 and self.more.isChecked())
        self.configure.setText(tr("main.guide.configure"))
        self.setVisible(bool(bindings))

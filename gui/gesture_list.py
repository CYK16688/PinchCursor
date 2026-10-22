"""Compact, grouped gesture rows for Precision Desk settings."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.gesture_icons_svg import GestureIconsSVG
from gui.i18n import tr
from gui.theme import use_styled_background


class GestureList(QWidget):
    CORE_POINTER_IDS = ("point", "pinch", "pinch_hold")
    CORE_CONTRACTS = {
        "point": "Move pointer",
        "pinch": "Click",
        "pinch_hold": "Drag",
    }
    GESTURE_NAMES = {
        "point": "Point", "pinch": "Pinch", "pinch_hold": "Pinch and hold",
        "peace": "Secondary click", "thumb_up": "Thumb up", "thumb_down": "Thumb down",
        "open_hand": "Open hand", "fist": "Fist", "ok": "OK", "rock": "Rock",
        "three": "Three fingers", "ilove_you": "I love you",
    }
    _GESTURE_LABEL_KEYS = {
        "point": "gesture.point",
        "pinch": "gesture.pinch",
        "pinch_hold": "gesture.pinch_hold",
        "peace": "gesture.peace",
        "thumb_up": "gesture.thumb_up",
        "thumb_down": "gesture.thumb_down",
        "open_hand": "gesture.open_hand",
        "fist": "gesture.fist",
        "ok": "gesture.ok",
        "rock": "gesture.rock",
        "three": "gesture.three",
        "ilove_you": "gesture.ilove_you",
    }
    _ACTION_LABEL_KEYS = {
        "none": "gesture.action.none",
        "left_click": "gesture.action.left_click",
        "right_click": "gesture.action.right_click",
        "custom_hotkey": "gesture.action.custom_hotkey",
    }
    _CONTRACT_LABEL_KEYS = {
        "point": "gesture.contract.move",
        "pinch": "gesture.contract.click",
        "pinch_hold": "gesture.contract.drag",
    }
    _GROUP_LABEL_KEYS = {
        "core": "gestures.core",
        "optional": "gestures.optional",
    }

    def __init__(self, gestures, parent=None, supported_actions=None):
        super().__init__(parent)
        self.gestures = deepcopy(gestures)
        self.supported_actions = frozenset(supported_actions) if supported_actions is not None else None
        self.rows = {}
        self._row_widgets = {}
        self._core_row_widgets = {}
        self._open_editors = {}
        self.core_contracts = dict(self.CORE_CONTRACTS)
        self._groups = {"core": [], "optional": []}
        self._build_ui()

    @classmethod
    def _gesture_label(cls, gesture_id):
        return tr(cls._GESTURE_LABEL_KEYS.get(gesture_id, "gesture.unavailable"))

    @classmethod
    def _action_label(cls, action_id):
        return tr(cls._ACTION_LABEL_KEYS.get(action_id, "gesture.action.none"))

    @classmethod
    def _contract_label(cls, gesture_id):
        return tr(cls._CONTRACT_LABEL_KEYS.get(gesture_id, "gesture.action.none"))

    def _build_ui(self):
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)
        self._group_headings = {}
        groups = (
            ("core", self.CORE_POINTER_IDS),
            ("optional", tuple(key for key in self.gestures if key not in self.CORE_POINTER_IDS)),
        )
        for group_id, ids in groups:
            heading = QLabel(tr(self._GROUP_LABEL_KEYS[group_id]))
            heading.setObjectName("summaryLabel")
            self._group_headings[group_id] = heading
            layout.addWidget(heading)
            for gesture_id in ids:
                if gesture_id not in self.gestures:
                    continue
                self._groups[group_id].append(gesture_id)
                if gesture_id in self.CORE_POINTER_IDS:
                    layout.addWidget(self._create_core_contract_row(gesture_id, self.gestures[gesture_id]))
                else:
                    layout.addWidget(self._create_row(gesture_id, self.gestures[gesture_id]))
        layout.addStretch()
        self._content_layout = layout
        scroll.setWidget(content)
        root.addWidget(scroll)

    def add_page_section(self, widget):
        """Append a section below the gesture rows, inside the same scroll.

        Stacking a second scroll region under this one clips the last row at the
        boundary and leaves the page with two independent scroll positions.
        """
        self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    GLYPH_SIZE = 26

    @classmethod
    def _glyph_label(cls, gesture_id):
        """The gesture's own pictogram, in a fixed slot.

        The slot is always present: a gesture without artwork must not shift its
        neighbours' controls, or the column reads as ragged.
        """
        label = QLabel()
        label.setFixedSize(cls.GLYPH_SIZE, cls.GLYPH_SIZE)
        label.setAlignment(Qt.AlignCenter)
        pixmap = GestureIconsSVG.pixmap(gesture_id, cls.GLYPH_SIZE, "#C6CBD5")
        if pixmap is not None:
            label.setPixmap(pixmap)
        return label

    def _create_row(self, gesture_id, config):
        row = QFrame()
        row.setObjectName("gestureSettingsRow")
        layout = QHBoxLayout(row)
        enabled = QCheckBox()
        enabled.setChecked(config.get("enabled", False))
        name = QLabel(self._gesture_label(gesture_id))
        name.setObjectName("gestureName")
        action = QComboBox()
        for action_id in self._ACTION_LABEL_KEYS:
            action.addItem(self._action_label(action_id), action_id)
        for index in range(action.count()):
            action_id = action.itemData(index)
            if action_id != "none" and self.supported_actions is not None and action_id not in self.supported_actions:
                action.model().item(index).setEnabled(False)
        configured_action = config.get("action", "none")
        if self.supported_actions is not None and configured_action not in {"none", *self.supported_actions}:
            enabled.setChecked(False)
            configured_action = "none"
        action.setCurrentIndex(max(action.findData(configured_action), 0))
        detail = QPushButton(tr("gesture.details"))
        detail.clicked.connect(lambda: self.open_details(gesture_id))
        layout.setSpacing(10)
        layout.addWidget(self._glyph_label(gesture_id))
        layout.addWidget(enabled)
        layout.addWidget(name, 1)
        layout.addWidget(action)
        layout.addWidget(detail)
        self.rows[gesture_id] = (enabled, action)
        self._row_widgets[gesture_id] = (name, action, detail)
        return row

    def _create_core_contract_row(self, gesture_id, config):
        """Show the non-remappable deterministic pointer contract."""
        row = QFrame()
        row.setObjectName("gestureSettingsRow")
        layout = QHBoxLayout(row)
        name = QLabel(self._gesture_label(gesture_id))
        name.setObjectName("gestureName")
        contract = QLabel(self._contract_label(gesture_id))
        contract.setObjectName("summaryLabel")
        if gesture_id == "pinch":
            detail = tr("gesture.contract.threshold", value=config.get("threshold", 35))
        elif gesture_id == "pinch_hold":
            detail = tr("gesture.contract.hold", value=config.get("hold_time", 0.3))
        else:
            detail = tr("gesture.details")
        settings = QLabel(detail)
        settings.setObjectName("hintLabel")
        layout.setSpacing(10)
        layout.addWidget(self._glyph_label(gesture_id))
        layout.addWidget(name, 1)
        layout.addWidget(contract)
        layout.addWidget(settings)
        self._core_row_widgets[gesture_id] = (name, contract, settings)
        return row

    def group_labels(self):
        return [tr(self._GROUP_LABEL_KEYS[group_id]) for group_id in self._groups]

    def group_gesture_ids(self, label):
        for group_id, key in self._GROUP_LABEL_KEYS.items():
            if label in {group_id, tr(key)}:
                return list(self._groups[group_id])
        return []

    def retranslate_ui(self):
        """Refresh static labels without changing staged action IDs or editor input."""
        for group_id, heading in self._group_headings.items():
            heading.setText(tr(self._GROUP_LABEL_KEYS[group_id]))
        for gesture_id, (name, action, detail) in self._row_widgets.items():
            selected_action = action.currentData()
            name.setText(self._gesture_label(gesture_id))
            for index in range(action.count()):
                action.setItemText(index, self._action_label(action.itemData(index)))
            action.setCurrentIndex(max(action.findData(selected_action), 0))
            detail.setText(tr("gesture.details"))
        for gesture_id, (name, contract, settings) in self._core_row_widgets.items():
            config = self.gestures[gesture_id]
            name.setText(self._gesture_label(gesture_id))
            contract.setText(self._contract_label(gesture_id))
            if gesture_id == "pinch":
                settings.setText(tr("gesture.contract.threshold", value=config.get("threshold", 35)))
            elif gesture_id == "pinch_hold":
                settings.setText(tr("gesture.contract.hold", value=config.get("hold_time", 0.3)))
            else:
                settings.setText(tr("gesture.details"))
        for editor in tuple(self._open_editors.values()):
            editor.retranslate_ui()

    def apply_to_config(self, config):
        for gesture_id, (enabled, action) in self.rows.items():
            config.set_gesture(gesture_id, "enabled", enabled.isChecked())
            config.set_gesture(gesture_id, "action", action.currentData())
            config.set_gesture(gesture_id, "hotkey", self.gestures[gesture_id].get("hotkey", ""))

    def open_details(self, gesture_id):
        """Open at most one staged details editor for each optional gesture."""
        existing = self._open_editors.get(gesture_id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing

        editor = GestureDetailsDialog(gesture_id, self.gestures[gesture_id], self)
        self._open_editors[gesture_id] = editor
        editor.finished.connect(
            lambda result, gid=gesture_id, active_editor=editor: self._finish_details(
                gid, active_editor, result
            )
        )
        editor.show()
        return editor

    def _finish_details(self, gesture_id, editor, result):
        """Apply only the currently active editor, then discard it immediately."""
        if self._open_editors.get(gesture_id) is not editor:
            return
        self._open_editors.pop(gesture_id, None)
        if result == QDialog.Accepted:
            self.gestures[gesture_id].update(editor.settings())
        editor.deleteLater()


class GestureDetailsDialog(QDialog):
    def __init__(self, gesture_id, config, parent=None):
        super().__init__(parent)
        use_styled_background(self)
        self.gesture_id = gesture_id
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.hotkey_input = QLineEdit(config.get("hotkey", ""))
        self.shortcut_label = QLabel()
        form.addRow(self.shortcut_label, self.hotkey_input)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton()
        self.apply_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.apply_button)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(f"{GestureList._gesture_label(self.gesture_id)} {tr('gesture.details')}")
        self.shortcut_label.setText(tr("gesture.details.shortcut"))
        self.cancel_button.setText(tr("common.cancel"))
        self.apply_button.setText(tr("common.apply"))

    def settings(self):
        return {"hotkey": self.hotkey_input.text().strip()}

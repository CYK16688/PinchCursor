"""组合动作卡片组件 - 配置手势组合触发的动作"""

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QLineEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPen

from core.intent_arbiter import CORE_POINTER_GESTURES
from utils.config_manager import COMBO_ACTIONS
from utils.hotkey_validation import normalize_hotkey
from gui.hotkey_input import HotkeyInput
from gui.i18n import tr


class ComboCard(QFrame):
    """组合动作配置卡片"""

    settingsChanged = Signal()
    deleteRequested = Signal(object)  # 请求删除此卡片

    # 可用手势列表
    GESTURES = [
        ("point", "指向"),
        ("pinch", "捏合"),
        ("pinch_hold", "捏合长按"),
        ("peace", "剪刀手"),
        ("open_hand", "张开手掌"),
        ("fist", "握拳"),
        ("thumb_up", "拇指向上"),
        ("thumb_down", "拇指向下"),
        ("ok", "OK手势"),
        ("rock", "摇滚手势"),
        ("three", "三指"),
    ]

    # Core pointer labels are intentionally absent: pointer move/click/drag is
    # an exclusive continuous lifecycle, not a generic shortcut sequence.
    GENERIC_COMBO_GESTURES = tuple(
        item for item in GESTURES if item[0] not in CORE_POINTER_GESTURES
    )

    # Generic combinations expose only commands the macOS adapter can execute.
    ACTIONS = tuple((action_id, action_id) for action_id in COMBO_ACTIONS)
    _GESTURE_LABEL_KEYS = {
        "point": "gesture.point", "pinch": "gesture.pinch",
        "pinch_hold": "gesture.pinch_hold", "peace": "gesture.peace",
        "open_hand": "gesture.open_hand", "fist": "gesture.fist",
        "thumb_up": "gesture.thumb_up", "thumb_down": "gesture.thumb_down",
        "ok": "gesture.ok", "rock": "gesture.rock", "three": "gesture.three",
    }
    _ACTION_LABEL_KEYS = {
        "left_click": "gesture.action.left_click", "right_click": "gesture.action.right_click",
        "double_click": "gesture.action.double_click",
        "middle_click": "gesture.action.middle_click", "scroll_up": "gesture.action.scroll_up",
        "scroll_down": "gesture.action.scroll_down",
        "custom_hotkey": "gesture.action.custom_hotkey",
    }

    @classmethod
    def _gesture_label(cls, gesture_id):
        return tr(cls._GESTURE_LABEL_KEYS.get(gesture_id, "gesture.unavailable"))

    @classmethod
    def _action_label(cls, action_id):
        return tr(cls._ACTION_LABEL_KEYS.get(action_id, "gesture.action.unavailable"))

    def __init__(self, combo_id=None, parent=None):
        super().__init__(parent)
        self.combo_id = combo_id or id(self)
        self.setObjectName("comboCard")
        self.setFixedHeight(100)
        self.init_ui()

    def init_ui(self):
        """初始化界面"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # 第一个手势
        gesture1_layout = QVBoxLayout()
        self.gesture1_label = QLabel(tr("combo.first_gesture"))
        self.gesture1_label.setObjectName("comboLabel")
        self.gesture1_combo = QComboBox()
        self.gesture1_combo.setObjectName("actionCombo")
        for gesture_id, _legacy_label in self.GESTURES:
            if gesture_id in CORE_POINTER_GESTURES:
                continue
            self.gesture1_combo.addItem(self._gesture_label(gesture_id), gesture_id)
        self.gesture1_combo.currentIndexChanged.connect(self.on_settings_changed)
        gesture1_layout.addWidget(self.gesture1_label)
        gesture1_layout.addWidget(self.gesture1_combo)
        layout.addLayout(gesture1_layout)

        # 加号
        plus_label = QLabel("+")
        plus_label.setObjectName("comboPlus")
        plus_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(plus_label)

        # 第二个手势
        gesture2_layout = QVBoxLayout()
        self.gesture2_label = QLabel(tr("combo.second_gesture"))
        self.gesture2_label.setObjectName("comboLabel")
        self.gesture2_combo = QComboBox()
        self.gesture2_combo.setObjectName("actionCombo")
        for gesture_id, _legacy_label in self.GESTURES:
            if gesture_id in CORE_POINTER_GESTURES:
                continue
            self.gesture2_combo.addItem(self._gesture_label(gesture_id), gesture_id)
        self.gesture2_combo.setCurrentIndex(1)  # 默认选择第二个可用的非核心手势
        self.gesture2_combo.currentIndexChanged.connect(self.on_settings_changed)
        gesture2_layout.addWidget(self.gesture2_label)
        gesture2_layout.addWidget(self.gesture2_combo)
        layout.addLayout(gesture2_layout)

        # 箭头
        arrow_label = QLabel("→")
        arrow_label.setObjectName("comboArrow")
        arrow_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(arrow_label)

        # 动作
        action_layout = QVBoxLayout()
        self.action_label = QLabel(tr("combo.action"))
        self.action_label.setObjectName("comboLabel")
        self.action_combo = QComboBox()
        self.action_combo.setObjectName("actionCombo")
        for action_id, _legacy_label in self.ACTIONS:
            self.action_combo.addItem(self._action_label(action_id), action_id)
        self.action_combo.currentIndexChanged.connect(self.on_action_changed)
        action_layout.addWidget(self.action_label)
        action_layout.addWidget(self.action_combo)
        layout.addLayout(action_layout)

        # 快捷键输入框（默认隐藏）
        self.hotkey_input = HotkeyInput()
        self.hotkey_input.setObjectName("hotkeyInput")
        self.hotkey_input.setPlaceholderText(tr("combo.hotkey_placeholder"))
        self.hotkey_input.setFixedWidth(120)
        self.hotkey_input.setVisible(False)
        self.hotkey_input.hotkeyChanged.connect(self.on_settings_changed)
        layout.addWidget(self.hotkey_input)

        # An unusable chord must be visible where it is typed: validation fails
        # closed on save, which used to delete the whole combo without a word.
        self.hotkey_error = QLabel("")
        self.hotkey_error.setObjectName("fieldError")
        self.hotkey_error.setWordWrap(True)
        self.hotkey_error.setVisible(False)
        layout.addWidget(self.hotkey_error)

        # 删除按钮
        self.delete_btn = QPushButton("×")
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.setFixedSize(30, 30)
        self.delete_btn.clicked.connect(lambda: self.deleteRequested.emit(self))
        layout.addWidget(self.delete_btn)

    def on_action_changed(self):
        """动作变更时更新快捷键输入框可见性"""
        is_custom = self.action_combo.currentData() == "custom_hotkey"
        self.hotkey_input.setVisible(is_custom)
        self.on_settings_changed()

    def on_settings_changed(self):
        """设置变更"""
        self.refresh_hotkey_validity()
        self.settingsChanged.emit()

    def refresh_hotkey_validity(self):
        """Say why a shortcut cannot be saved, while the user is still looking at it."""
        if self.action_combo.currentData() != "custom_hotkey":
            self.hotkey_error.setText("")
            self.hotkey_error.setVisible(False)
            return
        raw = self.hotkey_input.text().strip()
        if not raw:
            self.hotkey_error.setText(tr("combo.hotkey_required"))
            self.hotkey_error.setVisible(True)
            return
        try:
            normalize_hotkey(raw)
        except ValueError:
            self.hotkey_error.setText(tr("combo.hotkey_invalid"))
            self.hotkey_error.setVisible(True)
            return
        self.hotkey_error.setText("")
        self.hotkey_error.setVisible(False)

    def hotkey_is_valid(self) -> bool:
        """True when this card can be persisted without losing its combination."""
        if self.action_combo.currentData() != "custom_hotkey":
            return True
        try:
            normalize_hotkey(self.hotkey_input.text().strip())
        except ValueError:
            return False
        return True

    def get_settings(self):
        """获取当前设置"""
        return {
            "id": self.combo_id,
            "gesture1": self.gesture1_combo.currentData(),
            "gesture2": self.gesture2_combo.currentData(),
            "action": self.action_combo.currentData(),
            "hotkey": self.hotkey_input.text()
        }

    def load_settings(self, settings):
        """加载设置"""
        if not settings:
            return

        self.combo_id = settings.get("id", self.combo_id)

        g1 = settings.get("gesture1", "point")
        idx = self.gesture1_combo.findData(g1)
        if idx >= 0:
            self.gesture1_combo.setCurrentIndex(idx)

        g2 = settings.get("gesture2", "pinch")
        idx = self.gesture2_combo.findData(g2)
        if idx >= 0:
            self.gesture2_combo.setCurrentIndex(idx)

        action = settings.get("action", "left_click")
        idx = self.action_combo.findData(action)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)

        hotkey = settings.get("hotkey", "")
        self.hotkey_input.setText(hotkey)
        self.hotkey_input.setVisible(action == "custom_hotkey")

    def retranslate_ui(self):
        """Refresh labels only; stable combo IDs and staged input remain unchanged."""
        selected_gesture1 = self.gesture1_combo.currentData()
        selected_gesture2 = self.gesture2_combo.currentData()
        selected_action = self.action_combo.currentData()
        self.gesture1_label.setText(tr("combo.first_gesture"))
        self.gesture2_label.setText(tr("combo.second_gesture"))
        self.action_label.setText(tr("combo.action"))
        self.hotkey_input.setPlaceholderText(tr("combo.hotkey_placeholder"))
        for index in range(self.gesture1_combo.count()):
            self.gesture1_combo.setItemText(
                index, self._gesture_label(self.gesture1_combo.itemData(index))
            )
        for index in range(self.gesture2_combo.count()):
            self.gesture2_combo.setItemText(
                index, self._gesture_label(self.gesture2_combo.itemData(index))
            )
        for index in range(self.action_combo.count()):
            self.action_combo.setItemText(
                index, self._action_label(self.action_combo.itemData(index))
            )
        self.gesture1_combo.setCurrentIndex(max(self.gesture1_combo.findData(selected_gesture1), 0))
        self.gesture2_combo.setCurrentIndex(max(self.gesture2_combo.findData(selected_gesture2), 0))
        self.action_combo.setCurrentIndex(max(self.action_combo.findData(selected_action), 0))

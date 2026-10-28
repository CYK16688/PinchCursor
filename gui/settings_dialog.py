"""设置对话框 - 卡片式手势配置界面（参考Gameface设计）"""

from copy import deepcopy
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QListWidget,
    QListWidgetItem, QStackedWidget,
    QWidget, QLabel, QSlider, QComboBox, QGroupBox,
    QFormLayout, QPushButton, QSpinBox, QScrollArea,
    QFrame, QCheckBox, QLineEdit, QDoubleSpinBox, QMessageBox
)
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon

from . import icons

from .camera_settings_page import CameraSettingsPage
from .feedback_settings_page import FeedbackSettingsPage
from .gesture_list import GestureList
from .dynamic_gesture_settings_page import DynamicGestureSettingsPage
from .static_gesture_record_dialog import StaticGestureRecordDialog
from platform_services.factory import create_platform_services
from platform_services.camera_selection import open_configured_camera
from core.mediapipe_worker import MediaPipeVideoWorker
from utils.camera_utils import open_camera
from utils.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale
from gui.i18n import tr, translate
from gui.controls import SegmentedControl, ToggleSwitch
from gui.theme import use_styled_background



def styled_form(parent=None):
    """A QFormLayout with the dialog's shared alignment.

    Labels in this dialog are Chinese or English phrases of very different
    lengths, so without an explicit column policy every row's field started at a
    different x — the ragged left edge was the most visible flaw on the page.
    Right-aligning the label column and pinning its width keeps the controls on
    one vertical line in both languages.
    """
    form = QFormLayout(parent)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    return form

def slider_row(form, label, slider, value_text):
    """Add a slider to a form with a live numeric readout beside it.

    A bare QSlider gives no way to read or set an exact value: the handle's
    position is the only information, and "smoothing" here is 0.001-0.02 stored
    as slider/1000, so the number is not guessable at all.
    """
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    row.addWidget(slider, 1)
    readout = QLabel()
    readout.setObjectName("sliderValue")
    readout.setMinimumWidth(64)
    readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    row.addWidget(readout)

    def _refresh(*_args):
        readout.setText(value_text(slider.value()))

    slider.valueChanged.connect(_refresh)
    _refresh()
    form.addRow(label, holder)
    return readout


class SettingsDialog(QDialog):
    """设置对话框 - 卡片式布局"""

    # 手势列表 - 按使用热度排序
    GESTURES = [
        # 核心手势（高频使用）
        ("point", "指向", "控制光标移动，最常用的手势"),
        ("pinch", "捏合", "拇指食指捏合，用于点击"),
        ("pinch_hold", "捏合长按", "持续捏合，用于拖动"),
        ("peace", "剪刀手", "食指中指伸出，常用于右键"),
        # 常用手势
        ("thumb_up", "拇指向上", "竖起大拇指，点赞手势"),
        ("thumb_down", "拇指向下", "大拇指向下"),
        ("open_hand", "张开手掌", "五指张开"),
        ("fist", "握拳", "握紧拳头"),
        # 扩展手势
        ("ilove_you", "我爱你手势", "拇指、食指和小指伸出"),
        ("ok", "OK手势", "拇指食指成圈"),
        ("rock", "摇滚手势", "拇指小指伸出"),
        ("three", "三指", "食指中指无名指伸出"),
    ]

    def __init__(self, config, parent=None, camera_service=None):
        super().__init__(parent)
        use_styled_background(self)
        self.config = config
        self.camera_service = camera_service or create_platform_services().camera_service
        self.combo_cards = []
        self.current_section_id = "control"
        session = self.config.get("control_session") or {}
        self._staged_static_templates = deepcopy(session.get("custom_static_templates") or [])
        # A pinch calibration measured in this dialog, applied only by Save.
        self._staged_calibration = None
        self.init_ui()

    _GESTURE_LABEL_KEYS = {
        "point": "gesture.point",
        "pinch": "gesture.pinch",
        "pinch_hold": "gesture.pinch_hold",
        "peace": "gesture.peace",
        "thumb_up": "gesture.thumb_up",
        "thumb_down": "gesture.thumb_down",
        "open_hand": "gesture.open_hand",
        "fist": "gesture.fist",
        "ilove_you": "gesture.ilove_you",
        "ok": "gesture.ok",
        "rock": "gesture.rock",
        "three": "gesture.three",
    }
    # Each sidebar entry carries the glyph for its job, so the list is scannable
    # by shape before it is read as words.
    _SECTION_ICONS = {
        "control": "sliders",
        "gestures": "hand",
        "camera": "camera",
        "feedback": "meter",
        "permissions": "shield",
        "advanced": "gear",
    }

    def _section_icon(self, section_id):
        name = self._SECTION_ICONS.get(section_id)
        if name is None:
            return QIcon()
        icon = QIcon()
        for color, state, mode in (
            ("#8B93A1", QIcon.Off, QIcon.Normal),
            ("#F5F7FA", QIcon.On, QIcon.Selected),
            ("#F5F7FA", QIcon.On, QIcon.Active),
        ):
            icon.addPixmap(icons.padded_pixmap(name, color, 18, 7), mode, state)
        return icon

    _PERMISSION_LABEL_KEYS = {
        "granted": "permission.granted",
        "denied": "permission.denied",
        "not_determined": "permission.not_determined",
        "unavailable": "permission.unavailable",
    }

    _LANGUAGE_LABEL_KEYS = {
        "zh_CN": "language.zh_CN",
        "en_US": "language.en_US",
    }

    @classmethod
    def _language_label(cls, locale):
        return tr(cls._LANGUAGE_LABEL_KEYS.get(locale, "language.zh_CN"))

    def _staged_language(self):
        """Read a valid locale without mutating config before explicit Save."""
        ui = self.config.get("ui") or {}
        return normalize_locale(ui.get("language", DEFAULT_LOCALE))

    @classmethod
    def _gesture_label(cls, gesture_id):
        return tr(cls._GESTURE_LABEL_KEYS.get(gesture_id, "gesture.unavailable"))

    @classmethod
    def _permission_label(cls, state):
        value = getattr(state, "value", state)
        return tr(cls._PERMISSION_LABEL_KEYS.get(value, "permission.unavailable"))

    @staticmethod
    def _permission_semantics(state):
        """Map an authorization state onto the theme's dot/value semantics."""
        value = getattr(state, "value", state)
        mapping = {
            "granted": ("granted", ""),
            "denied": ("denied", "denied"),
            "not_determined": ("pending", "pending"),
        }
        return mapping.get(value, ("", ""))

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle(tr("settings.window_title"))
        self.setMinimumSize(900, 640)
        self.resize(1040, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self.title_label = QLabel(tr("settings.title"))
        self.title_label.setObjectName("sectionTitle")
        layout.addWidget(self.title_label)

        content = QHBoxLayout()
        content.setSpacing(16)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setFixedWidth(178)
        self.sidebar.setIconSize(QSize(25, 18))
        self.sections = QStackedWidget()
        self.section_ids = []
        self._section_label_keys = {
            "control": "settings.section.control",
            "gestures": "settings.section.gestures",
            "camera": "settings.section.camera",
            "feedback": "settings.section.feedback",
            "permissions": "settings.section.permissions",
            "advanced": "settings.section.advanced",
        }
        for section_id, label, page in self._create_sections():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, section_id)
            item.setIcon(self._section_icon(section_id))
            self.sidebar.addItem(item)
            self.sections.addWidget(page)
            self.section_ids.append(section_id)
        self.sidebar.currentRowChanged.connect(self._select_section_row)
        self.sidebar.setCurrentRow(0)

        # Language is an app-level choice, not a page field: it belongs at the
        # bottom of the navigation column, where it also stops stealing a strip
        # of height from every page.
        sidebar_column = QVBoxLayout()
        sidebar_column.setSpacing(8)
        sidebar_column.addWidget(self.sidebar, 1)
        language_row = QHBoxLayout()
        self.language_label = QLabel(translate("settings.language", locale=self._staged_language()))
        self.language_combo = QComboBox()
        for locale in SUPPORTED_LOCALES:
            self.language_combo.addItem(
                translate(self._LANGUAGE_LABEL_KEYS[locale], locale=self._staged_language()), locale
            )
        self.language_combo.setCurrentIndex(
            max(self.language_combo.findData(self._staged_language()), 0)
        )
        language_row.addWidget(self.language_label)
        language_row.addWidget(self.language_combo, 1)
        sidebar_column.addLayout(language_row)

        content.addLayout(sidebar_column)
        content.addWidget(self.sections, 1)
        layout.addLayout(content, 1)

        # 按钮
        btn_layout = QHBoxLayout()
        self.reset_button = QPushButton(tr("common.restore_defaults"))
        self.reset_button.clicked.connect(self.reset_defaults)
        self.save_button = QPushButton(tr("common.save"))
        self.save_button.setObjectName("saveBtn")
        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button = QPushButton(tr("common.cancel"))
        self.cancel_button.clicked.connect(self.reject)
        btn_layout.addWidget(self.reset_button)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.cancel_button)
        layout.addLayout(btn_layout)

    def _create_sections(self):
        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        self.advanced_title_label = QLabel(tr("settings.advanced.title"))
        self.advanced_title_label.setObjectName("settingsPageTitle")
        self.advanced_copy_label = QLabel(tr("settings.advanced.description"))
        self.advanced_copy_label.setObjectName("hintLabel")
        self.advanced_copy_label.setWordWrap(True)
        self.advanced_tabs = QTabWidget()
        self.advanced_tabs.addTab(self.create_combo_tab(), tr("settings.advanced.tab.combos"))
        self.advanced_tabs.addTab(self.create_context_rules_tab(), tr("settings.advanced.tab.context"))
        self.advanced_tabs.addTab(self.create_zones_tab(), tr("settings.advanced.tab.zones"))
        self.advanced_tabs.addTab(self.create_global_tab(), tr("settings.advanced.tab.diagnostics"))
        self.diagnostics_page = self._create_diagnostics_tab()
        advanced_layout.addWidget(self.advanced_title_label)
        advanced_layout.addWidget(self.advanced_copy_label)
        advanced_layout.addWidget(self.advanced_tabs, 1)
        self.camera_page = CameraSettingsPage(self.config, self.camera_service)
        capabilities = create_platform_services().capabilities
        self.gesture_page = GestureList(
            self.config.get("gestures") or {},
            supported_actions=capabilities.supported_actions,
        )
        self.dynamic_gesture_page = DynamicGestureSettingsPage(
            self.config, self.gesture_page, self.camera_service
        )
        self.gesture_page.add_page_section(self.dynamic_gesture_page)
        self.feedback_page = FeedbackSettingsPage(self.config)
        return [
            ("control", tr("settings.section.control"), self.create_control_page()),
            ("gestures", tr("settings.section.gestures"), self.gesture_page),
            ("camera", tr("settings.section.camera"), self.camera_page),
            ("feedback", tr("settings.section.feedback"), self.feedback_page),
            ("permissions", tr("settings.section.permissions"), self.create_permissions_page()),
            ("advanced", tr("settings.section.advanced"), advanced),
        ]

    def _select_section_row(self, row):
        if row < 0:
            return
        self.sections.setCurrentIndex(row)
        self.current_section_id = self.section_ids[row]

    def open_section(self, section_id):
        """Select a Precision Desk settings page by its stable identifier."""
        control_tab = {"control": 0, "pointer": 0, "activation": 1}.get(section_id)
        if control_tab is not None:
            section_id = "control"
            self.control_tabs.setCurrentIndex(control_tab)
        if section_id not in self.section_ids:
            raise ValueError(f"Unknown settings section: {section_id}")
        self.sidebar.setCurrentRow(self.section_ids.index(section_id))

    def retranslate_ui(self):
        """Refresh fixed Settings copy without persisting or replacing staged values."""
        self.setWindowTitle(tr("settings.window_title"))
        self.title_label.setText(tr("settings.title"))
        self.language_label.setText(tr("settings.language"))
        selected_language = self.language_combo.currentData()
        for index in range(self.language_combo.count()):
            locale = self.language_combo.itemData(index)
            self.language_combo.setItemText(index, self._language_label(locale))
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(selected_language), 0))
        learned_label = getattr(self, "assist_learned_label", None)
        if learned_label is not None:
            learned_label.setText(self._assist_learned_text())
        self.reset_button.setText(tr("common.restore_defaults"))
        self.save_button.setText(tr("common.save"))
        self.cancel_button.setText(tr("common.cancel"))
        for index, section_id in enumerate(self.section_ids):
            self.sidebar.item(index).setText(tr(self._section_label_keys[section_id]))

        self.control_title_label.setText(tr("settings.control.title"))
        self.control_description_label.setText(tr("settings.control.description"))
        self.activation_group.setTitle(tr("settings.control.activation"))
        self.timing_group.setTitle(tr("settings.control.timing.title"))
        self.assist_group.setTitle(tr("settings.control.assist.title"))
        for index, key in enumerate(self._control_tab_keys):
            self.control_tabs.setTabText(index, tr(key))
        selected_mode = self.session_mode.currentData()
        for mode, key in self._session_mode_keys.items():
            self.session_mode.setItemText(self.session_mode.findData(mode), tr(key))
        self.session_mode.setCurrentIndex(max(self.session_mode.findData(selected_mode), 0))
        for selector in (self.activation_gesture, self.exit_gesture):
            selected_value = selector.currentData()
            for index in range(selector.count()):
                gesture_id = selector.itemData(index)
                if selector.itemData(index, Qt.UserRole + 1):
                    template = next(
                        (item for item in self._staged_static_templates if item.get("template_id") == gesture_id),
                        {},
                    )
                    selector.setItemText(
                        index,
                        tr(
                            "settings.control.custom_trigger.option",
                            template_name=str(template.get("name") or gesture_id),
                        ),
                    )
                else:
                    selector.setItemText(index, self._gesture_label(gesture_id))
            selector.setCurrentIndex(max(selector.findData(selected_value), 0))
        self.always_active_notice.setText(tr("settings.control.always_active_hint"))
        self.stability_seconds.setSuffix(tr("common.unit.ms"))
        self.no_hand_timeout_seconds.setSuffix(tr("common.unit.seconds"))
        self.mode_label.setText(tr("settings.control.mode"))
        self.activation_gesture_label.setText(tr("settings.control.activation_gesture"))
        self.exit_gesture_label.setText(tr("settings.control.exit_gesture"))
        self.hold_shortcut_label.setText(tr("settings.control.hold_shortcut"))
        self.stability_seconds_label.setText(tr("settings.control.activation_stability"))
        self.no_hand_timeout_seconds_label.setText(tr("settings.control.hand_loss_timeout"))
        self.custom_trigger_group.setTitle(tr("settings.control.custom_trigger.title"))
        self.custom_trigger_copy_label.setText(tr("settings.control.custom_trigger.description"))
        self.record_trigger_button.setText(tr("settings.control.custom_trigger.record"))
        self.custom_triggers_summary.setText(self._custom_trigger_summary())

        # Pinch calibration copy.
        self.calibrate_button.setText(tr("settings.control.calibrate.button"))
        self._refresh_calibration_summary()

        # Pointer / assist / mapping / performance. These were created with tr()
        # but never revisited, so switching zh->en left them in the old language —
        # the "half-translated dialog" the review reported.
        self.pointer_group.setTitle(tr("settings.control.pointer.title"))
        self.point_assist_label.setText(tr("settings.control.pointer.assist"))
        self.point_assist_check.setText(tr("settings.control.pointer.assist"))
        self.point_assist_hint.setText(tr("settings.control.pointer.assist_hint"))
        self.assist_mode_label.setText(tr("settings.control.assist.mode"))
        self.assist_mode_hint.setText(tr("settings.control.assist.mode_hint"))
        for mode, key in (
            ("bayesian", "settings.control.assist.bayesian"),
            ("shadow", "settings.control.assist.shadow"),
            ("ranker", "settings.control.assist.ranker"),
        ):
            index = self.assist_mode.findData(mode)
            if index >= 0:
                self.assist_mode.setItemText(index, tr(key))
        self.mapping_mode_label.setText(tr("settings.control.mapping.mode"))
        self.mapping_gain_label.setText(tr("settings.control.mapping.gain"))
        self.mapping_hint.setText(tr("settings.control.mapping.hint"))
        for mode, key in self._mapping_mode_keys.items():
            index = self.mapping_mode.findData(mode)
            if index >= 0:
                self.mapping_mode.setItemText(index, tr(key))
        self.performance_group.setTitle(tr("settings.control.performance.title"))
        self.performance_label.setText(tr("settings.control.performance.mode"))
        self.performance_hint.setText(tr("settings.control.performance.hint"))
        for mode in ("standard", "performance"):
            index = self.performance_mode.findData(mode)
            if index >= 0:
                # An explicit key map: interpolating a key here defeats every
                # static catalogue audit and hides a typo until runtime.
                self.performance_mode.setItemText(
                    index, tr(self._PERFORMANCE_MODE_KEYS[mode])
                )

        # Telemetry. Context awareness and intent toggles are retranslated
        # further down with the other advanced groups; this block sits outside
        # them, which is why it was missed.
        self.telemetry_group.setTitle(tr("settings.advanced.global.telemetry"))
        self.telemetry_label.setText(tr("settings.advanced.global.telemetry_enabled"))
        self.telemetry_check.setText(tr("settings.advanced.global.enable"))
        self.telemetry_hint_label.setText(tr("settings.advanced.global.telemetry_description"))
        self.purge_telemetry_button.setText(tr("settings.advanced.global.telemetry_purge"))

        self.permissions_title_label.setText(tr("settings.permissions.title"))
        self.permissions_group.setTitle(tr("settings.permissions.system_access"))
        self.permissions_camera_label.setText(tr("settings.permissions.camera"))
        self.permissions_accessibility_label.setText(tr("settings.permissions.accessibility"))
        self.permissions_input_monitoring_label.setText(tr("settings.permissions.input_monitoring"))
        self.permissions_copy_label.setText(tr("settings.permissions.description"))
        self.request_accessibility_button.setText(tr("settings.permissions.request_accessibility"))
        self.request_camera_button.setText(tr("settings.permissions.request_camera"))
        self.request_input_monitoring_button.setText(tr("settings.permissions.request_input_monitoring"))
        self.recheck_permissions_button.setText(tr("settings.permissions.recheck"))
        self.restart_hint_label.setText(tr("settings.permissions.restart_hint"))

        self.advanced_title_label.setText(tr("settings.advanced.title"))
        self.advanced_copy_label.setText(tr("settings.advanced.description"))
        for index, key in enumerate((
            "settings.advanced.tab.combos",
            "settings.advanced.tab.context",
            "settings.advanced.tab.zones",
            "settings.advanced.tab.diagnostics",
            "settings.advanced.tab.stats",
        )):
            self.advanced_tabs.setTabText(index, tr(key))
        if hasattr(self, "diagnostics_page"):
            self.diagnostics_page.retranslate_ui()
        self.combo_hint_label.setText(tr("settings.advanced.combo.description"))
        if hasattr(self, "combo_empty_label"):
            self.combo_empty_label.setText(tr("settings.advanced.combo.empty"))
        self.combo_add_button.setText(tr("settings.advanced.combo.add"))
        self.context_rules_hint_label.setText(tr("settings.advanced.context.description"))
        for control_id, key in self.control_types:
            self.context_groups[control_id].setTitle(tr(key))
            for gesture_id, gesture_key in self.gesture_types:
                self.context_checkboxes[control_id][gesture_id].setText(tr(gesture_key))
        self.zones_info_label.setText(tr("settings.advanced.zones.description"))
        self.zones_add_button.setText(tr("settings.advanced.zones.add"))
        for index in range(self.zones_list.count()):
            frame = self.zones_list.itemAt(index).widget()
            if frame is None or not hasattr(frame, "zone_data"):
                continue
            zone = frame.zone_data
            zone["x_label"].setText(tr("settings.advanced.zones.x"))
            zone["y_label"].setText(tr("settings.advanced.zones.y"))
            zone["width_label"].setText(tr("settings.advanced.zones.width"))
            zone["height_label"].setText(tr("settings.advanced.zones.height"))
            zone["click"].setText(tr("settings.advanced.zones.click"))
            zone["drag"].setText(tr("settings.advanced.zones.drag"))
            zone["delete_button"].setText(tr("settings.advanced.zones.delete"))
        self.global_mouse_group.setTitle(tr("settings.advanced.global.mouse"))
        self.scroll_speed_label.setText(tr("settings.advanced.global.scroll_speed"))
        self.smoothing_label.setText(tr("settings.advanced.global.smoothing"))
        self.dead_zone_label.setText(tr("settings.advanced.global.dead_zone"))
        self.dead_zone_hint.setText(tr("settings.advanced.global.dead_zone_hint"))
        self.global_detection_group.setTitle(tr("settings.advanced.global.detection"))
        self.detection_conf_label.setText(tr("settings.advanced.global.confidence"))
        self.tracking_conf_label.setText(tr("settings.advanced.global.tracking_confidence"))
        self.global_stabilization_group.setTitle(tr("settings.advanced.global.stabilization"))
        self.confirm_threshold_label.setText(tr("settings.advanced.global.confirm_frames"))
        self.min_switch_interval_label.setText(tr("settings.advanced.global.switch_interval"))
        self.global_context_group.setTitle(tr("settings.advanced.global.context"))
        self.context_aware_check.setText(tr("settings.advanced.global.enable"))
        self.context_aware_label.setText(tr("settings.advanced.global.context_aware"))
        self.global_context_hint_label.setText(tr("settings.advanced.global.context_description"))
        self.intent_actions_check.setText(tr("settings.advanced.global.intent_enabled"))
        self.intent_actions_label.setText(tr("settings.advanced.global.intent"))
        self.intent_hint_label.setText(tr("settings.advanced.global.intent_description"))
        for card in self.combo_cards:
            card.retranslate_ui()
        self.camera_page.retranslate_ui()
        self.feedback_page.retranslate_ui()
        self.gesture_page.retranslate_ui()
        self.dynamic_gesture_page.retranslate_ui()
        self._refresh_control_mode_fields()
        self._refresh_control_accessibility()

    def create_control_page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.control_title_label = QLabel(tr("settings.control.title"))
        self.control_title_label.setObjectName("settingsPageTitle")
        self.control_description_label = QLabel(tr("settings.control.description"))
        self.control_description_label.setObjectName("hintLabel")
        self.control_description_label.setWordWrap(True)
        layout.addWidget(self.control_title_label)
        # The title and task tabs establish the page hierarchy without a
        # second sentence repeating the navigation.
        self.control_description_label.hide()
        self.control_tabs = QTabWidget()
        self._control_tab_keys = (
            "settings.control.tab.pointer",
            "settings.control.tab.activation",
            "settings.control.tab.advanced",
        )
        self.pointer_page, pointer_layout = self._control_tab_page()
        self.activation_page, activation_layout = self._control_tab_page()
        self.control_advanced_page, advanced_layout = self._control_tab_page()
        for page, key in zip(
            (self.pointer_page, self.activation_page, self.control_advanced_page),
            self._control_tab_keys,
        ):
            self.control_tabs.addTab(page, tr(key))
        layout.addWidget(self.control_tabs, 1)
        self.activation_group = QGroupBox(tr("settings.control.activation"))
        form = styled_form(self.activation_group)
        session = self.config.get("control_session") or {}
        # Four mutually exclusive activation modes. A segmented control keeps
        # every option visible, so choosing is one click instead of two and the
        # alternatives are discoverable without opening anything.
        self.session_mode = SegmentedControl()
        self._session_mode_keys = {
            "gesture": "settings.control.mode.gesture",
            "hold_shortcut": "settings.control.mode.hold_shortcut",
            "gesture_or_shortcut": "settings.control.mode.gesture_or_shortcut",
            "always": "settings.control.mode.always",
        }
        self._PERFORMANCE_MODE_KEYS = {
            "standard": "settings.control.performance.standard",
            "performance": "settings.control.performance.performance",
        }
        for mode, key in self._session_mode_keys.items():
            self.session_mode.addItem(tr(key), mode)
        mode_index = self.session_mode.findData(session.get("mode", "gesture"))
        self.session_mode.setCurrentIndex(max(mode_index, 0))
        self.activation_gesture = QComboBox()
        self.exit_gesture = QComboBox()
        for gesture_id, _gesture_name, _ in self.GESTURES:
            self.activation_gesture.addItem(self._gesture_label(gesture_id), gesture_id)
            self.exit_gesture.addItem(self._gesture_label(gesture_id), gesture_id)
        self._add_custom_trigger_options()
        self._activation_builtin_gesture = session.get("activation_gesture", "open_hand")
        self._exit_builtin_gesture = session.get("exit_gesture", "fist")
        self._select_trigger_option(
            self.activation_gesture,
            session.get("activation_template_id", ""),
            self._activation_builtin_gesture,
        )
        self._select_trigger_option(
            self.exit_gesture,
            session.get("exit_template_id", ""),
            self._exit_builtin_gesture,
        )
        self.hold_shortcut = QLineEdit(session.get("hold_shortcut", ""))
        self.always_active_notice = QLabel(tr("settings.control.always_active_hint"))
        self.always_active_notice.setObjectName("hintLabel")
        self.always_active_notice.setWordWrap(True)
        self.stability_seconds = QSpinBox()
        self.stability_seconds.setRange(0, 3000)
        self.stability_seconds.setSuffix(tr("common.unit.ms"))
        self.stability_seconds.setValue(round(session.get("stability_seconds", 0.3) * 1000))
        self.no_hand_timeout_seconds = QSpinBox()
        self.no_hand_timeout_seconds.setRange(1, 30)
        self.no_hand_timeout_seconds.setSuffix(tr("common.unit.seconds"))
        self.no_hand_timeout_seconds.setValue(round(session.get("no_hand_timeout_seconds", 2.0)))
        self.mode_label = QLabel(tr("settings.control.mode"))
        form.addRow(self.mode_label)
        form.addRow(self.session_mode)
        self.activation_gesture_label = QLabel(tr("settings.control.activation_gesture"))
        self.exit_gesture_label = QLabel(tr("settings.control.exit_gesture"))
        self.hold_shortcut_label = QLabel(tr("settings.control.hold_shortcut"))
        self.stability_seconds_label = QLabel(tr("settings.control.activation_stability"))
        self.no_hand_timeout_seconds_label = QLabel(tr("settings.control.hand_loss_timeout"))
        form.addRow(self.activation_gesture_label, self.activation_gesture)
        form.addRow(self.exit_gesture_label, self.exit_gesture)
        form.addRow(self.hold_shortcut_label, self.hold_shortcut)
        form.addRow(self.no_hand_timeout_seconds_label, self.no_hand_timeout_seconds)
        self.timing_group = QGroupBox(tr("settings.control.timing.title"))
        timing_form = styled_form(self.timing_group)
        timing_form.addRow(self.stability_seconds_label, self.stability_seconds)
        advanced_layout.addWidget(self.timing_group)

        # Calibration is a primary click task, alongside pointer tuning.
        self.calibrate_button = QPushButton(tr("settings.control.calibrate.button"))
        self.calibrate_button.clicked.connect(self.open_pinch_calibration)
        self.calibrate_hint = QLabel(tr("settings.control.calibrate.hint"))
        self.calibrate_hint.setObjectName("hintLabel")
        self.calibrate_hint.setWordWrap(True)
        self.calibration_panel = QWidget()
        calibration_layout = QVBoxLayout(self.calibration_panel)
        calibration_layout.setContentsMargins(0, 0, 0, 0)
        calibration_layout.setSpacing(8)
        self.calibration_actions_layout = QHBoxLayout()
        self.calibration_actions_layout.setSpacing(16)
        self.calibration_actions_layout.addWidget(self.calibrate_button)
        calibration_layout.addLayout(self.calibration_actions_layout)
        calibration_layout.addWidget(self.calibrate_hint)
        self.calibrate_hint.hide()
        form.addRow("", self.always_active_notice)
        self.session_mode.currentIndexChanged.connect(self._refresh_control_mode_fields)
        self._refresh_control_mode_fields()
        activation_layout.addWidget(self.activation_group)
        self.custom_trigger_group = QGroupBox(tr("settings.control.custom_trigger.title"))
        template_layout = QVBoxLayout(self.custom_trigger_group)
        self.custom_trigger_copy_label = QLabel(tr("settings.control.custom_trigger.description"))
        self.custom_trigger_copy_label.setObjectName("hintLabel")
        self.custom_trigger_copy_label.setWordWrap(True)
        self.record_trigger_button = QPushButton(tr("settings.control.custom_trigger.record"))
        self.record_trigger_button.clicked.connect(self.open_static_trigger_recording)
        self.custom_triggers_summary = QLabel(self._custom_trigger_summary())
        self.custom_triggers_summary.setObjectName("hintLabel")
        template_layout.addWidget(self.custom_trigger_copy_label)
        template_layout.addWidget(self.custom_triggers_summary)
        # A button added straight to a QVBoxLayout stretches to the panel width
        # and reads as a banner, competing with the dialog's real actions.
        trigger_row = QHBoxLayout()
        trigger_row.addWidget(self.record_trigger_button)
        trigger_row.addStretch()
        template_layout.addLayout(trigger_row)
        advanced_layout.addWidget(self.custom_trigger_group)

        self.pointer_group = QGroupBox(tr("settings.control.pointer.title"))
        pointer_form = styled_form(self.pointer_group)
        assist = self.config.get("pointer_assist") or {}
        self.point_assist_check = ToggleSwitch(tr("settings.control.pointer.assist"))
        self.point_assist_check.setChecked(bool(assist.get("enabled", True)))
        self.point_assist_hint = QLabel(tr("settings.control.pointer.assist_hint"))
        self.point_assist_hint.setObjectName("hintLabel")
        self.point_assist_hint.setWordWrap(True)
        self.point_assist_label = QLabel()
        self.point_assist_label.setVisible(False)
        # The switch carries its own name; its explanation is a tooltip.
        self.point_assist_hint.hide()

        self.assist_group = QGroupBox(tr("settings.control.assist.title"))
        assist_form = styled_form(self.assist_group)
        # Three short exclusive options: a segmented control shows all of them,
        # so the user can see what the alternatives are without opening a popup.
        self.assist_mode = SegmentedControl()
        for mode, key in (
            ("bayesian", "settings.control.assist.bayesian"),
            ("shadow", "settings.control.assist.shadow"),
            ("ranker", "settings.control.assist.ranker"),
        ):
            self.assist_mode.addItem(tr(key), mode)
        self.assist_mode.setCurrentData(assist.get("mode", "bayesian"))
        self.assist_mode_label = QLabel(tr("settings.control.assist.mode"))
        self.assist_mode_hint = QLabel(tr("settings.control.assist.mode_hint"))
        self.assist_mode_hint.setObjectName("hintLabel")
        self.assist_mode_hint.setWordWrap(True)
        assist_form.addRow(self.assist_mode_label)
        assist_form.addRow(self.assist_mode)
        assist_form.addRow(self.assist_mode_hint)
        advanced_layout.insertWidget(1, self.assist_group)

        mapping = self.config.get("pointer_mapping") or {}
        self.mapping_mode = SegmentedControl()
        self._mapping_mode_keys = {
            "absolute": "settings.control.mapping.absolute",
            "relative": "settings.control.mapping.relative",
        }
        for mode, key in self._mapping_mode_keys.items():
            self.mapping_mode.addItem(tr(key), mode)
        self.mapping_mode.setCurrentData(mapping.get("mode", "absolute"))
        self.mapping_gain = QDoubleSpinBox()
        self.mapping_gain.setRange(1.0, 4.0)
        self.mapping_gain.setSingleStep(0.2)
        self.mapping_gain.setDecimals(1)
        self.mapping_gain.setValue(float(mapping.get("gain", 2.0)))
        self.mapping_gain.setSuffix("×")
        self.mapping_mode_label = QLabel(tr("settings.control.mapping.mode"))
        self.mapping_gain_label = QLabel(tr("settings.control.mapping.gain"))
        self.mapping_hint = QLabel(tr("settings.control.mapping.hint"))
        self.mapping_hint.setObjectName("hintLabel")
        self.mapping_hint.setWordWrap(True)
        pointer_form.addRow(self.mapping_mode_label)
        pointer_form.addRow(self.mapping_mode)
        pointer_form.addRow(self.mapping_gain_label, self.mapping_gain)
        self.calibration_actions_layout.insertWidget(0, self.point_assist_check)
        self.calibration_actions_layout.insertStretch(1)
        pointer_form.addRow(self.calibration_panel)
        self.mapping_hint.hide()
        self.mapping_mode.currentIndexChanged.connect(self._refresh_mapping_fields)
        self._refresh_mapping_fields()
        pointer_layout.addWidget(self.pointer_group)
        # Reparent the existing tuning card rather than creating duplicate
        # controls: Save and Restore defaults still use the same widget values.
        pointer_layout.addWidget(self.global_mouse_group)
        self.dead_zone_hint.hide()

        performance = self.config.get("performance") or {}
        self.performance_group = QGroupBox(tr("settings.control.performance.title"))
        performance_form = styled_form(self.performance_group)
        self.performance_mode = SegmentedControl()
        for mode in ("standard", "performance"):
            self.performance_mode.addItem(
                tr(self._PERFORMANCE_MODE_KEYS[mode]), mode
            )
        self.performance_mode.setCurrentIndex(
            max(self.performance_mode.findData(performance.get("mode", "standard")), 0)
        )
        self.performance_label = QLabel(tr("settings.control.performance.mode"))
        self.performance_hint = QLabel(tr("settings.control.performance.hint"))
        self.performance_hint.setObjectName("hintLabel")
        self.performance_hint.setWordWrap(True)
        performance_form.addRow(self.performance_label)
        performance_form.addRow(self.performance_mode)
        performance_form.addRow(self.performance_hint)
        advanced_layout.addWidget(self.performance_group)
        for page_layout in (pointer_layout, activation_layout, advanced_layout):
            page_layout.addStretch()
        self._refresh_control_accessibility()
        return widget

    @staticmethod
    def _control_tab_page():
        """Keep each task independently scrollable at short window heights."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 14, 16)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll, layout

    def _refresh_control_accessibility(self):
        """Keep visible form labels and assistive names in sync across locales."""
        for label, field in (
            (self.mode_label, self.session_mode),
            (self.activation_gesture_label, self.activation_gesture),
            (self.exit_gesture_label, self.exit_gesture),
            (self.hold_shortcut_label, self.hold_shortcut),
            (self.stability_seconds_label, self.stability_seconds),
            (self.no_hand_timeout_seconds_label, self.no_hand_timeout_seconds),
            (self.mapping_mode_label, self.mapping_mode),
            (self.mapping_gain_label, self.mapping_gain),
            (self.assist_mode_label, self.assist_mode),
            (self.performance_label, self.performance_mode),
            (self.scroll_speed_label, self.scroll_speed),
            (self.smoothing_label, self.smoothing),
            (self.dead_zone_label, self.dead_zone),
        ):
            label.setBuddy(field)
            field.setAccessibleName(label.text())
        self.calibrate_button.setToolTip(tr("settings.control.calibrate.hint"))
        self.point_assist_check.setAccessibleName(tr("settings.control.pointer.assist"))
        self.point_assist_check.setToolTip(tr("settings.control.pointer.assist_hint"))
        self.mapping_mode.setToolTip(tr("settings.control.mapping.hint"))
        self.dead_zone.setToolTip(tr("settings.advanced.global.dead_zone_hint"))

    def open_pinch_calibration(self):
        """Run the guided pinch calibration and stage the resulting ratios.

        The result is held until Save like every other control in this dialog.
        Writing straight into the shared config meant Cancel — or closing the
        window — still left the new thresholds live, and the next save anywhere
        in the session committed them.
        """
        from .pinch_calibration_dialog import PinchCalibrationDialog

        dialog = PinchCalibrationDialog(
            camera_config=self.config.get("camera") or {},
            config=self.config,
            parent=self,
        )
        try:
            if dialog.exec() and dialog.calibration is not None:
                result = dialog.calibration
                self._staged_calibration = {
                    "enter_ratio": round(float(result.enter_ratio), 4),
                    "exit_ratio": round(float(result.exit_ratio), 4),
                    "sample_count": int(result.sample_count),
                }
                self._refresh_calibration_summary()
        finally:
            dialog.deleteLater()

    def _apply_calibration_stage(self):
        """Commit a pending calibration only at the Save boundary."""
        staged = getattr(self, "_staged_calibration", None)
        if not staged:
            return
        for key, value in staged.items():
            self.config.set("pinch_calibration", key, value)
        self._staged_calibration = None

    def _refresh_calibration_summary(self):
        """Show the staged thresholds so the user can see what Save will apply."""
        label = getattr(self, "calibrate_hint", None)
        if label is None:
            return
        staged = getattr(self, "_staged_calibration", None)
        if not staged:
            label.setText(tr("settings.control.calibrate.hint"))
            label.hide()
            return
        label.show()
        label.setText(tr(
            "settings.control.calibrate.pending",
            enter=staged["enter_ratio"],
            exit=staged["exit_ratio"],
            count=staged["sample_count"],
        ))

    def _refresh_mapping_fields(self):
        """Gain only applies to relative mapping; keep it visible but inert."""
        relative = self.mapping_mode.currentData() == "relative"
        self.mapping_gain.setEnabled(relative)
        self.mapping_gain_label.setEnabled(relative)

    def _refresh_control_mode_fields(self):
        """Progressively disclose only the controls needed by the selected activation mode."""
        mode = self.session_mode.currentData()
        uses_gesture = mode in {"gesture", "gesture_or_shortcut"}
        uses_shortcut = mode in {"hold_shortcut", "gesture_or_shortcut"}
        for label, field in (
            (self.activation_gesture_label, self.activation_gesture),
            (self.stability_seconds_label, self.stability_seconds),
        ):
            label.setVisible(uses_gesture)
            field.setVisible(uses_gesture)
        self.timing_group.setVisible(uses_gesture)
        self.hold_shortcut_label.setVisible(uses_shortcut)
        self.hold_shortcut.setVisible(uses_shortcut)
        self.exit_gesture_label.setVisible(mode != "always")
        self.exit_gesture.setVisible(mode != "always")
        self.always_active_notice.setVisible(mode == "always")

    def _custom_trigger_summary(self):
        return tr(
            "settings.control.custom_trigger.staged_count",
            count=len(self._staged_static_templates),
        )

    def _add_custom_trigger_options(self):
        for template in self._staged_static_templates:
            if not isinstance(template, dict):
                continue
            template_id = template.get("template_id")
            if not isinstance(template_id, str) or not template_id:
                continue
            name = str(template.get("name") or template_id)
            for selector in (self.activation_gesture, self.exit_gesture):
                if self._custom_trigger_index(selector, template_id) >= 0:
                    continue
                selector.addItem(
                    tr("settings.control.custom_trigger.option", template_name=name),
                    template_id,
                )
                selector.setItemData(selector.count() - 1, True, Qt.UserRole + 1)

    def _remove_custom_trigger_options(self):
        """Drop staged-template choices so selectors cannot reference deleted data."""
        for selector in (self.activation_gesture, self.exit_gesture):
            for index in range(selector.count() - 1, -1, -1):
                if selector.itemData(index, Qt.UserRole + 1):
                    selector.removeItem(index)

    def stage_static_template(self, template):
        """Stage a recorded static trigger until the user explicitly saves Settings."""
        if not isinstance(template, dict):
            return False
        template_id = template.get("template_id")
        feature_vector = template.get("feature_vector")
        if not isinstance(template_id, str) or not template_id or not isinstance(feature_vector, list):
            return False
        self._staged_static_templates = [
            item for item in self._staged_static_templates
            if not isinstance(item, dict) or item.get("template_id") != template_id
        ]
        self._staged_static_templates.append(deepcopy(template))
        self._add_custom_trigger_options()
        if hasattr(self, "custom_triggers_summary"):
            self.custom_triggers_summary.setText(self._custom_trigger_summary())
        return True

    @staticmethod
    def _custom_trigger_index(selector, template_id):
        for index in range(selector.count()):
            if (
                selector.itemData(index) == template_id
                and selector.itemData(index, Qt.UserRole + 1)
            ):
                return index
        return -1

    def _select_trigger_option(self, selector, template_id, gesture_id):
        template_index = self._custom_trigger_index(selector, template_id)
        if template_index >= 0:
            selector.setCurrentIndex(template_index)
            return
        selector.setCurrentIndex(max(selector.findData(gesture_id), 0))

    @staticmethod
    def _selected_template_id(selector):
        if selector.itemData(selector.currentIndex(), Qt.UserRole + 1):
            return selector.currentData()
        return ""

    def open_static_trigger_recording(self):
        """Open a dedicated preview; it never shares a camera session with control."""
        dialog = StaticGestureRecordDialog(parent=self)
        worker = self._start_recording_worker(dialog)
        try:
            if dialog.exec():
                template = dialog.saved_template
                if template is None:
                    return
                self.stage_static_template({
                    "template_id": template.template_id,
                    "name": template.name,
                    "feature_vector": list(template.feature_vector),
                    "threshold": template.threshold,
                })
        finally:
            if worker is not None:
                worker.stop()
                worker.wait(2000)
                worker.deleteLater()
            detector = getattr(dialog, "recording_detector", None)
            if detector is not None:
                detector.release()

    def _start_recording_worker(self, dialog):
        camera = self.config.get("camera") or {}
        detection = self.config.get("detection") or {}
        from core.detector_factory import create_detector

        detector = create_detector(
            "mediapipe",
            detection.get("confidence", 0.7),
            detection.get("tracking_confidence", 0.5),
        )
        capture = open_configured_camera(
            camera, self.camera_service, legacy_open=open_camera
        )
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            detector.release()
            dialog.preview.setText(tr("settings.static.camera_open_failed"))
            dialog.state = dialog.state.FAILED
            dialog._refresh()
            return None
        dialog.recording_detector = detector
        worker = MediaPipeVideoWorker(
            camera_id=camera.get("id", 0),
            width=camera.get("width", 640),
            height=camera.get("height", 480),
            detector=detector,
            capture=capture,
            parent=dialog,
        )
        worker.landmark_frame_ready.connect(dialog.accept_landmark_frame)
        worker.worker_error.connect(
            lambda _message: dialog.preview.setText(tr("settings.static.camera_open_failed"))
        )
        worker.start()
        return worker

    def create_permissions_page(self):
        permissions = create_platform_services().permission_provider.snapshot()
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.permissions_title_label = QLabel(tr("settings.permissions.title"))
        self.permissions_title_label.setObjectName("settingsPageTitle")
        layout.addWidget(self.permissions_title_label)
        self.permissions_group = QGroupBox(tr("settings.permissions.system_access"))
        form = styled_form(self.permissions_group)
        self.permissions_camera_label = QLabel(tr("settings.permissions.camera"))
        self.permissions_accessibility_label = QLabel(tr("settings.permissions.accessibility"))
        self.permissions_input_monitoring_label = QLabel(tr("settings.permissions.input_monitoring"))
        self.permissions_camera_value = QLabel(self._permission_label(permissions.camera))
        self.permissions_accessibility_value = QLabel(self._permission_label(permissions.accessibility))
        self.permissions_input_monitoring_value = QLabel(self._permission_label(permissions.input_monitoring))
        # Same dot vocabulary as the main window: a binary fact reads at a glance.
        self.permission_dots = {}
        for key, name_label, value_label, state in (
            ("camera", self.permissions_camera_label, self.permissions_camera_value, permissions.camera),
            ("accessibility", self.permissions_accessibility_label, self.permissions_accessibility_value, permissions.accessibility),
            ("input_monitoring", self.permissions_input_monitoring_label, self.permissions_input_monitoring_value, permissions.input_monitoring),
        ):
            value_label.setObjectName("permissionValue")
            dot = QLabel()
            dot.setObjectName("statusDot")
            semantic, value_semantic = self._permission_semantics(state)
            dot.setProperty("semantic", semantic)
            value_label.setProperty("semantic", value_semantic)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(dot)
            row_layout.addWidget(value_label)
            row_layout.addStretch()
            self.permission_dots[key] = (dot, value_label)
            form.addRow(name_label, row)
        layout.addWidget(self.permissions_group)
        self.permissions_copy_label = QLabel(tr("settings.permissions.description"))
        self.permissions_copy_label.setObjectName("hintLabel")
        self.permissions_copy_label.setWordWrap(True)
        layout.addWidget(self.permissions_copy_label)
        self.request_accessibility_button = QPushButton(tr("settings.permissions.request_accessibility"))
        self.request_accessibility_button.clicked.connect(self._request_accessibility_from_parent)
        self.request_camera_button = QPushButton(tr("settings.permissions.request_camera"))
        self.request_camera_button.clicked.connect(self._request_camera_from_parent)
        self.request_input_monitoring_button = QPushButton(
            tr("settings.permissions.request_input_monitoring")
        )
        self.request_input_monitoring_button.clicked.connect(self._request_input_monitoring_from_parent)
        # Stacked full-width buttons read as banners; keep them at their natural
        # width so the page has one visual rank instead of three competing bars.
        requests_row = QHBoxLayout()
        for button in (
            self.request_accessibility_button,
            self.request_camera_button,
            self.request_input_monitoring_button,
        ):
            requests_row.addWidget(button)
        requests_row.addStretch()
        layout.addLayout(requests_row)
        self.recheck_permissions_button = QPushButton(tr("settings.permissions.recheck"))
        self.recheck_permissions_button.clicked.connect(self._recheck_permissions)
        recheck_row = QHBoxLayout()
        recheck_row.addWidget(self.recheck_permissions_button)
        recheck_row.addStretch()
        layout.addLayout(recheck_row)
        # Apple grants these two only to a freshly launched process; saying so
        # here is cheaper than letting the user conclude the switch did nothing.
        self.restart_hint_label = QLabel(tr("settings.permissions.restart_hint"))
        self.restart_hint_label.setObjectName("hintLabel")
        self.restart_hint_label.setWordWrap(True)
        layout.addWidget(self.restart_hint_label)
        layout.addStretch()
        return widget

    def refresh_permissions(self, provider=None) -> None:
        """Re-read the three authorization states without rebuilding the page."""
        if provider is None:
            parent = self.parent()
            provider = getattr(
                getattr(parent, "platform_services", None), "permission_provider", None
            )
        if provider is None:
            # Detached from a window there is no live provider to ask, and
            # building platform services here would open native panels.
            return
        try:
            snapshot = provider.snapshot()
        except Exception:  # noqa: BLE001 - a status refresh must never fail loudly
            return
        for key, state in (
            ("camera", getattr(snapshot, "camera", None)),
            ("accessibility", getattr(snapshot, "accessibility", None)),
            ("input_monitoring", getattr(snapshot, "input_monitoring", None)),
        ):
            row = self.permission_dots.get(key)
            if row is None:
                continue
            dot, value_label = row
            semantic, value_semantic = self._permission_semantics(state)
            for widget, name in ((dot, semantic), (value_label, value_semantic)):
                widget.setProperty("semantic", name)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            value_label.setText(self._permission_label(state))

    def _recheck_permissions(self, parent=None):
        """Ask the window to re-read the system, then repaint these rows."""
        parent = parent if parent is not None else self.parent()
        refresh = getattr(parent, "_refresh_permission_status", None)
        if callable(refresh):
            refresh()
        provider = getattr(getattr(parent, "platform_services", None), "permission_provider", None)
        self.refresh_permissions(provider)

    def _request_accessibility_from_parent(self):
        parent = self.parent()
        if parent and hasattr(parent, "request_accessibility_permission"):
            parent.request_accessibility_permission()

    def _request_camera_from_parent(self):
        parent = self.parent()
        if parent and hasattr(parent, "request_camera_permission"):
            parent.request_camera_permission()

    def _request_input_monitoring_from_parent(self):
        parent = self.parent()
        if parent and hasattr(parent, "request_input_monitoring_permission"):
            parent.request_input_monitoring_permission()

    def create_combo_tab(self):
        """创建组合动作标签页"""
        from gui.combo_card import ComboCard

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        self.combo_hint_label = QLabel(tr("settings.advanced.combo.description"))
        self.combo_hint_label.setObjectName("hintLabel")
        layout.addWidget(self.combo_hint_label)

        # An unconfigured list used to be a full-height black rectangle, which
        # read as a rendering fault rather than "nothing configured yet".
        self.combo_empty_label = QLabel(tr("settings.advanced.combo.empty"))
        self.combo_empty_label.setObjectName("comboEmpty")
        self.combo_empty_label.setAlignment(Qt.AlignCenter)
        self.combo_empty_label.setWordWrap(True)
        layout.addWidget(self.combo_empty_label, 1)

        # 滚动区域
        scroll = QScrollArea()
        self.combo_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.combo_scroll_content = QWidget()
        self.combo_scroll_layout = QVBoxLayout(self.combo_scroll_content)
        self.combo_scroll_layout.setSpacing(12)

        # 加载已有组合
        combos = self.config.get("gesture_combos") or []
        for combo_cfg in combos:
            self._add_combo_card(combo_cfg)

        self.combo_scroll_layout.addStretch()
        scroll.setWidget(self.combo_scroll_content)
        layout.addWidget(scroll, 1)

        self.combo_add_button = QPushButton(tr("settings.advanced.combo.add"))
        self.combo_add_button.setObjectName("addComboBtn")
        self.combo_add_button.clicked.connect(self._add_new_combo)
        add_row = QHBoxLayout()
        add_row.addWidget(self.combo_add_button)
        add_row.addStretch()
        layout.addLayout(add_row)

        self._refresh_combo_empty_state()
        return widget

    def _refresh_combo_empty_state(self):
        """Show the empty-state copy exactly when no combo card is staged."""
        if not hasattr(self, "combo_empty_label"):
            return
        has_cards = bool(getattr(self, "combo_cards", []))
        self.combo_empty_label.setVisible(not has_cards)
        if hasattr(self, "combo_scroll"):
            self.combo_scroll.setVisible(has_cards)

    def _clear_combo_cards(self):
        """Remove staged cards while retaining the terminal stretch layout item."""
        for card in self.combo_cards:
            self.combo_scroll_layout.removeWidget(card)
            card.deleteLater()
        self.combo_cards.clear()
        self._refresh_combo_empty_state()

    def _add_combo_card(self, settings=None):
        """添加组合卡片"""
        from gui.combo_card import ComboCard

        card = ComboCard()
        if settings:
            card.load_settings(settings)
        card.deleteRequested.connect(self._remove_combo_card)
        self.combo_cards.append(card)
        # 插入到stretch之前
        self.combo_scroll_layout.insertWidget(
            self.combo_scroll_layout.count() - 1, card
        )
        self._refresh_combo_empty_state()

    def _add_new_combo(self):
        """添加新组合"""
        self._add_combo_card()

    def _remove_combo_card(self, card):
        """删除组合卡片"""
        if card in self.combo_cards:
            self.combo_cards.remove(card)
            card.deleteLater()
            self._refresh_combo_empty_state()

    def create_context_rules_tab(self):
        """创建上下文规则标签页 - 配置手势与组件的关系"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        self.context_rules_hint_label = QLabel(tr("settings.advanced.context.description"))
        self.context_rules_hint_label.setObjectName("hintLabel")
        layout.addWidget(self.context_rules_hint_label)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # 组件类型和手势类型
        self.control_types = [
            ("text_input", "settings.advanced.context.control.text_input"),
            ("clickable", "settings.advanced.context.control.clickable"),
            ("slider", "settings.advanced.context.control.slider"),
            ("menu", "settings.advanced.context.control.menu"),
            ("scrollable", "settings.advanced.context.control.scrollable"),
            ("generic", "settings.advanced.context.control.generic"),
        ]
        self.gesture_types = [
            ("point", "gesture.point"),
            ("pinch", "gesture.pinch"),
            ("pinch_hold", "gesture.pinch_hold"),
            ("peace", "gesture.peace"),
            ("thumb_up", "gesture.thumb_up"),
            ("thumb_down", "gesture.thumb_down"),
            ("dynamic_shortcut", "settings.advanced.context.gesture.dynamic_shortcut"),
        ]

        # 存储复选框
        self.context_checkboxes = {}
        self.context_groups = {}

        # 为每个组件类型创建一组复选框
        for ctrl_id, ctrl_key in self.control_types:
            group = QGroupBox(tr(ctrl_key))
            self.context_groups[ctrl_id] = group
            group_layout = QHBoxLayout(group)
            self.context_checkboxes[ctrl_id] = {}

            for gest_id, gesture_key in self.gesture_types:
                cb = QCheckBox(tr(gesture_key))
                self.context_checkboxes[ctrl_id][gest_id] = cb
                group_layout.addWidget(cb)

            group_layout.addStretch()
            scroll_layout.addWidget(group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # 加载配置
        self._load_context_rules()

        return widget

    def _load_context_rules(self):
        """加载上下文规则配置"""
        ctx_cfg = self.config.get("context_aware") or {}
        rules = ctx_cfg.get("control_gestures") or {}

        for ctrl_id, _ in self.control_types:
            allowed = rules.get(ctrl_id, [])
            for gest_id, _ in self.gesture_types:
                cb = self.context_checkboxes[ctrl_id][gest_id]
                cb.setChecked(gest_id in allowed)

    def create_zones_tab(self):
        """创建区域规则标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.zones_info_label = QLabel(tr("settings.advanced.zones.description"))
        self.zones_info_label.setWordWrap(True)
        layout.addWidget(self.zones_info_label)

        # 区域列表
        self.zones_list = QVBoxLayout()
        layout.addLayout(self.zones_list)

        # 加载现有规则
        self._load_zone_rules()

        self.zones_add_button = QPushButton(tr("settings.advanced.zones.add"))
        self.zones_add_button.clicked.connect(self._add_zone_rule)
        zones_add_row = QHBoxLayout()
        zones_add_row.addWidget(self.zones_add_button)
        zones_add_row.addStretch()
        layout.addLayout(zones_add_row)

        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def create_global_tab(self):
        """创建全局设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        # Cards must not run into the scrollbar or the tab frame.
        layout.setContentsMargins(4, 12, 14, 16)
        layout.setSpacing(4)

        self.global_mouse_group = QGroupBox(tr("settings.advanced.global.mouse"))
        form1 = styled_form(self.global_mouse_group)

        self.scroll_speed = QSlider(Qt.Horizontal)
        self.scroll_speed.setRange(10, 100)
        self.scroll_speed_label = QLabel(tr("settings.advanced.global.scroll_speed"))
        slider_row(form1, self.scroll_speed_label, self.scroll_speed, lambda v: f"{v}")

        self.smoothing = QSlider(Qt.Horizontal)
        self.smoothing.setRange(1, 20)
        self.smoothing_label = QLabel(tr("settings.advanced.global.smoothing"))
        # Stored as value()/1000, so show the real unit rather than the tick.
        slider_row(form1, self.smoothing_label, self.smoothing, lambda v: f"{v / 1000:.3f}")

        # The dial that actually stops the cursor shaking. 0 turns it off, which
        # is the right answer for drawing but not for pointing at buttons.
        self.dead_zone = QSlider(Qt.Horizontal)
        self.dead_zone.setRange(0, 16)
        self.dead_zone_label = QLabel(tr("settings.advanced.global.dead_zone"))
        self.dead_zone_hint = QLabel(tr("settings.advanced.global.dead_zone_hint"))
        self.dead_zone_hint.setObjectName("hintLabel")
        self.dead_zone_hint.setWordWrap(True)
        slider_row(
            form1, self.dead_zone_label, self.dead_zone,
            lambda v: tr("settings.advanced.global.dead_zone_off") if v == 0 else f"{v} px",
        )
        form1.addRow("", self.dead_zone_hint)

        layout.addWidget(self.global_mouse_group)

        self.global_detection_group = QGroupBox(tr("settings.advanced.global.detection"))
        form2 = styled_form(self.global_detection_group)

        self.detection_conf = QSlider(Qt.Horizontal)
        self.detection_conf.setRange(30, 95)
        self.detection_conf_label = QLabel(tr("settings.advanced.global.confidence"))
        slider_row(form2, self.detection_conf_label, self.detection_conf, lambda v: f"{v}{tr('common.unit.percent')}")

        self.tracking_conf = QSlider(Qt.Horizontal)
        self.tracking_conf.setRange(30, 95)
        self.tracking_conf_label = QLabel(tr("settings.advanced.global.tracking_confidence"))
        slider_row(form2, self.tracking_conf_label, self.tracking_conf, lambda v: f"{v}{tr('common.unit.percent')}")

        layout.addWidget(self.global_detection_group)

        self.global_stabilization_group = QGroupBox(tr("settings.advanced.global.stabilization"))
        form3 = styled_form(self.global_stabilization_group)

        self.confirm_threshold = QSlider(Qt.Horizontal)
        self.confirm_threshold.setRange(1, 5)
        self.confirm_threshold_label = QLabel(tr("settings.advanced.global.confirm_frames"))
        slider_row(form3, self.confirm_threshold_label, self.confirm_threshold, lambda v: f"{v}{tr('common.unit.frames')}")

        self.min_switch_interval = QSlider(Qt.Horizontal)
        self.min_switch_interval.setRange(5, 30)
        self.min_switch_interval_label = QLabel(tr("settings.advanced.global.switch_interval"))
        slider_row(form3, self.min_switch_interval_label, self.min_switch_interval, lambda v: f"{v * 10} ms")

        layout.addWidget(self.global_stabilization_group)

        self.global_context_group = QGroupBox(tr("settings.advanced.global.context"))
        form4 = styled_form(self.global_context_group)

        self.context_aware_check = ToggleSwitch(tr("settings.advanced.global.context_aware"))
        self.context_aware_label = QLabel()
        self.context_aware_label.setVisible(False)
        self.global_context_hint_label = QLabel(tr("settings.advanced.global.context_description"))
        self.global_context_hint_label.setObjectName("hintLabel")
        self.global_context_hint_label.setWordWrap(True)
        form4.addRow(self.context_aware_check)
        form4.addRow("", self.global_context_hint_label)
        self.intent_actions_check = ToggleSwitch(tr("settings.advanced.global.intent_enabled"))
        self.intent_actions_label = QLabel()
        self.intent_actions_label.setVisible(False)
        self.intent_hint_label = QLabel(tr("settings.advanced.global.intent_description"))
        self.intent_hint_label.setObjectName("hintLabel")
        self.intent_hint_label.setWordWrap(True)
        form4.addRow(self.intent_actions_check)
        form4.addRow("", self.intent_hint_label)

        layout.addWidget(self.global_context_group)

        self.telemetry_group = QGroupBox(tr("settings.advanced.global.telemetry"))
        telemetry_form = styled_form(self.telemetry_group)
        self.telemetry_check = ToggleSwitch(tr("settings.advanced.global.telemetry_enabled"))
        self.telemetry_label = QLabel()
        self.telemetry_label.setVisible(False)
        self.telemetry_hint_label = QLabel(tr("settings.advanced.global.telemetry_description"))
        self.telemetry_hint_label.setObjectName("hintLabel")
        self.telemetry_hint_label.setWordWrap(True)
        self.purge_telemetry_button = QPushButton(tr("settings.advanced.global.telemetry_purge"))
        self.purge_telemetry_button.clicked.connect(self._purge_telemetry)
        telemetry_form.addRow(self.telemetry_check)
        telemetry_form.addRow("", self.telemetry_hint_label)
        # What the adaptor currently believes, read straight from the config it
        # wrote — the same numbers the TargetModel was built with.
        self.assist_learned_label = QLabel(self._assist_learned_text())
        self.assist_learned_label.setObjectName("hintLabel")
        self.assist_learned_label.setWordWrap(True)
        telemetry_form.addRow("", self.assist_learned_label)
        # A button placed straight into a form row stretches to the panel width
        # and reads as a banner; keep it the size of a normal control.
        purge_row = QHBoxLayout()
        purge_row.addWidget(self.purge_telemetry_button)
        purge_row.addStretch()
        telemetry_form.addRow("", purge_row)
        layout.addWidget(self.telemetry_group)

        # 加载全局设置
        self.load_global_settings()

        layout.addStretch()
        # The combo and context tabs scroll; this one did not, so a short window
        # sliced the last group mid-row with no way to reach it.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _assist_learned_text(self) -> str:
        """Describe the adapted aim-assist values, or why there are none yet.

        The values come from `pointer_assist.learned`, which only the tuner
        writes after a real decision; an empty payload means the configured
        numbers are still in force.
        """
        assist = self.config.get("pointer_assist") or {}
        learned = assist.get("learned")
        learned = learned if isinstance(learned, dict) else {}
        if not learned:
            return tr("settings.advanced.global.assist_learned_empty")
        raw_distance = learned.get("max_snap_distance")
        raw_confidence = learned.get("min_confidence")
        if raw_distance is None or raw_confidence is None:
            return tr("settings.advanced.global.assist_learned_empty")
        try:
            distance = float(raw_distance)
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            return tr("settings.advanced.global.assist_learned_empty")
        clicks = learned.get("clicks")
        clicks = int(clicks) if isinstance(clicks, int) and not isinstance(clicks, bool) else 0
        return tr(
            "settings.advanced.global.assist_learned",
            distance=f"{distance:g}",
            confidence=f"{confidence:.2f}",
            clicks=clicks,
        )

    def _purge_telemetry(self):
        """Erase the local event log after an explicit confirmation."""
        answer = QMessageBox.question(
            self,
            tr("settings.advanced.global.telemetry_purge"),
            tr("settings.advanced.global.telemetry_purge_confirm"),
        )
        if answer != QMessageBox.Yes:
            return
        from core.telemetry import TelemetryStore, default_path

        store = TelemetryStore(default_path(self.config.config_path), enabled=True)
        store.purge()
        store.close()
        self.purge_telemetry_button.setText(tr("settings.advanced.global.telemetry_purged"))

    def _create_diagnostics_tab(self):
        """Add the read-only statistics page and refresh it when selected."""
        from core.telemetry import default_path
        from .diagnostics_page import DiagnosticsPage

        page = DiagnosticsPage(default_path(self.config.config_path))
        self.advanced_tabs.addTab(page, tr("settings.advanced.tab.stats"))
        self.advanced_tabs.currentChanged.connect(
            lambda index: page.refresh() if self.advanced_tabs.widget(index) is page else None
        )
        return page

    def load_global_settings(self):
        """Load only settings backed by the current MediaPipe control path."""
        sensitivity = self.config.get("global_sensitivity") or {}
        self.scroll_speed.setValue(sensitivity.get("scroll_speed", 50))
        self.smoothing.setValue(round(float(sensitivity.get("smoothing", 0.005)) * 1000))
        self.dead_zone.setValue(int(float(sensitivity.get("dead_zone", 8.0))))

        detection = self.config.get("detection") or {}
        self.detection_conf.setValue(round(float(detection.get("confidence", 0.7)) * 100))
        self.tracking_conf.setValue(round(float(detection.get("tracking_confidence", 0.5)) * 100))

        # 稳定化参数
        stab = self.config.get("stabilization") or {}
        self.confirm_threshold.setValue(stab.get("confirm_threshold", 2))
        self.min_switch_interval.setValue(round(float(stab.get("min_switch_interval", 0.1)) * 100))

        # 上下文感知
        telemetry = self.config.get("telemetry") or {}
        self.telemetry_check.setChecked(telemetry.get("enabled", False) is True)

        ctx = self.config.get("context_aware") or {}
        self.context_aware_check.setChecked(ctx.get("enabled", True))
        self.intent_actions_check.setChecked(ctx.get("intent_actions_enabled", True))

    def _load_zone_rules(self):
        """加载区域规则"""
        rules = self.config.get("zone_rules") or []
        for rule in rules:
            if rule is not None:
                self._create_zone_widget(rule)

    def _add_zone_rule(self):
        """添加新区域规则"""
        rule = {'x': 0, 'y': 0, 'w': 100, 'h': 100, 'allowed': ['click']}
        self._create_zone_widget(rule)

    def _create_zone_widget(self, rule):
        """创建区域规则控件"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(frame)

        # 位置输入
        # Coordinates are global screen points, and a display placed left of or
        # above the main one has a negative origin. Clamping to 0 moved such a
        # zone onto the primary display the moment the page was opened, and the
        # next Save persisted the moved copy.
        x_spin = QSpinBox()
        x_spin.setRange(-32768, 32767)
        x_spin.setValue(int(rule.get('x', 0)))
        y_spin = QSpinBox()
        y_spin.setRange(-32768, 32767)
        y_spin.setValue(int(rule.get('y', 0)))
        w_spin = QSpinBox()
        w_spin.setRange(1, 32767)
        w_spin.setValue(int(rule.get('w', 100)))
        h_spin = QSpinBox()
        h_spin.setRange(1, 32767)
        h_spin.setValue(int(rule.get('h', 100)))

        x_label = QLabel(tr("settings.advanced.zones.x"))
        y_label = QLabel(tr("settings.advanced.zones.y"))
        width_label = QLabel(tr("settings.advanced.zones.width"))
        height_label = QLabel(tr("settings.advanced.zones.height"))
        layout.addWidget(x_label)
        layout.addWidget(x_spin)
        layout.addWidget(y_label)
        layout.addWidget(y_spin)
        layout.addWidget(width_label)
        layout.addWidget(w_spin)
        layout.addWidget(height_label)
        layout.addWidget(h_spin)

        click_cb = QCheckBox(tr("settings.advanced.zones.click"))
        click_cb.setChecked('click' in rule.get('allowed', []))
        drag_cb = QCheckBox(tr("settings.advanced.zones.drag"))
        drag_cb.setChecked('drag' in rule.get('allowed', []))
        layout.addWidget(click_cb)
        layout.addWidget(drag_cb)

        del_btn = QPushButton(tr("settings.advanced.zones.delete"))
        del_btn.clicked.connect(lambda: self._remove_zone(frame))
        layout.addWidget(del_btn)

        frame.zone_data = {
            'x': x_spin, 'y': y_spin, 'w': w_spin, 'h': h_spin,
            'click': click_cb, 'drag': drag_cb,
            'x_label': x_label, 'y_label': y_label,
            'width_label': width_label, 'height_label': height_label,
            'delete_button': del_btn,
        }

        self.zones_list.addWidget(frame)

    def _remove_zone(self, frame):
        """删除区域规则"""
        self.zones_list.removeWidget(frame)
        frame.deleteLater()

    def _get_context_rules(self):
        """获取上下文规则配置"""
        rules = {}
        for ctrl_id, _ in self.control_types:
            allowed = []
            for gest_id, _ in self.gesture_types:
                cb = self.context_checkboxes[ctrl_id][gest_id]
                if cb.isChecked():
                    allowed.append(gest_id)
            rules[ctrl_id] = allowed
        return rules

    def _get_zone_rules(self):
        """获取所有区域规则"""
        rules = []
        for i in range(self.zones_list.count()):
            item = self.zones_list.itemAt(i)
            if item and item.widget():
                frame = item.widget()
                if hasattr(frame, 'zone_data'):
                    d = frame.zone_data
                    allowed = []
                    if d['click'].isChecked():
                        allowed.append('click')
                    if d['drag'].isChecked():
                        allowed.append('drag')
                    rules.append({
                        'x': d['x'].value(),
                        'y': d['y'].value(),
                        'w': d['w'].value(),
                        'h': d['h'].value(),
                        'allowed': allowed
                    })
        return rules

    def save_settings(self):
        """保存设置"""
        # A combination carrying an unusable shortcut used to be dropped by the
        # normalizer, so saving silently deleted work the user had just done.
        # Refuse the save and point at the card instead.
        for card in self.combo_cards:
            if not card.hotkey_is_valid():
                card.refresh_hotkey_validity()
                card.setFocus()
                return
        # Locale selection remains staged until this explicit Save action.
        self.config.set("ui", "language", self.language_combo.currentData())

        # Global controls backed by the live pointer path.
        self.config.set("global_sensitivity", "scroll_speed", self.scroll_speed.value())
        self.config.set("global_sensitivity", "smoothing", self.smoothing.value() / 1000)
        self.config.set("global_sensitivity", "dead_zone", float(self.dead_zone.value()))

        # MediaPipe is the sole supported landmark provider.
        self.config.set("detection", "detector_type", "mediapipe")
        self.config.set("detection", "confidence", self.detection_conf.value() / 100)
        self.config.set("detection", "tracking_confidence", self.tracking_conf.value() / 100)

        # 稳定化参数
        self.config.set("stabilization", "confirm_threshold", self.confirm_threshold.value())
        self.config.set("stabilization", "min_switch_interval", self.min_switch_interval.value() / 100)

        # 上下文感知
        self.config.set("context_aware", "enabled", self.context_aware_check.isChecked())
        self.config.set("telemetry", "enabled", self.telemetry_check.isChecked())
        self.config.set("context_aware", "intent_actions_enabled", self.intent_actions_check.isChecked())

        # 上下文规则
        control_gestures = self._get_context_rules()
        self.config.set("context_aware", "control_gestures", control_gestures)

        # 区域规则
        zone_rules = self._get_zone_rules()
        self.config.set("zone_rules", None, zone_rules)

        # Control-session settings stay staged until the user presses Save.
        self.config.set("control_session", "mode", self.session_mode.currentData())
        activation_template_id = self._selected_template_id(self.activation_gesture)
        exit_template_id = self._selected_template_id(self.exit_gesture)
        self.config.set("control_session", "activation_template_id", activation_template_id)
        self.config.set("control_session", "exit_template_id", exit_template_id)
        self.config.set(
            "control_session",
            "activation_gesture",
            self._activation_builtin_gesture if activation_template_id else self.activation_gesture.currentData(),
        )
        self.config.set(
            "control_session",
            "exit_gesture",
            self._exit_builtin_gesture if exit_template_id else self.exit_gesture.currentData(),
        )
        self.config.set("control_session", "hold_shortcut", self.hold_shortcut.text().strip())
        self.config.set("pointer_assist", "enabled", self.point_assist_check.isChecked())
        self.config.set("pointer_assist", "mode", self.assist_mode.currentData())
        self.config.set("pointer_mapping", "mode", self.mapping_mode.currentData())
        self.config.set("performance", "mode", self.performance_mode.currentData())
        self.config.set("pointer_mapping", "gain", round(float(self.mapping_gain.value()), 2))
        self.config.set(
            "control_session", "custom_static_templates", deepcopy(self._staged_static_templates)
        )
        self.config.set(
            "control_session", "stability_seconds", self.stability_seconds.value() / 1000
        )
        self.config.set(
            "control_session", "no_hand_timeout_seconds", self.no_hand_timeout_seconds.value()
        )

        # Persist stable camera identity and resolution from the Camera page.
        self.camera_page.apply_to_config()
        self.feedback_page.apply_to_config()

        # Persist compact gesture list selections.
        self.gesture_page.apply_to_config(self.config)
        self.dynamic_gesture_page.apply_to_config()

        # A calibration measured during this dialog is committed only here.
        self._apply_calibration_stage()

        # Persist normalized shortcut combinations now, rather than leaving
        # malformed legacy entries alive until a later ConfigManager.save().
        from utils.config_manager import normalize_gesture_combos
        self.config.config["gesture_combos"] = normalize_gesture_combos(
            [card.get_settings() for card in self.combo_cards]
        )

        self.accept()

    def reset_defaults(self):
        """恢复默认设置"""
        from utils.config_manager import DEFAULT_CONFIG

        # Reset visible state only; persistence remains explicit through Save.
        control = DEFAULT_CONFIG.get("control_session", {})
        self.session_mode.setCurrentIndex(max(self.session_mode.findData(control.get("mode", "gesture")), 0))
        self._staged_static_templates = []
        self._remove_custom_trigger_options()
        self._activation_builtin_gesture = control.get("activation_gesture", "open_hand")
        self._exit_builtin_gesture = control.get("exit_gesture", "fist")
        self.activation_gesture.setCurrentIndex(max(self.activation_gesture.findData(self._activation_builtin_gesture), 0))
        self.exit_gesture.setCurrentIndex(max(self.exit_gesture.findData(self._exit_builtin_gesture), 0))
        self.hold_shortcut.setText(control.get("hold_shortcut", ""))
        self.stability_seconds.setValue(round(control.get("stability_seconds", 0.3) * 1000))
        self.no_hand_timeout_seconds.setValue(round(control.get("no_hand_timeout_seconds", 2.0)))
        self.custom_triggers_summary.setText(self._custom_trigger_summary())

        camera = DEFAULT_CONFIG.get("camera", {})
        self.camera_page.selected_device_id = camera.get("device_id", "")
        self.camera_page.width_input.setValue(camera.get("width", 640))
        self.camera_page.height_input.setValue(camera.get("height", 480))
        self.camera_page._refresh_selected_status()

        feedback = DEFAULT_CONFIG.get("feedback", {})
        self.feedback_page.mode_combo.setCurrentIndex(max(self.feedback_page.mode_combo.findData(feedback.get("mode", "standard")), 0))
        self.feedback_page.opacity_input.setValue(round(feedback.get("opacity", 0.92) * 100))
        self.feedback_page.scale_input.setValue(round(feedback.get("scale", 1.0) * 100))

        # Reset every visible advanced setting locally; Save remains the only
        # persistence boundary.
        self.language_combo.setCurrentIndex(
            max(self.language_combo.findData(DEFAULT_CONFIG.get("ui", {}).get("language", DEFAULT_LOCALE)), 0)
        )
        sens = DEFAULT_CONFIG.get("global_sensitivity", {})
        self.scroll_speed.setValue(sens.get("scroll_speed", 50))
        self.smoothing.setValue(round(float(sens.get("smoothing", 0.005)) * 1000))
        self.dead_zone.setValue(int(float(sens.get("dead_zone", 8.0))))
        detection = DEFAULT_CONFIG.get("detection", {})
        self.detection_conf.setValue(round(float(detection.get("confidence", 0.7)) * 100))
        self.tracking_conf.setValue(round(float(detection.get("tracking_confidence", 0.5)) * 100))
        stabilization = DEFAULT_CONFIG.get("stabilization", {})
        self.confirm_threshold.setValue(stabilization.get("confirm_threshold", 2))
        self.min_switch_interval.setValue(round(float(stabilization.get("min_switch_interval", 0.1)) * 100))

        telemetry = DEFAULT_CONFIG.get("telemetry", {})
        self.telemetry_check.setChecked(telemetry.get("enabled", False) is True)

        context = DEFAULT_CONFIG.get("context_aware", {})
        self.context_aware_check.setChecked(context.get("enabled", True))
        self.intent_actions_check.setChecked(context.get("intent_actions_enabled", True))
        context_rules = context.get("control_gestures", {})
        for control_id, _ in self.control_types:
            allowed = context_rules.get(control_id, [])
            for gesture_id, _ in self.gesture_types:
                self.context_checkboxes[control_id][gesture_id].setChecked(gesture_id in allowed)

        while self.zones_list.count():
            item = self.zones_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for rule in DEFAULT_CONFIG.get("zone_rules", []):
            self._create_zone_widget(rule)

        self._clear_combo_cards()
        for combo in DEFAULT_CONFIG.get("gesture_combos", []):
            self._add_combo_card(combo)
        self.dynamic_gesture_page.reset_defaults()

        # Reset compact gesture rows (the legacy card collection is no longer rendered).
        gestures = DEFAULT_CONFIG.get("gestures", {})
        for gesture_id, (enabled, action) in self.gesture_page.rows.items():
            gesture = deepcopy(gestures.get(gesture_id, {}))
            self.gesture_page.gestures[gesture_id] = gesture
            idx = action.findData(gesture.get("action", "none"))
            supported = idx >= 0 and action.model().item(idx).isEnabled()
            enabled.setChecked(gesture.get("enabled", True) and supported)
            action.setCurrentIndex(idx if supported else max(action.findData("none"), 0))

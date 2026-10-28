"""Staged dynamic shortcut controls embedded in the existing Gestures surface."""

from copy import deepcopy

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gui.controls import ToggleSwitch
from gui.i18n import tr
from .dynamic_gesture_record_dialog import DynamicGestureRecordDialog
from utils.config_manager import normalize_dynamic_gestures


class DynamicGestureSettingsPage(QWidget):
    ACTIONS = (
        ("Scroll up", "scroll_up"),
        ("Scroll down", "scroll_down"),
        ("Custom shortcut", "custom_hotkey"),
    )
    ACTION_KEYS = {
        "scroll_up": "settings.dynamic.action.scroll_up",
        "scroll_down": "settings.dynamic.action.scroll_down",
        "custom_hotkey": "settings.dynamic.action.custom_hotkey",
    }

    def __init__(self, config, parent=None, camera_service=None):
        super().__init__(parent)
        self.config = config
        self.camera_service = camera_service
        self._staged = deepcopy(normalize_dynamic_gestures(config.get("dynamic_gestures")))
        layout = QVBoxLayout(self)
        self.title_label = QLabel()
        # This page is embedded inside Gestures: a page-level title here makes
        # two headings of equal weight compete on one screen.
        self.title_label.setObjectName("sectionTitle")
        self.hint_label = QLabel()
        self.hint_label.setObjectName("hintLabel")
        self.hint_label.setWordWrap(True)
        # A whole feature on/off: a switch says "flip this", a checkbox
        # reads as "pick this one from a set".
        self.enabled_check = ToggleSwitch()
        self.enabled_check.setChecked(self._staged["enabled"])
        self.action_selector = QComboBox()
        for action, key in self.ACTION_KEYS.items():
            self.action_selector.addItem(tr(key), action)
        self.record_button = QPushButton()
        self.record_button.clicked.connect(self.open_recording)
        self.list_label = QLabel()
        self.list_label.setObjectName("hintLabel")
        self.templates_layout = QVBoxLayout()
        self.templates_layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.enabled_check)
        selector_row = QHBoxLayout()
        selector_row.addWidget(self.action_selector)
        selector_row.addStretch()
        layout.addLayout(selector_row)
        record_row = QHBoxLayout()
        record_row.addWidget(self.record_button)
        record_row.addStretch()
        layout.addLayout(record_row)
        layout.addWidget(self.list_label)
        layout.addLayout(self.templates_layout)
        self.retranslate_ui()

    @property
    def staged_templates(self):
        return deepcopy(self._staged["templates"])

    def stage_add(self, record):
        safe = normalize_dynamic_gestures({
            "enabled": self._staged["enabled"],
            "defaults": self._staged["defaults"],
            "templates": [record],
        })["templates"]
        if safe:
            self._staged["templates"] = [
                item for item in self._staged["templates"]
                if item["template_id"] != safe[0]["template_id"]
            ] + safe
        self._refresh()

    def stage_delete(self, template_id):
        self._staged["templates"] = [
            item for item in self._staged["templates"] if item["template_id"] != template_id
        ]
        self._refresh()

    def apply_to_config(self):
        self._staged["enabled"] = self.enabled_check.isChecked()
        self.config.set("dynamic_gestures", None, normalize_dynamic_gestures(self._staged))

    def reset_defaults(self):
        """Reset only staged dynamic settings; Settings Save remains the commit boundary."""
        from utils.config_manager import DEFAULT_CONFIG

        self._staged = deepcopy(normalize_dynamic_gestures(DEFAULT_CONFIG.get("dynamic_gestures")))
        self.enabled_check.setChecked(self._staged["enabled"])
        self._refresh()

    def open_recording(self):
        dialog = DynamicGestureRecordDialog(parent=self)
        selected_action = self.action_selector.currentData()
        dialog.action_selector.setCurrentIndex(
            max(dialog.action_selector.findData(selected_action), 0)
        )
        worker = self._start_recording_worker(dialog)
        try:
            if dialog.exec() and dialog.saved_record is not None:
                self.stage_add(dialog.saved_record)
        finally:
            self._cleanup_recording_worker(worker, dialog)

    def _start_recording_worker(self, dialog):
        """Use an isolated capture/detector lifecycle, never the live control worker."""
        from core.detector_factory import create_detector
        from core.mediapipe_worker import MediaPipeVideoWorker
        from platform_services.camera_selection import open_configured_camera
        from utils.camera_utils import open_camera

        camera = self.config.get("camera") or {}
        detection = self.config.get("detection") or {}
        detector = create_detector(
            "mediapipe",
            detection.get("confidence", 0.7),
            detection.get("tracking_confidence", 0.5),
        )
        capture = open_configured_camera(camera, self.camera_service, legacy_open=open_camera)
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            detector.release()
            dialog.preview.setText(tr("settings.dynamic.camera_open_failed"))
            dialog.state = dialog.state.FAILED
            dialog._refresh()
            return None
        dialog.recording_detector = detector
        worker = MediaPipeVideoWorker(
            camera_id=camera.get("id", 0), width=camera.get("width", 640), height=camera.get("height", 480),
            detector=detector, capture=capture, parent=dialog,
        )
        worker.landmark_frame_ready.connect(dialog.accept_landmark_frame)
        worker.worker_error.connect(
            lambda _message: dialog.preview.setText(tr("settings.dynamic.camera_open_failed"))
        )
        worker.start()
        return worker

    @staticmethod
    def _cleanup_recording_worker(worker, dialog):
        try:
            if worker is not None:
                worker.stop()
                worker.wait(2000)
                worker.deleteLater()
        finally:
            detector = getattr(dialog, "recording_detector", None)
            if detector is not None:
                detector.release()

    def retranslate_ui(self):
        """Refresh static copy without mutating staged templates or action IDs."""
        selected_action = self.action_selector.currentData()
        self.title_label.setText(tr("settings.dynamic.title"))
        self.hint_label.setText(tr("settings.dynamic.description"))
        self.enabled_check.setText(tr("settings.dynamic.enable"))
        self.record_button.setText(tr("settings.dynamic.record"))
        for action, key in self.ACTION_KEYS.items():
            index = self.action_selector.findData(action)
            self.action_selector.setItemText(index, tr(key))
        self.action_selector.setCurrentIndex(max(self.action_selector.findData(selected_action), 0))
        self._refresh()

    @classmethod
    def _action_label(cls, action):
        return tr(cls.ACTION_KEYS.get(action, "settings.dynamic.action.unavailable"))

    def _refresh(self):
        names = ", ".join(item["name"] for item in self._staged["templates"])
        self.list_label.setText(names or tr("settings.dynamic.empty"))
        while self.templates_layout.count():
            item = self.templates_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for template in self._staged["templates"]:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(
                QLabel(
                    tr(
                        "settings.dynamic.template_row",
                        template_name=template["name"],
                        action=self._action_label(template["action"]),
                    )
                ),
                1,
            )
            delete_button = QPushButton(tr("settings.dynamic.delete"))
            delete_button.clicked.connect(
                lambda _checked=False, template_id=template["template_id"]: self.stage_delete(template_id)
            )
            layout.addWidget(delete_button)
            self.templates_layout.addWidget(row)

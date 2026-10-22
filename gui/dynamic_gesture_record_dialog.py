"""Dedicated, opt-in dynamic gesture recording dialog."""

from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout
)

from gui.i18n import tr
from gui.theme import use_styled_background
from core.dynamic_gesture_template import DynamicGestureMatcher
from utils.hotkey_validation import normalize_hotkey


class DynamicRecordingState(StrEnum):
    READY = "ready"
    RECORDING = "recording"
    TAKE_READY = "take_ready"
    SAVED = "saved"
    FAILED = "failed"


class DynamicGestureRecordDialog(QDialog):
    """Collect landmark-only dynamic takes; worker ownership stays with Settings."""

    ACTIONS = (("Scroll up", "scroll_up"), ("Scroll down", "scroll_down"), ("Custom shortcut", "custom_hotkey"))

    def __init__(self, *, matcher=None, matcher_kwargs=None, parent=None):
        super().__init__(parent)
        use_styled_background(self)
        self.matcher = matcher or DynamicGestureMatcher(**(matcher_kwargs or {}))
        self.takes = []
        self.current_take = []
        self.saved_template = None
        self.saved_record = None
        self.state = DynamicRecordingState.READY
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setObjectName("settingsPageTitle")
        self.status = QLabel()
        self.status.setObjectName("hintLabel")
        # Labels default to a Preferred vertical policy, so a taller dialog
        # stretches every one of them and the text floats in an empty box. Pin
        # them and let the preview absorb the extra height instead.
        for label in (self.title_label, self.status):
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.preview = QLabel()
        self.preview.setObjectName("recordingPreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.name_input = QLineEdit()
        self.action_selector = QComboBox()
        for key, action in (
            ("settings.dynamic_trigger.action.scroll_up", "scroll_up"),
            ("settings.dynamic_trigger.action.scroll_down", "scroll_down"),
            ("settings.dynamic_trigger.action.custom_hotkey", "custom_hotkey"),
        ):
            self.action_selector.addItem(tr(key), action)
        self.context_selector = QComboBox()
        for key, category in (
            ("settings.dynamic_trigger.context.anywhere", ""),
            ("settings.dynamic_trigger.context.clickable", "clickable"),
            ("settings.dynamic_trigger.context.scrollable", "scrollable"),
            ("settings.dynamic_trigger.context.text_input", "text_input"),
        ):
            self.context_selector.addItem(tr(key), category)
        self.hotkey_input = QLineEdit()
        self.action_selector.currentIndexChanged.connect(self._refresh)
        self.record_button = QPushButton()
        self.finish_button = QPushButton()
        self.retry_button = QPushButton()
        self.add_take_button = QPushButton()
        self.save_button = QPushButton()
        self.record_button.clicked.connect(self.start_recording)
        self.finish_button.clicked.connect(self.finish_recording)
        self.retry_button.clicked.connect(self.retry_current_take)
        self.add_take_button.clicked.connect(self.accept_current_take)
        self.save_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        for button in (self.record_button, self.finish_button, self.retry_button, self.add_take_button):
            row.addWidget(button)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status)
        layout.addWidget(self.preview)
        layout.addWidget(self.name_input)
        layout.addWidget(self.action_selector)
        layout.addWidget(self.context_selector)
        layout.addWidget(self.hotkey_input)
        layout.addLayout(row)
        layout.addWidget(self.save_button)
        self.retranslate_ui()

    @property
    def take_count(self):
        return len(self.takes)

    @property
    def current_frame_count(self):
        return len(self.current_take)

    def _normalized_hotkey(self):
        """Return a safe canonical custom shortcut, or None when invalid."""
        if self.action_selector.currentData() != "custom_hotkey":
            return ""
        try:
            return normalize_hotkey(self.hotkey_input.text())
        except ValueError:
            return None

    @property
    def can_save(self):
        if not self.takes or not self.name_input.text().strip():
            return False
        return self._normalized_hotkey() is not None

    def start_recording(self):
        if self.state is DynamicRecordingState.SAVED:
            return
        self.current_take.clear()
        self.state = DynamicRecordingState.RECORDING
        self._refresh()

    def accept_landmarks(self, landmarks):
        if self.state is not DynamicRecordingState.RECORDING:
            return
        if self.matcher.normalize_frame(landmarks) is None:
            self.state = DynamicRecordingState.FAILED
        else:
            self.current_take.append(landmarks)
            if len(self.current_take) >= self.matcher.max_recording_frames:
                self._finish_current_take()
        self._refresh()

    def accept_landmark_frame(self, landmark_frame):
        """Show a transient preview but retain only landmarks in the recording state."""
        frame = landmark_frame.frame
        if frame is not None:
            height, width, channels = frame.shape
            image = QImage(frame.data, width, height, channels * width, QImage.Format_BGR888)
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.FastTransformation))
        else:
            self.preview.setText(tr("settings.dynamic_trigger.capturing"))
        self.accept_landmarks(landmark_frame.landmarks)

    def finish_recording(self):
        """Explicitly finish a take after the user completes the motion."""
        if self.state is DynamicRecordingState.RECORDING:
            self._finish_current_take()

    def _finish_current_take(self):
        if self.matcher.prepare_recording(self.current_take) is None:
            self.state = DynamicRecordingState.FAILED
        else:
            self.state = DynamicRecordingState.TAKE_READY
        self._refresh()

    def accept_current_take(self):
        if self.state is not DynamicRecordingState.TAKE_READY:
            return False
        self.takes.append(list(self.current_take))
        self.current_take.clear()
        self.state = DynamicRecordingState.READY
        self._refresh()
        return True

    def retry_current_take(self):
        self.current_take.clear()
        if self.state is not DynamicRecordingState.SAVED:
            self.state = DynamicRecordingState.READY
        self._refresh()

    def confirm_template(self):
        if self.saved_template is not None:
            return self.saved_template
        if self.state is DynamicRecordingState.TAKE_READY:
            self.accept_current_take()
        normalized_hotkey = self._normalized_hotkey()
        if not self.can_save or normalized_hotkey is None:
            return None
        action = self.action_selector.currentData()
        prepared = [
            prepared_take
            for take in self.takes
            if (prepared_take := self.matcher.prepare_recording(take)) is not None
        ]
        suggested = self.matcher.suggest_threshold(prepared)
        template = self.matcher.create_template(
            self.name_input.text().strip(),
            action,
            self.takes,
            threshold=suggested if suggested is not None else 0.18,
            context_category=self.context_selector.currentData() or "",
        )
        if template is None:
            self.state = DynamicRecordingState.FAILED
            self._refresh()
            return None
        self.saved_template = template
        self.saved_record = {
            "template_id": template.template_id,
            "name": template.name,
            "action": template.action,
            "hotkey": normalized_hotkey,
            "samples": [[list(frame) for frame in sample] for sample in template.samples],
            "threshold": template.threshold,
            "cooldown_seconds": template.cooldown_seconds,
            "min_motion_energy": template.min_motion_energy,
            "context_category": template.context_category,
        }
        self.state = DynamicRecordingState.SAVED
        self._refresh()
        return template

    def accept(self):
        if self.confirm_template() is not None:
            super().accept()

    def retranslate_ui(self):
        """Refresh static copy without modifying recorded takes or user input."""
        selected_action = self.action_selector.currentData()
        self.setWindowTitle(tr("settings.dynamic_trigger.title"))
        self.title_label.setText(tr("settings.dynamic_trigger.instruction"))
        if not self.preview.pixmap():
            self.preview.setText(tr("settings.dynamic_trigger.preview_waiting"))
        self.name_input.setPlaceholderText(tr("settings.dynamic_trigger.name_placeholder"))
        self.hotkey_input.setPlaceholderText(tr("settings.dynamic_trigger.hotkey_placeholder"))
        for key, action in (
            ("settings.dynamic_trigger.action.scroll_up", "scroll_up"),
            ("settings.dynamic_trigger.action.scroll_down", "scroll_down"),
            ("settings.dynamic_trigger.action.custom_hotkey", "custom_hotkey"),
        ):
            index = self.action_selector.findData(action)
            self.action_selector.setItemText(index, tr(key))
        self.action_selector.setCurrentIndex(max(self.action_selector.findData(selected_action), 0))
        selected_context = self.context_selector.currentData()
        for key, category in (
            ("settings.dynamic_trigger.context.anywhere", ""),
            ("settings.dynamic_trigger.context.clickable", "clickable"),
            ("settings.dynamic_trigger.context.scrollable", "scrollable"),
            ("settings.dynamic_trigger.context.text_input", "text_input"),
        ):
            index = self.context_selector.findData(category)
            if index >= 0:
                self.context_selector.setItemText(index, tr(key))
        self.context_selector.setCurrentIndex(
            max(self.context_selector.findData(selected_context), 0)
        )
        self.record_button.setText(tr("settings.dynamic_trigger.record"))
        self.finish_button.setText(tr("settings.dynamic_trigger.finish"))
        self.retry_button.setText(tr("settings.dynamic_trigger.retry"))
        self.add_take_button.setText(tr("settings.dynamic_trigger.keep_take"))
        self.save_button.setText(tr("settings.dynamic_trigger.save"))
        self._refresh()

    def _refresh(self):
        recording = self.state is DynamicRecordingState.RECORDING
        take_ready = self.state is DynamicRecordingState.TAKE_READY
        custom = self.action_selector.currentData() == "custom_hotkey"
        self.hotkey_input.setVisible(custom)
        self.record_button.setEnabled(not recording and self.state is not DynamicRecordingState.SAVED)
        self.finish_button.setEnabled(recording and len(self.current_take) >= self.matcher.min_recording_frames)
        self.retry_button.setEnabled(recording or take_ready or self.state is DynamicRecordingState.FAILED)
        self.add_take_button.setEnabled(take_ready)
        self.save_button.setEnabled(self.can_save or take_ready)
        self.status.setText(
            tr(
                "settings.dynamic_trigger.progress",
                take_count=self.take_count,
                current_frame_count=self.current_frame_count,
            )
        )

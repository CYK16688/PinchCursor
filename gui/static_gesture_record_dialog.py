"""Confirmation-based static trigger recording dialog."""

from enum import StrEnum
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout
from gui.i18n import tr
from gui.theme import use_styled_background
from core.static_gesture_template import StaticGestureMatcher


class RecordingState(StrEnum):
    WAITING = "waiting"
    CAPTURING = "capturing"
    READY_TO_CONFIRM = "ready_to_confirm"
    SAVED = "saved"
    FAILED = "failed"


class StaticGestureRecordDialog(QDialog):
    def __init__(self, required_frames=12, parent=None):
        super().__init__(parent)
        use_styled_background(self)
        self.required_frames = required_frames
        self.matcher = StaticGestureMatcher()
        self.samples = []
        self.saved_template = None
        self.state = RecordingState.WAITING
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setObjectName("settingsPageTitle")
        self.status = QLabel()
        self.status.setObjectName("hintLabel")
        self.preview = QLabel()
        self.preview.setObjectName("recordingPreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.name_input = QLineEdit()
        self.retry_button = QPushButton()
        self.confirm_button = QPushButton()
        self.retry_button.clicked.connect(self.retry)
        self.confirm_button.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addWidget(self.retry_button); row.addStretch(); row.addWidget(self.confirm_button)
        layout.addWidget(self.title_label); layout.addWidget(self.status); layout.addWidget(self.preview); layout.addWidget(self.name_input); layout.addLayout(row)
        self.retranslate_ui()

    @property
    def sample_count(self):
        return len(self.samples)

    @property
    def can_confirm(self):
        return self.state is RecordingState.READY_TO_CONFIRM

    def accept_landmarks(self, landmarks):
        if self.state in {RecordingState.SAVED, RecordingState.FAILED}:
            return
        if self.matcher.normalize(landmarks) is None:
            self.state = RecordingState.FAILED
            self._refresh()
            return
        self.samples.append(landmarks)
        self.state = RecordingState.READY_TO_CONFIRM if len(self.samples) >= self.required_frames else RecordingState.CAPTURING
        self._refresh()

    def accept_landmark_frame(self, landmark_frame):
        """Accept a frame from a dedicated camera worker while recording."""
        frame = landmark_frame.frame
        if frame is not None:
            height, width, channels = frame.shape
            image = QImage(frame.data, width, height, channels * width, QImage.Format_BGR888)
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.FastTransformation
            ))
        self.accept_landmarks(landmark_frame.landmarks)

    def retry(self):
        self.samples.clear()
        self.state = RecordingState.WAITING
        self._refresh()

    def confirm_template(self):
        if self.saved_template is not None:
            return self.saved_template
        if not self.can_confirm or not self.name_input.text().strip():
            return None
        template = self.matcher.create_template(self.name_input.text().strip(), self.samples)
        if template is None:
            self.state = RecordingState.FAILED
            self._refresh()
            return None
        self.saved_template = template
        self.state = RecordingState.SAVED
        self._refresh()
        return template

    def accept(self):
        if self.confirm_template() is not None:
            super().accept()

    def retranslate_ui(self):
        """Refresh static UI copy without altering captured landmarks or input."""
        self.setWindowTitle(tr("settings.static_trigger.title"))
        self.title_label.setText(tr("settings.static_trigger.instruction"))
        if not self.preview.pixmap():
            self.preview.setText(tr("settings.static_trigger.preview_waiting"))
        self.name_input.setPlaceholderText(tr("settings.static_trigger.name_placeholder"))
        self.retry_button.setText(tr("settings.static_trigger.retry"))
        self.confirm_button.setText(tr("settings.static_trigger.save"))
        self._refresh()

    def _refresh(self):
        self.status.setText(
            tr(
                "settings.static_trigger.samples_progress",
                sample_count=self.sample_count,
                required_frames=self.required_frames,
            )
        )
        self.confirm_button.setEnabled(self.can_confirm)

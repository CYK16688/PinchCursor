"""Camera-backed dialog for collecting a user's pinch calibration samples."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout
)

from .i18n import tr
from .pinch_calibration_flow import CalibrationResult, CalibrationSession
from .theme import use_styled_background


class PinchCalibrationDialog(QDialog):
    """Guide five pinch motions while an isolated worker owns camera resources."""

    def __init__(self, *, camera_config=None, config=None, worker_factory=None, parent=None):
        super().__init__(parent)
        use_styled_background(self)
        self.config = config
        self.camera_config = dict(camera_config or self._config_value("camera") or {})
        self.worker_factory = worker_factory
        self.session = CalibrationSession()
        self.calibration: CalibrationResult | None = None
        self.worker = None
        self.recording_detector = None

        self.setMinimumWidth(460)
        self.setWindowTitle(tr("calibration.title"))
        layout = QVBoxLayout(self)

        self.title_label = QLabel(tr("settings.control.calibrate.button"))
        self.title_label.setObjectName("settingsPageTitle")
        self.instruction_label = QLabel(tr("calibration.instruction"))
        self.instruction_label.setObjectName("hintLabel")
        self.instruction_label.setWordWrap(True)
        self.preview = QLabel()
        self.preview.setObjectName("recordingPreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("hintLabel")
        self.failure_label = QLabel()
        self.failure_label.setObjectName("hintLabel")
        self.failure_label.setWordWrap(True)
        self.cancel_button = QPushButton(tr("calibration.cancel"))
        self.save_button = QPushButton(tr("calibration.save"))
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.accept)

        # Labels are vertically Preferred by default, so a taller dialog
        # stretches them into empty boxes. Pin them and let the preview grow.
        for label in (self.title_label, self.instruction_label, self.progress_label, self.failure_label):
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout.addWidget(self.title_label)
        layout.addWidget(self.instruction_label)
        layout.addWidget(self.preview)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.failure_label)
        layout.addLayout(buttons)
        self._refresh()
        self.worker = self._start_recording_worker()

    def _config_value(self, key):
        """Read a section from either the app configuration object or a mapping."""
        if self.config is None:
            return None
        try:
            return self.config.get(key)
        except (AttributeError, TypeError):
            return None

    def _start_recording_worker(self):
        """Create an isolated detector/capture pair so calibration never steals live state."""
        if self.worker_factory is not None:
            try:
                worker = self.worker_factory(
                    camera_config=self.camera_config, config=self.config, parent=self
                )
            except TypeError:
                # A no-argument factory makes simple test doubles convenient.
                worker = self.worker_factory()
            self._connect_and_start_worker(worker)
            return worker

        from core.detector_factory import create_detector
        from core.mediapipe_worker import MediaPipeVideoWorker
        from platform_services.camera_selection import open_configured_camera
        from platform_services.factory import create_platform_services
        from utils.camera_utils import open_camera

        detection = self._config_value("detection") or {}
        detector = create_detector(
            "mediapipe",
            detection.get("confidence", 0.7),
            detection.get("tracking_confidence", 0.5),
        )
        capture = open_configured_camera(
            self.camera_config,
            create_platform_services().camera_service,
            legacy_open=open_camera,
        )
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            detector.release()
            self.failure_label.setText(tr("calibration.failed"))
            return None
        self.recording_detector = detector
        worker = MediaPipeVideoWorker(
            camera_id=self.camera_config.get("id", 0),
            width=self.camera_config.get("width", 640),
            height=self.camera_config.get("height", 480),
            detector=detector,
            capture=capture,
            parent=self,
        )
        self._connect_and_start_worker(worker)
        return worker

    def _connect_and_start_worker(self, worker) -> None:
        """Attach the only required worker signals without constraining test doubles."""
        if worker is None:
            return
        landmark_signal = getattr(worker, "landmark_frame_ready", None)
        if landmark_signal is not None:
            landmark_signal.connect(self.accept_landmark_frame)
        error_signal = getattr(worker, "worker_error", None)
        if error_signal is not None:
            error_signal.connect(lambda _message: self.failure_label.setText(tr("calibration.failed")))
        start = getattr(worker, "start", None)
        if start is not None:
            start()

    def accept_landmark_frame(self, landmark_frame) -> None:
        """Display the frame and feed its timestamped landmarks into the pure session."""
        try:
            frame = landmark_frame.frame
            if frame is not None:
                height, width, channels = frame.shape
                image = QImage(frame.data, width, height, channels * width, QImage.Format_BGR888)
                pixmap = QPixmap.fromImage(image).scaled(
                    self.preview.size(), Qt.KeepAspectRatio, Qt.FastTransformation
                )
                self.preview.setPixmap(pixmap)
            timestamp = float(landmark_frame.timestamp_ms) / 1000.0
            self.session.add_landmarks(landmark_frame.landmarks, timestamp)
            self._refresh()
        except Exception:
            # A malformed camera frame must leave the dialog usable and closable.
            return

    def _refresh(self) -> None:
        """Update only transient progress while preserving any failure explanation."""
        self.progress_label.setText(
            tr("calibration.progress").format(
                done=self.session.progress, total=self.session.total_pinches
            )
        )
        # Keep Save available so an early click gives the translated recovery
        # message rather than leaving the user with an unexplained disabled action.
        self.save_button.setEnabled(True)

    def accept(self) -> None:
        """Accept only a completed session with enough valid calibrator samples."""
        result = self.session.result()
        if result is None:
            self.failure_label.setText(tr("calibration.failed"))
            return
        self.calibration = result
        self._cleanup_recording_worker()
        super().accept()

    def reject(self) -> None:
        """Stop the isolated worker before the dialog can release its Qt ownership."""
        self._cleanup_recording_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        """Also release the camera when the window manager closes the dialog."""
        self._cleanup_recording_worker()
        super().closeEvent(event)

    def _cleanup_recording_worker(self) -> None:
        """Stop capture first, then release the detector even after worker startup failures."""
        worker, self.worker = self.worker, None
        try:
            if worker is not None:
                stop = getattr(worker, "stop", None)
                if stop is not None:
                    stop()
                wait = getattr(worker, "wait", None)
                if wait is not None:
                    wait(2000)
                delete_later = getattr(worker, "deleteLater", None)
                if delete_later is not None:
                    delete_later()
        finally:
            detector, self.recording_detector = self.recording_detector, None
            if detector is not None:
                release = getattr(detector, "release", None)
                if release is not None:
                    release()

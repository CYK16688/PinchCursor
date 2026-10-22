from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import cv2
from PySide6.QtCore import QThread, Signal


@dataclass(frozen=True)
class LandmarkFrame:
    frame: object
    landmarks: list[tuple[int, int, float]] | None
    timestamp_ms: int


class MediaPipeVideoWorker(QThread):
    """Owns ordered MediaPipe VIDEO inference for a UI-created camera capture."""

    landmark_frame_ready = Signal(object)
    worker_ready = Signal()
    worker_error = Signal(str)

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        detector=None,
        capture=None,
        detector_factory: Callable[[], object] | None = None,
        capture_opener: Callable[[], object] | None = None,
        capture_factory: Callable[[int], object] = cv2.VideoCapture,
        clock: Callable[[], float] = time.monotonic,
        parent=None,
    ):
        super().__init__(parent)
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.detector = detector
        self.capture = capture
        self.detector_factory = detector_factory
        self.capture_opener = capture_opener
        self.capture_factory = capture_factory
        self.clock = clock
        self._running = False
        self._last_timestamp_ms = -1

    @classmethod
    def for_test(cls) -> "MediaPipeVideoWorker":
        return cls(detector=None, capture_factory=lambda _: None)

    def next_timestamp_ms(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        timestamp_ms = int(now * 1000)
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms
        return timestamp_ms

    def stop(self) -> None:
        self._running = False
        self.requestInterruption()

    def run(self) -> None:
        try:
            if self.detector is None and self.detector_factory is not None:
                self.detector = self.detector_factory()
            if self.capture is None:
                self.capture = (
                    self.capture_opener()
                    if self.capture_opener is not None
                    else self.capture_factory(self.camera_id)
                )
            if self.capture is None or not self.capture.isOpened():
                self.worker_error.emit("Unable to open selected camera")
                return
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._running = True
            self.worker_ready.emit()
            while self._running and not self.isInterruptionRequested():
                ok, frame = self.capture.read()
                if not ok:
                    self.worker_error.emit("Camera frame capture failed")
                    break
                frame = cv2.flip(frame, 1)
                # The Metal delegate only accepts four-channel input; the CPU
                # graph wants three. The detector owns that choice.
                color_format = getattr(self.detector, "color_format", "rgb")
                code = cv2.COLOR_BGR2RGBA if color_format == "rgba" else cv2.COLOR_BGR2RGB
                rgb = cv2.cvtColor(frame, code)
                timestamp_ms = self.next_timestamp_ms()
                result = self.detector.detect_for_video(rgb, timestamp_ms)
                landmarks = self.detector.get_landmarks(result, frame.shape)
                self.landmark_frame_ready.emit(
                    LandmarkFrame(frame=frame, landmarks=landmarks, timestamp_ms=timestamp_ms)
                )
        except Exception as error:
            self.worker_error.emit(str(error))
        finally:
            if self.capture is not None:
                self.capture.release()
                self.capture = None
            if self.detector is not None:
                release = getattr(self.detector, "release", None)
                if release is not None:
                    release()
                self.detector = None
            self._running = False

from __future__ import annotations

import math
import time
import threading
from dataclasses import dataclass
from typing import Callable

import cv2
from PySide6.QtCore import QThread, Signal


@dataclass(frozen=True)
class LandmarkFrame:
    frame: object
    landmarks: list[tuple[float, float, float]] | None
    timestamp_ms: int


class MediaPipeVideoWorker(QThread):
    """Owns ordered MediaPipe VIDEO inference for a UI-created camera capture."""

    landmark_frame_ready = Signal(object)
    frame_available = Signal(object)
    worker_ready = Signal()
    worker_error = Signal(str)
    source_ready = Signal(object)
    source_error = Signal(object, str)

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
        coalesce_frames: bool = False,
        frame_consumer: Callable[[LandmarkFrame], object] | None = None,
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
        self.coalesce_frames = coalesce_frames
        self.frame_consumer = frame_consumer
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._notification_pending = False
        self._running = False
        self._last_timestamp_ms = -1
        # Minimum seconds between two inference passes. The main window raises
        # this once no hand has been seen for a while, so an idle camera stops
        # burning a full CPU/GPU core. It is never raised while a hand is
        # tracked, because that is exactly when latency matters.
        self.min_frame_interval = 0.0

    def set_min_frame_interval(self, seconds: float) -> None:
        """Throttle inference to at most one pass per ``seconds`` (0 disables)."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        # NaN survives both min() and max(), and a NaN deadline makes every
        # comparison false, which would silently disable the throttle entirely.
        if not math.isfinite(value):
            return
        self.min_frame_interval = max(0.0, min(value, 1.0))

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

    def _publish_frame(self, frame):
        if self.frame_consumer is not None:
            # The callback must only submit to a bounded mailbox. Running it
            # here avoids the GUI event loop becoming part of input delivery.
            self.frame_consumer(frame)
            return
        if not self.coalesce_frames:
            self.landmark_frame_ready.emit(frame)
            return
        with self._frame_lock:
            self._latest_frame = frame
            notify = not self._notification_pending
            self._notification_pending = True
        if notify:
            self.frame_available.emit(self)

    def take_latest_frame(self):
        """A single-slot mailbox: queued GUI work never retains old images."""
        with self._frame_lock:
            frame = self._latest_frame
            self._latest_frame = None
            self._notification_pending = False
            return frame

    def _report_error(self, message):
        self.worker_error.emit(message)
        self.source_error.emit(self, message)

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
                self._report_error("Unable to open selected camera")
                return
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if self.isInterruptionRequested():
                return
            self._running = True
            self.worker_ready.emit()
            self.source_ready.emit(self)
            next_pass_at = 0.0
            while self._running and not self.isInterruptionRequested():
                ok, frame = self.capture.read()
                if not ok:
                    self._report_error("Camera frame capture failed")
                    break
                # Sleep on the frames the power policy told us to skip. The read
                # still happens so the capture buffer does not go stale.
                now = self.clock()
                if self.min_frame_interval > 0.0 and now < next_pass_at:
                    time.sleep(min(next_pass_at - now, 0.05))
                    continue
                next_pass_at = now + self.min_frame_interval
                frame = cv2.flip(frame, 1)
                # The Metal delegate only accepts four-channel input; the CPU
                # graph wants three. The detector owns that choice.
                color_format = getattr(self.detector, "color_format", "rgb")
                code = cv2.COLOR_BGR2RGBA if color_format == "rgba" else cv2.COLOR_BGR2RGB
                rgb = cv2.cvtColor(frame, code)
                timestamp_ms = self.next_timestamp_ms()
                result = self.detector.detect_for_video(rgb, timestamp_ms)
                landmarks = self.detector.get_landmarks(result, frame.shape)
                if self.isInterruptionRequested() or not self._running:
                    break
                self._publish_frame(
                    LandmarkFrame(frame=frame, landmarks=landmarks, timestamp_ms=timestamp_ms)
                )
        except Exception as error:
            self._report_error(str(error))
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

"""Qt-free state machine for guided pinch-threshold calibration."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable

from core.gesture_classifier import (
    GestureClassifier,
    PinchCalibrator,
    palm_scale_from_landmarks,
)


@dataclass(frozen=True)
class CalibrationResult:
    """The validated pinch-distance / palm-scale thresholds from one session."""

    enter_ratio: float
    exit_ratio: float
    sample_count: int


class CalibrationSession:
    """Collect guided pinch samples without depending on a GUI or camera device."""

    def __init__(
        self,
        *,
        total_pinches: int = 5,
        min_samples: int = 10,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.total_pinches = self._positive_int(total_pinches, 5)
        self.min_samples = self._positive_int(min_samples, PinchCalibrator.MIN_SAMPLES)
        self._clock = clock or time.monotonic
        self.reset()

    @staticmethod
    def _positive_int(value, default: int) -> int:
        """Return a safe positive count without exposing configuration errors to UI code."""
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _pinch_distance(landmarks) -> float | None:
        """Return thumb-tip to index-tip distance, ignoring invalid frames."""
        try:
            if landmarks is None or len(landmarks) <= 8:
                return None
            thumb = landmarks[4]
            index = landmarks[8]
            dx = float(index[0]) - float(thumb[0])
            dy = float(index[1]) - float(thumb[1])
            distance = math.hypot(dx, dy)
        except Exception:
            # Detector output is external input; a bad frame must not interrupt calibration.
            return None
        return distance if math.isfinite(distance) and distance >= 0.0 else None

    @staticmethod
    def _valid_time(now) -> bool:
        """Reject malformed timestamps while keeping sampling entirely non-throwing."""
        try:
            return math.isfinite(float(now))
        except (TypeError, ValueError, OverflowError):
            return False

    def add_landmarks(self, landmarks, now: float) -> None:
        """Collect one valid frame and advance once for each complete pinch motion."""
        if self.finished or not self._valid_time(now):
            return
        try:
            palm_scale = palm_scale_from_landmarks(landmarks)
            pinch_distance = self._pinch_distance(landmarks)
            if palm_scale is None or pinch_distance is None:
                return
            ratio = pinch_distance / palm_scale
            if not math.isfinite(ratio) or ratio < 0.0:
                return
            self._calibrator.add_sample([pinch_distance], [palm_scale])

            if self._in_pinch:
                # Release only beyond the larger threshold so a held pinch cannot
                # become several events because of jitter near the boundary.
                if ratio > GestureClassifier.DEFAULT_PINCH_EXIT_RATIO:
                    self._in_pinch = False
            elif ratio < GestureClassifier.DEFAULT_PINCH_ENTER_RATIO:
                self._in_pinch = True
                self._completed_pinches += 1
        except Exception:
            # Landmark producers are not trusted; calibration is best-effort.
            return

    @property
    def progress(self) -> int:
        """Return the number of completed pinch-and-release motions."""
        return self._completed_pinches

    @property
    def finished(self) -> bool:
        """Whether the requested number of guided pinch motions has been observed."""
        return self._completed_pinches >= self.total_pinches

    @property
    def sample_count(self) -> int:
        """Return the number of valid landmark samples retained by the calibrator."""
        return self._calibrator.sample_count

    def result(self) -> CalibrationResult | None:
        """Return ordered thresholds only after the guided collection is complete."""
        if not self.finished or self.sample_count < self.min_samples:
            return None
        calibration = self._calibrator.thresholds()
        if calibration is None or calibration.enter_ratio >= calibration.exit_ratio:
            return None
        return CalibrationResult(
            enter_ratio=calibration.enter_ratio,
            exit_ratio=calibration.exit_ratio,
            sample_count=calibration.sample_count,
        )

    def reset(self) -> None:
        """Discard samples and re-arm the session for a fresh guided recording."""
        self._calibrator = PinchCalibrator()
        self._completed_pinches = 0
        self._in_pinch = False

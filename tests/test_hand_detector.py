import numpy as np
import pytest
from types import SimpleNamespace

from core.hand_detector import HandDetector
from core.pointer_mapping import AbsoluteMapper, ScreenBounds
from utils.tracker import TargetTracker


def test_hand_detector_supports_video_mode_with_timestamp():
    detector = HandDetector()
    try:
        result = detector.detect_for_video(np.zeros((32, 32, 3), dtype=np.uint8), 1)
        assert result is not None
    finally:
        detector.release()


def test_detector_tracker_and_mapper_preserve_fractional_landmarks():
    detector = HandDetector.__new__(HandDetector)
    result = SimpleNamespace(hand_landmarks=[[
        SimpleNamespace(x=0.2001, y=0.2001, z=0.0) for _ in range(21)
    ]])
    landmarks = detector.get_landmarks(result, (480, 640, 3))
    assert landmarks[8] == pytest.approx((128.064, 96.048, 0.0))
    tracker = TargetTracker()
    pos, tracked = tracker.update(landmarks, (480, 640, 3), timestamp=0.0)
    assert tracked
    assert pos == pytest.approx((128.064, 96.048))
    mapped = AbsoluteMapper().map(pos, (640, 480), ScreenBounds(0, 0, 2560, 1440))
    assert mapped == pytest.approx((512.256, 288.144))

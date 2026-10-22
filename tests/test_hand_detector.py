import numpy as np

from core.hand_detector import HandDetector


def test_hand_detector_supports_video_mode_with_timestamp():
    detector = HandDetector()
    try:
        result = detector.detect_for_video(np.zeros((32, 32, 3), dtype=np.uint8), 1)
        assert result is not None
    finally:
        detector.release()

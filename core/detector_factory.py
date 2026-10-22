"""Create the single safe landmark provider used by Gesture Control."""

from core.base_detector import BaseHandDetector


def create_detector(
    detector_type: str = "mediapipe",
    detection_conf: float = 0.7,
    tracking_conf: float = 0.5,
    delegate: str = "cpu",
) -> BaseHandDetector:
    """Create MediaPipe's 21-landmark detector.

    ``detector_type`` remains an ignored compatibility parameter so persisted
    pre-cleanup settings and focused worker tests can migrate without exposing
    a detector that cannot satisfy the hand-landmark safety contract.
    """
    from core.hand_detector import HandDetector

    return HandDetector(detection_conf, tracking_conf, delegate=delegate)

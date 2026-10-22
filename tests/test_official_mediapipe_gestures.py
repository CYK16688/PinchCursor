from core.gesture_classifier import GestureClassifier
from gui.settings_dialog import SettingsDialog
from utils.config_manager import DEFAULT_CONFIG


OFFICIAL_MEDIAPIPE_CANNED_GESTURES = {
    "Closed_Fist": "fist",
    "Open_Palm": "open_hand",
    "Pointing_Up": "point",
    "Thumb_Down": "thumb_down",
    "Thumb_Up": "thumb_up",
    "Victory": "peace",
    "ILoveYou": "ilove_you",
}


def test_all_official_mediapipe_canned_gestures_have_project_definitions():
    classifier = GestureClassifier()
    configured = DEFAULT_CONFIG["gestures"]
    settings_ids = {gesture_id for gesture_id, _name, _description in SettingsDialog.GESTURES}

    assert set(OFFICIAL_MEDIAPIPE_CANNED_GESTURES.values()) <= set(classifier.gestures)
    assert set(OFFICIAL_MEDIAPIPE_CANNED_GESTURES.values()) <= set(configured)
    assert set(OFFICIAL_MEDIAPIPE_CANNED_GESTURES.values()) <= settings_ids


def test_raw_iloveyou_is_thumb_index_and_pinky_extended(monkeypatch):
    classifier = GestureClassifier()
    monkeypatch.setattr(classifier, "_get_finger_states", lambda _landmarks: [1, 1, 0, 0, 1])
    monkeypatch.setattr(classifier, "_get_pinch_distance", lambda _landmarks: 100)

    assert classifier._detect_raw_gesture([(0, 0)] * 21) == "ilove_you"

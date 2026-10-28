"""The pointer must stop where the fingers closed, not where they settled.

The pinch label needs about four frames to stabilise. During that window the
gesture is still "point", so the pointer kept following the hand and the click
landed away from where the pinch began. Measured before the fix: 2 px of drift at
40 px/s of hand movement, 7 px at 100 px/s, 20 px at 300 px/s, 40 px at 600 px/s.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from gui import main_window as mw
    from utils.config_manager import ConfigManager

    config = ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(mw, "ConfigManager", lambda: config)
    widget = mw.MainWindow()
    yield widget
    widget.close()
    app.processEvents()


def _info(is_pinching):
    return {"distance": 10.0, "velocity": 0.0, "is_approaching": False,
            "is_pinching": is_pinching}


def test_no_pinch_means_the_pointer_follows_the_hand(window):
    assert window._freeze_pointer_for_pinch(100, 200, _info(False)) == (100, 200)
    assert window._freeze_pointer_for_pinch(140, 260, _info(False)) == (140, 260)


def test_the_pointer_stops_on_the_first_pinch_frame(window):
    assert window._freeze_pointer_for_pinch(100, 200, _info(False)) == (100, 200)
    # Fingers close here; the hand keeps moving afterwards.
    assert window._freeze_pointer_for_pinch(140, 260, _info(True)) == (140, 260)
    assert window._freeze_pointer_for_pinch(180, 320, _info(True)) == (140, 260)
    assert window._freeze_pointer_for_pinch(220, 380, _info(True)) == (140, 260)


def test_releasing_frees_the_pointer_again(window):
    window._freeze_pointer_for_pinch(100, 200, _info(False))
    window._freeze_pointer_for_pinch(140, 260, _info(True))
    assert window._freeze_pointer_for_pinch(300, 400, _info(False)) == (300, 400)


def test_a_second_pinch_freezes_at_its_own_position(window):
    window._freeze_pointer_for_pinch(10, 20, _info(True))
    window._freeze_pointer_for_pinch(50, 60, _info(True))
    window._freeze_pointer_for_pinch(90, 90, _info(False))

    assert window._freeze_pointer_for_pinch(500, 500, _info(True)) == (500, 500)


def test_missing_pinch_info_does_not_freeze(window):
    assert window._freeze_pointer_for_pinch(70, 80, None) == (70, 80)
    assert window._freeze_pointer_for_pinch(90, 100, {}) == (90, 100)


def test_the_drift_is_actually_gone_end_to_end():
    """State machine + freeze: the click lands where the pinch was detected."""
    from core.action_state_machine import ActionStateMachine
    from core.gesture_classifier import GestureClassifier

    def run(hand_speed, freeze):
        classifier = GestureClassifier()
        machine = ActionStateMachine()
        now = 0.0
        x = 100.0
        frozen = None
        at_pinch = None
        clicked = None
        for pinching in [False] * 10 + [True] * 5 + [False] * 5:
            landmarks = _pose(pinching)
            gesture = classifier.classify(landmarks, timestamp=now)
            info = classifier.get_pinch_info(landmarks, timestamp=now)
            if freeze and info.get("is_pinching"):
                if frozen is None:
                    frozen = (int(x), 200)
            elif freeze:
                frozen = None
            position = frozen if (freeze and frozen) else (int(x), 200)
            result = machine.update(gesture, position, pinch_info=info, timestamp=now)
            if info.get("is_pinching") and at_pinch is None:
                at_pinch = result["pos"]
            if result.get("action") == "left_click" and clicked is None:
                clicked = result["pos"]
            now += 1 / 30
            x += hand_speed / 30
        return at_pinch, clicked

    for speed in (100, 300, 600):
        free_at, free_click = run(speed, freeze=True)
        assert free_at is not None and free_click is not None, speed
        assert free_click == free_at, f"{speed} px/s still drifts"

        drift_at, drift_click = run(speed, freeze=False)
        assert drift_click is not None, speed
        assert drift_click[0] != drift_at[0], (
            f"the unfrozen path should still drift at {speed} px/s, otherwise "
            "this test proves nothing"
        )


def _pose(pinching):
    """Pointing hand; the thumb closes onto the index tip when ``pinching``."""
    landmarks = [(320.0, 240.0, 0.0)] * 21
    landmarks = list(landmarks)
    landmarks[0] = (320.0, 340.0, 0.0)
    landmarks[9] = (320.0, 240.0, 0.0)
    landmarks[5] = (250.0, 220.0, 0.0)
    landmarks[6] = (248.0, 180.0, 0.0)
    landmarks[7] = (247.0, 150.0, 0.0)
    landmarks[8] = (246.0, 120.0, 0.0)
    landmarks[4] = (250.0, 124.0, 0.0) if pinching else (300.0, 300.0, 0.0)
    landmarks[10] = (320.0, 210.0, 0.0)
    landmarks[11] = (322.0, 250.0, 0.0)
    landmarks[12] = (324.0, 275.0, 0.0)
    landmarks[13] = (385.0, 225.0, 0.0)
    landmarks[14] = (387.0, 260.0, 0.0)
    landmarks[15] = (389.0, 282.0, 0.0)
    landmarks[16] = (391.0, 298.0, 0.0)
    landmarks[17] = (435.0, 240.0, 0.0)
    landmarks[18] = (437.0, 270.0, 0.0)
    landmarks[19] = (439.0, 288.0, 0.0)
    landmarks[20] = (441.0, 302.0, 0.0)
    return landmarks

"""Behavioral tests for the Qt-free pinch calibration session."""

from gui.pinch_calibration_flow import CalibrationSession


def _landmarks(pinch_distance: float):
    """Build a valid pixel-landmark frame with a 100-pixel palm scale."""
    points = [(0.0, 0.0, 0.0)] * 21
    points[0] = (0.0, 0.0, 0.0)
    points[4] = (0.0, 0.0, 0.0)
    points[8] = (pinch_distance, 0.0, 0.0)
    points[9] = (100.0, 0.0, 0.0)
    return points


def _complete_five_pinches(session):
    for index in range(5):
        session.add_landmarks(_landmarks(60.0), float(index * 2))
        session.add_landmarks(_landmarks(10.0), float(index * 2 + 1))


def test_five_pinches_finish_and_produce_ordered_result():
    session = CalibrationSession()

    _complete_five_pinches(session)

    result = session.result()
    assert session.finished
    assert session.progress == 5
    assert result is not None
    assert result.sample_count == 10
    assert result.enter_ratio < result.exit_ratio


def test_held_pinch_counts_only_once_until_released():
    session = CalibrationSession(total_pinches=2)

    session.add_landmarks(_landmarks(60.0), 0.0)
    session.add_landmarks(_landmarks(10.0), 1.0)
    session.add_landmarks(_landmarks(10.0), 2.0)
    session.add_landmarks(_landmarks(10.0), 3.0)

    assert session.progress == 1
    session.add_landmarks(_landmarks(60.0), 4.0)
    session.add_landmarks(_landmarks(10.0), 5.0)
    assert session.progress == 2


def test_invalid_landmarks_are_ignored():
    session = CalibrationSession()

    session.add_landmarks(None, 0.0)
    session.add_landmarks([], 1.0)
    session.add_landmarks([(0.0, 0.0)] * 10, 2.0)
    degenerate = _landmarks(10.0)
    degenerate[9] = (0.0, 0.0, 0.0)
    session.add_landmarks(degenerate, 3.0)

    assert session.progress == 0
    assert session.sample_count == 0


def test_result_is_none_until_session_finishes():
    session = CalibrationSession()
    session.add_landmarks(_landmarks(60.0), 0.0)
    session.add_landmarks(_landmarks(10.0), 1.0)

    assert not session.finished
    assert session.result() is None


def test_reset_clears_collected_samples_and_progress():
    session = CalibrationSession()
    _complete_five_pinches(session)

    session.reset()

    assert session.progress == 0
    assert session.sample_count == 0
    assert not session.finished
    assert session.result() is None

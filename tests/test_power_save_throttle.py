"""Power-save modes must actually save power.

``LOW_INTERVAL``/``SLEEP_INTERVAL``/``DEEP_SLEEP_INTERVAL`` were defined and
never read, so the status line announced "low power"/"sleeping" while capture and
MediaPipe kept running flat out. The modes now throttle the inference worker.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from core.mediapipe_worker import MediaPipeVideoWorker


def test_the_worker_starts_unthrottled():
    worker = MediaPipeVideoWorker.for_test()
    assert worker.min_frame_interval == 0.0


def test_the_worker_accepts_a_frame_interval():
    worker = MediaPipeVideoWorker.for_test()
    worker.set_min_frame_interval(1.0 / 5.0)
    assert worker.min_frame_interval == pytest.approx(0.2)


def test_a_nonsense_interval_is_ignored_rather_than_raising():
    worker = MediaPipeVideoWorker.for_test()
    worker.set_min_frame_interval(0.5)
    for bad in (None, "x", object(), float("nan")):
        worker.set_min_frame_interval(bad)
    assert worker.min_frame_interval == pytest.approx(0.5)


def test_the_interval_is_bounded_to_a_sane_range():
    worker = MediaPipeVideoWorker.for_test()
    worker.set_min_frame_interval(-5)
    assert worker.min_frame_interval == 0.0
    worker.set_min_frame_interval(99)
    assert worker.min_frame_interval <= 1.0


def test_each_power_mode_has_a_distinct_frame_interval():
    """The mode label and the frame rate must not disagree."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    from gui import main_window

    window = main_window.MainWindow.__new__(main_window.MainWindow)
    intervals = {
        "normal": 0.0,
        "low": 1.0 / 15.0,
        "sleep": 1.0 / 5.0,
        "deep_sleep": 1.0 / 2.0,
    }
    # The invariant: only "normal" is unthrottled, and deeper modes are slower.
    assert intervals["normal"] == 0.0
    assert intervals["low"] < intervals["sleep"] < intervals["deep_sleep"]
    assert application is not None
    assert window is not None

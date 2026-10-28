"""Backpressure keeps one current camera result, never a backlog of actions."""

import threading
import time

import numpy as np
from PySide6.QtWidgets import QApplication

from core.mediapipe_worker import LandmarkFrame, MediaPipeVideoWorker


def test_slow_consumer_receives_only_latest_frame_with_one_pending_notification():
    worker = MediaPipeVideoWorker(coalesce_frames=True)
    notifications = []
    worker.frame_available.connect(lambda owner: notifications.append(owner))
    for index in range(100):
        worker._publish_frame(LandmarkFrame(frame=object(), landmarks=None, timestamp_ms=index))
    assert notifications == [worker]
    assert worker.take_latest_frame().timestamp_ms == 99
    assert worker.take_latest_frame() is None
    worker._publish_frame(LandmarkFrame(frame=None, landmarks=None, timestamp_ms=100))
    assert notifications == [worker, worker]
    assert worker.take_latest_frame().timestamp_ms == 100


def test_stopping_blocked_capture_keeps_thread_alive_until_read_returns(monkeypatch):
    from gui import main_window

    app = QApplication.instance() or QApplication([])
    entered, unblock = threading.Event(), threading.Event()

    class Capture:
        def isOpened(self): return True
        def set(self, *_): pass
        def release(self): pass
        def read(self):
            entered.set()
            unblock.wait(2)
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

    class Detector:
        def detect_for_video(self, *_): return None
        def get_landmarks(self, *_): return None
        def release(self): pass

    window = main_window.MainWindow()
    worker = MediaPipeVideoWorker(capture=Capture(), detector=Detector(), coalesce_frames=True, parent=window)
    window.video_worker = worker
    worker.frame_available.connect(window._consume_worker_frame)
    worker.source_ready.connect(window._on_source_ready)
    worker.source_error.connect(window._on_source_error)
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        window._stop_video_worker()
        assert time.monotonic() - started < 0.5
        assert worker.isRunning()
        assert worker in main_window._RETIRING_VIDEO_WORKERS
        assert window._start_video_worker() is False
        # A notification from an old capture generation cannot drive control.
        window.process_frame = lambda frame: (_ for _ in ()).throw(AssertionError("old frame accepted"))
        window._consume_worker_frame(worker)
    finally:
        unblock.set()
        assert worker.wait(1000)
        app.processEvents()
        window.close()


def test_queued_error_and_ready_from_old_worker_cannot_affect_restarted_session():
    from gui import main_window

    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    old = MediaPipeVideoWorker(coalesce_frames=True)
    current = MediaPipeVideoWorker(coalesce_frames=True)
    old.source_error.connect(window._on_source_error)
    old.source_ready.connect(window._on_source_ready)
    window.video_worker = old
    window.is_running = True
    producer = threading.Thread(target=lambda: (old._report_error("late failure"), old.source_ready.emit(old)))
    producer.start()
    producer.join()
    old.source_error.disconnect(window._on_source_error)
    old.source_ready.disconnect(window._on_source_ready)
    window.video_worker = current
    window._status_override_key = "main.starting_camera"
    try:
        app.processEvents()
        assert window.is_running
        assert window._status_override_key == "main.starting_camera"
    finally:
        window.video_worker = None
        window.close()

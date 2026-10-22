import threading

from core.mediapipe_worker import MediaPipeVideoWorker


class Capture:
    def __init__(self):
        self.released = False

    def isOpened(self):
        return True

    def set(self, *_args):
        pass

    def read(self):
        return False, None

    def release(self):
        self.released = True


class Detector:
    def __init__(self):
        self.released = False

    def detect_for_video(self, _rgb, _timestamp_ms):
        return None

    def get_landmarks(self, _result, _frame_shape):
        return None

    def release(self):
        self.released = True


def test_video_worker_uses_strictly_increasing_millisecond_timestamps():
    worker = MediaPipeVideoWorker.for_test()

    assert worker.next_timestamp_ms(1000.0) < worker.next_timestamp_ms(1000.0)


def test_video_worker_uses_capture_created_by_ui_thread():
    capture = Capture()
    worker = MediaPipeVideoWorker(detector=None, capture=capture)

    assert worker.capture is capture


def test_video_worker_releases_ui_created_capture_after_camera_failure():
    capture = Capture()
    worker = MediaPipeVideoWorker(detector=Detector(), capture=capture)

    worker.start()
    assert worker.wait(1000)

    assert capture.released is True


def test_video_worker_initializes_detector_and_capture_off_the_ui_thread():
    ui_thread_id = threading.get_ident()
    observed_thread_ids = []
    detector = Detector()
    capture = Capture()

    worker = MediaPipeVideoWorker(
        detector_factory=lambda: observed_thread_ids.append(threading.get_ident()) or detector,
        capture_opener=lambda: observed_thread_ids.append(threading.get_ident()) or capture,
    )
    worker.start()

    assert worker.wait(1000)
    assert len(observed_thread_ids) == 2
    assert observed_thread_ids[0] == observed_thread_ids[1]
    assert observed_thread_ids[0] != ui_thread_id
    assert capture.released is True
    assert detector.released is True

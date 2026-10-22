from __future__ import annotations

import platform

import cv2


def camera_backend_for_platform(system_name: str | None = None):
    """Return a platform-safe preferred capture backend, if one is needed."""
    system_name = system_name or platform.system()
    return cv2.CAP_DSHOW if system_name == "Windows" else None


def open_camera(camera_id: int, system_name: str | None = None):
    backend = camera_backend_for_platform(system_name)
    if backend is None:
        return cv2.VideoCapture(camera_id)
    return cv2.VideoCapture(camera_id, backend)


def detect_cameras(max_cameras: int = 10, system_name: str | None = None):
    """Detect available cameras without assuming a Windows-only backend."""
    cameras = []
    for camera_id in range(max_cameras):
        cap = open_camera(camera_id, system_name)
        if not cap.isOpened() and camera_backend_for_platform(system_name) is not None:
            cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            continue
        try:
            ok, frame = cap.read()
            camera_type = _analyze_camera_type(frame) if ok and frame is not None else "unknown"
            label = {"rgb": "RGB", "ir": "红外", "unknown": ""}.get(camera_type, "")
            name = f"摄像头 {camera_id}" + (f" ({label})" if label else "")
            cameras.append((camera_id, name, camera_type))
        finally:
            cap.release()
    return cameras


def _analyze_camera_type(frame):
    if frame is None or frame.size == 0:
        return "unknown"
    if len(frame.shape) == 2:
        return "ir"
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return "ir" if hsv[:, :, 1].mean() < 15 else "rgb"


def find_ir_camera(cameras):
    for camera_id, _name, camera_type in cameras:
        if camera_type == "ir":
            return camera_id
    return None


class IRPresenceDetector:
    """Optional low-power IR presence detector for supported camera setups."""

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.cap = None
        self.baseline = None
        self.threshold = 30
        self.presence_frames = 0
        self.absence_frames = 0
        self.confirm_threshold = 3

    def start(self):
        self.cap = open_camera(self.camera_id)
        if not self.cap.isOpened():
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        self._establish_baseline()
        return True

    def stop(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        self.baseline = None

    def _establish_baseline(self):
        import numpy as np

        frames = []
        for _ in range(5):
            ok, frame = self.cap.read()
            if ok:
                frames.append(self._gray(frame).astype("float32"))
        if frames:
            self.baseline = np.mean(frames, axis=0)

    def detect_presence(self):
        import numpy as np

        if not self.cap or not self.cap.isOpened():
            return True
        ok, frame = self.cap.read()
        if not ok:
            return True
        gray = self._gray(frame)
        if self.baseline is None:
            self.baseline = gray.astype("float32")
            return True
        diff = cv2.absdiff(gray, self.baseline.astype("uint8"))
        _threshold, binary = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)
        has_presence = diff.mean() > 10 or np.mean(binary > 0) > 0.05
        if has_presence:
            self.presence_frames += 1
            self.absence_frames = 0
        else:
            self.absence_frames += 1
            self.presence_frames = 0
            self.baseline = self.baseline * 0.99 + gray.astype("float32") * 0.01
        if self.presence_frames >= self.confirm_threshold:
            return True
        if self.absence_frames >= self.confirm_threshold * 2:
            return False
        return True

    @staticmethod
    def _gray(frame):
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame

"""Windows camera enumeration behind the shared ``CameraService`` contract.

Windows offers no dependency-free way to read friendly device names (that needs
Media Foundation or WMI through COM), so devices are enumerated by probing
OpenCV capture indices. Each device gets a stable, index-derived identity -
``windows-index-N`` - which survives re-ordering of the dropdown and lets
``open_selected`` reopen exactly the same index later.

Probing costs a capture open per index, and the GUI asks for the device list on
every console refresh, so results are cached for a few seconds. ``refresh`` in
the camera settings page still reaches real hardware because the cache expires.
Worse than the cost is exclusivity: Windows capture handles are usually exclusive,
so a probe can collide with the video worker opening the same camera. Two guards
handle that - all opens are serialized through a process-wide lock, and an index
this service already handed out is never re-probed while its capture is open.

Manual Windows validation still required for: which indices appear on a given
machine, whether DirectShow needs the plain-backend fallback, whether probing is
fast enough to stay on the UI thread, and whether the open lock is sufficient
against a driver that reports a camera as busy to the *second* opener.
"""

from __future__ import annotations

import sys
import threading
import time

import cv2

from platform_services.contracts import CameraDevice
from platform_services.null import UnavailableCameraService

__all__ = [
    "DEVICE_ID_PREFIX",
    "WindowsCameraService",
    "UnavailableCameraService",
]

DEVICE_ID_PREFIX = "windows-index-"
DEFAULT_MAX_DEVICES = 8
DEFAULT_CACHE_SECONDS = 5.0

# Windows capture handles are usually exclusive. Probing an index while the
# video worker opens the same one would make one of the two fail, so every
# open/close in this module is serialized through one process-wide lock.
_CAPTURE_OPEN_LOCK = threading.Lock()


def windows_capture_factory(index: int):
    """Open a Windows capture handle for one index, preferring DirectShow."""
    if sys.platform != "win32":
        raise RuntimeError("Windows video capture requires a Windows host")
    from utils.camera_utils import camera_backend_for_platform

    backend = camera_backend_for_platform("Windows")
    capture = cv2.VideoCapture(int(index), backend)
    if not capture.isOpened() and backend is not None:
        capture.release()
        capture = cv2.VideoCapture(int(index))
    return capture


class WindowsCameraService:
    """Index-probing Windows camera service with stable device identities."""

    def __init__(
        self,
        capture_factory=None,
        max_devices: int = DEFAULT_MAX_DEVICES,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        clock=None,
    ):
        self._capture_factory = capture_factory or windows_capture_factory
        self._max_devices = max(1, int(max_devices))
        self._cache_seconds = max(0.0, float(cache_seconds))
        self._clock = clock or time.monotonic
        self._cache: tuple[float, list[CameraDevice]] | None = None
        self._active_device: CameraDevice | None = None
        self._active_capture = None

    def list_devices(self, force: bool = False) -> list[CameraDevice]:
        """Return usable cameras; never raises, never invents a device."""
        now = self._clock()
        if not force and self._cache is not None:
            cached_at, devices = self._cache
            if now - cached_at < self._cache_seconds:
                return list(devices)
        devices = [
            device
            for device in (self._probe(index) for index in range(self._max_devices))
            if device is not None
        ]
        self._cache = (now, devices)
        return list(devices)

    def open_selected(self, device_id: str, width: int, height: int):
        """Open the capture index encoded in ``device_id``, or None if unusable."""
        index = self.index_for_device(device_id)
        if index is None:
            return None
        capture = None
        with _CAPTURE_OPEN_LOCK:
            try:
                capture = self._capture_factory(index)
            except Exception:
                return None
            if capture is None or not capture.isOpened():
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        pass
                return None
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._active_capture = capture
        self._active_device = self._device(index)
        return capture

    def _forget_active_capture(self) -> None:
        """Forget the handed-out capture without closing it."""
        self._active_capture = None
        self._active_device = None

    @staticmethod
    def index_for_device(device_id: object) -> int | None:
        """Decode ``windows-index-N`` into N, rejecting every other shape."""
        if not isinstance(device_id, str) or not device_id.startswith(DEVICE_ID_PREFIX):
            return None
        suffix = device_id[len(DEVICE_ID_PREFIX):]
        if not suffix.isdigit():
            return None
        return int(suffix)

    def _probe(self, index: int) -> CameraDevice | None:
        """A camera is reported only if it opens *and* delivers a frame."""
        active = self._active_device
        if active is not None and active.device_id == f"{DEVICE_ID_PREFIX}{index}":
            # Never re-probe a device this service already handed out: the
            # capture is still open, so a second open would fail and the device
            # would wrongly vanish from the list mid-session.
            if self._capture_still_open():
                return active
            self._forget_active_capture()
        with _CAPTURE_OPEN_LOCK:
            return self._probe_locked(index)

    def _probe_locked(self, index: int) -> CameraDevice | None:
        capture = None
        try:
            capture = self._capture_factory(index)
            if capture is None or not capture.isOpened():
                return None
            delivered, frame = capture.read()
            if not delivered or frame is None:
                return None
            return self._device(index)
        except Exception:
            return None
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass

    def _capture_still_open(self) -> bool:
        try:
            return bool(self._active_capture is not None and self._active_capture.isOpened())
        except Exception:
            return False

    @staticmethod
    def _device(index: int) -> CameraDevice:
        return CameraDevice(
            device_id=f"{DEVICE_ID_PREFIX}{index}",
            display_name=f"Camera {index}",
            kind="unknown",
            available=True,
        )

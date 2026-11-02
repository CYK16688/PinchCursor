"""Optional IR camera ownership isolated from Qt, RGB capture and input."""
from __future__ import annotations

import threading
import time


class IRPresenceRuntime:
    """Sample one optional detector on a single, non-restartable daemon.

    Factory, camera startup, reads and release all run on that owner. If native
    camera I/O hangs, callers can still stop RGB/input and the cached sample
    expires. Keep this instance until ``close`` succeeds before replacing it.
    """

    def __init__(self, detector_factory=None, *, clock=time.monotonic,
                 sample_interval=0.2, max_sample_age=1.0):
        self._factory = detector_factory
        self._clock = clock
        self._sample_interval = sample_interval
        self._max_sample_age = max_sample_age
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sample = None
        self._sample_at = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def presence(self):
        with self._lock:
            if (self._stop.is_set() or self._sample_at is None
                    or not 0 <= self._clock() - self._sample_at <= self._max_sample_age):
                return None
            return self._sample

    def start(self):
        with self._lock:
            if self._stop.is_set() or self._thread is not None:
                raise RuntimeError("IRPresenceRuntime instances cannot restart")
            if self._factory is None:
                return False
            self._thread = threading.Thread(
                target=self._run, name="infrared-presence", daemon=True,
            )
            try:
                self._thread.start()
            except Exception:
                self._thread = None
                self._stop.set()
                raise
        return True

    def close(self, timeout=0.0):
        # Serialize only thread creation, never native camera I/O. Otherwise a
        # close racing start could report success before the daemon launches.
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        return not self.is_running

    def _run(self):
        detector = None
        try:
            if self._stop.is_set():
                return
            detector = self._factory()
            if detector is None or self._stop.is_set() or not detector.start():
                return
            while not self._stop.is_set():
                try:
                    sample = detector.detect_presence()
                    sample = sample if isinstance(sample, bool) else None
                except Exception:
                    sample = None
                with self._lock:
                    self._sample = sample
                    self._sample_at = self._clock()
                if self._stop.wait(self._sample_interval):
                    break
        except Exception:
            # Optional hardware failures must not disable the RGB/control lane.
            pass
        finally:
            with self._lock:
                self._sample = None
                self._sample_at = None
            if detector is not None:
                try:
                    detector.stop()
                except Exception:
                    pass

"""Bound native input to fresh camera evidence, independently of the GUI loop."""

from __future__ import annotations

import math
import threading
import time

from platform_services.contracts import ActionResult

MAX_FRAME_AGE_SECONDS = 0.25
FUTURE_FRAME_TOLERANCE_SECONDS = 0.05


def frame_is_fresh(timestamp, now):
    return (
        isinstance(timestamp, (int, float))
        and not isinstance(timestamp, bool)
        and math.isfinite(timestamp)
        and -FUTURE_FRAME_TOLERANCE_SECONDS <= now - timestamp <= MAX_FRAME_AGE_SECONDS
    )


class InputGuard:
    """Serialize input/release and revoke input when frame delivery stops.

    Accessibility queries run outside this lock. If they stall, the watchdog
    can release a drag, and the eventual dispatch checks the expired lease.
    No Qt objects or camera handles are touched by the watchdog.
    """

    def __init__(self, controller, *, clock=time.monotonic):
        self._controller = controller
        self._clock = clock
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._thread = None
        self._watch_retired = True
        self._enabled = False
        self._accepting = True
        self._frame_at = None
        self._interrupted = False
        self._release_failed = False
        self._closing = False
        self._suspended = threading.Event()
        self._release_requested = threading.Event()

    def start(self, *, threaded=True):
        with self._lock:
            with self._lifecycle_lock:
                if self._closing or self.release_pending:
                    raise RuntimeError("Cannot start a closed guard or one with a pending release")
                self._enabled = True
                self._accepting = True
                self._suspended.clear()
                self._frame_at = None
                self._interrupted = False
                if threaded:
                    self._ensure_watchdog_locked()

    def _ensure_watchdog_locked(self):
        # A thread can still be alive after committing to exit. A new owed
        # release must have an owner even during that final interval.
        if self._watch_retired or self._thread is None or not self._thread.is_alive():
            self._shutdown.clear()
            self._watch_retired = False
            self._thread = threading.Thread(target=self._watch, name="input-watchdog", daemon=True)
            self._thread.start()

    def _request_suspend_locked(self):
        if self._suspended.is_set():
            return False
        self._suspended.set()
        self._release_requested.set()
        return True

    def observe_frame(self, timestamp):
        """Renew the lease; return whether local gesture state needs resetting."""
        with self._lock:
            if self._suspended.is_set() or not self._accepting:
                return True
            interrupted = self._interrupted or (
                self._frame_at is not None
                and timestamp - self._frame_at > MAX_FRAME_AGE_SECONDS
            )
            self._interrupted = False
            self._frame_at = timestamp if frame_is_fresh(timestamp, self._clock()) else None
            return interrupted

    def consume_interruption(self):
        """Let the GUI discard stale interaction state when it resumes."""
        with self._lock:
            interrupted = self._interrupted
            self._interrupted = False
            return interrupted

    def execute(self, request):
        with self._lock:
            if (self._suspended.is_set() or not self._accepting) and request.action != "drag_end":
                return ActionResult(False, "Control session is stopped", "session_stopped")
            if request.action != "drag_end" and self._enabled:
                if self._frame_at is None or not frame_is_fresh(self._frame_at, self._clock()):
                    self._interrupted = True
                    self._frame_at = None
                    self._release()
                    return ActionResult(False, "Camera evidence expired", "stale_frame")
            if self._release_failed and not self._release().executed:
                return ActionResult(False, "Mouse release is pending", "release_pending")
            result = self._controller().execute(request)
            if self._suspended.is_set():
                # Stop may have revoked input while the native call was in
                # flight. Preserve native serialization and release as soon as
                # it returns, without relying on the GUI resuming.
                self._frame_at = None
                self._release()
            if not result.executed:
                # A failed down/up may already have reached the OS. Arrange
                # retries even if fresh open-hand frames continue to arrive.
                self._interrupted = True
                self._frame_at = None
                self._release()
            return result

    def release(self):
        with self._lock:
            self._frame_at = None
            return self._release()

    def suspend(self, timeout=0.025):
        """Revoke this session before stopping its producer/decision thread.

        An in-flight frame cannot renew a suspended lease. Only an explicit
        start permits input again; release alone remains an interaction reset.
        """
        # Revocation does not need the native dispatch lock. A stalled native
        # API must not stall the GUI's Stop button or allow a later frame to
        # renew the session while shutdown is waiting for that API.
        with self._lifecycle_lock:
            # Stop and the control-owner finalizer may both suspend the same
            # session. Once revoked, do not enqueue another release after its
            # watchdog has already committed to exiting.
            if not self._request_suspend_locked():
                if self.release_pending:
                    return ActionResult(False, "Mouse release is pending", "release_pending")
                return ActionResult(True)
        return self._finish_suspend(timeout)

    def _finish_suspend(self, timeout):
        if self._thread is not None and self._thread.is_alive():
            # The watchdog or control-owner finalizer performs native release.
            # Even mouse-up can block, so GUI callers must not invoke it here.
            return ActionResult(False, "Mouse release is pending", "release_pending")
        if not self._lock.acquire(timeout=max(0.0, timeout)):
            with self._lifecycle_lock:
                self._ensure_watchdog_locked()
            return ActionResult(False, "Mouse release is pending", "release_pending")
        try:
            self._accepting = False
            self._frame_at = None
            self._interrupted = True
            return self._release()
        finally:
            self._lock.release()

    def _release(self):
        try:
            result = self._controller().release_drag()
        except Exception:
            result = ActionResult(False, "Mouse release failed", "release_pending")
        self._release_failed = not result.executed
        self._release_requested.clear()
        if self._release_failed and self._suspended.is_set():
            with self._lifecycle_lock:
                self._ensure_watchdog_locked()
        return result

    def check_timeout(self):
        """Also exposed for deterministic clock-driven failure tests."""
        with self._lock:
            expired = self._enabled and self._frame_at is not None and not frame_is_fresh(
                self._frame_at, self._clock()
            )
            if expired:
                self._interrupted = True
                self._frame_at = None
            if expired or self._release_failed or self._release_requested.is_set():
                return self._release()
        return None

    def _watch(self):
        try:
            while not self._shutdown.wait(0.025):
                self.check_timeout()
                with self._lifecycle_lock:
                    if self._closing and not self.release_pending:
                        self._shutdown.set()
                        return
        finally:
            with self._lifecycle_lock:
                self._watch_retired = True
                if self.release_pending:
                    self._ensure_watchdog_locked()

    def close(self):
        with self._lifecycle_lock:
            # Publish the terminal state and revoke together, so start cannot
            # rearm input between suspension and committing to close.
            self._closing = True
            newly_suspended = self._request_suspend_locked()
        if newly_suspended:
            self._finish_suspend(0.025)
        with self._lifecycle_lock:
            # A temporary failure or in-flight native call must still be retried
            # after close. Never wait on its dispatch lock on the GUI thread.
            if self.release_pending:
                self._ensure_watchdog_locked()
                return
            self._shutdown.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.1)

    @property
    def release_pending(self):
        return self._release_failed or self._release_requested.is_set()

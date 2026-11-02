"""Optional camera failures and stalls cannot block RGB or input shutdown."""
import threading
import time

import pytest

from core.ir_presence import IRPresenceRuntime
from tests.test_control_runtime import until


class Detector:
    def __init__(self, *, blocked=None, failure=None):
        self.blocked = blocked
        self.failure = failure
        self.entered = threading.Event()
        self.resume = threading.Event()
        self.calls = []
        self.sample = False

    def call(self, phase):
        self.calls.append((phase, threading.current_thread().name))
        if self.blocked == phase:
            self.entered.set()
            assert self.resume.wait(2)
        if self.failure == phase:
            raise OSError("synthetic IR failure")

    def start(self):
        self.call("start")
        return True

    def detect_presence(self):
        self.call("read")
        return self.sample

    def stop(self):
        self.call("stop")


def test_no_factory_does_not_create_a_thread():
    runtime = IRPresenceRuntime()
    assert not runtime.start()
    assert not runtime.is_running
    assert runtime.presence is None
    assert runtime.close()


def test_factory_start_reads_and_stop_share_one_owner_and_sample_expires():
    detector = Detector()
    now = [10.0]
    factory_threads = []

    def factory():
        factory_threads.append(threading.current_thread().name)
        return detector

    runtime = IRPresenceRuntime(factory, clock=lambda: now[0], sample_interval=0.01)
    try:
        assert runtime.start()
        until(lambda: runtime.presence is False)
        # Freeze the next read after one successful sample: stale absence must
        # never keep the application in deep sleep indefinitely.
        detector.blocked = "read"
        assert detector.entered.wait(1)
        now[0] += 1.001
        assert runtime.presence is None
        detector.sample = True
        detector.resume.set()
        until(lambda: runtime.presence is True)
    finally:
        detector.resume.set()
        assert runtime.close(timeout=1)
    assert runtime.presence is None
    assert factory_threads == ["infrared-presence"]
    assert {thread for _, thread in detector.calls} == {"infrared-presence"}
    assert detector.calls[-1][0] == "stop"


@pytest.mark.parametrize("phase", ["factory", "start", "read", "stop"])
def test_stalled_native_call_has_bounded_close_and_cannot_restart(phase):
    detector = Detector(blocked=phase)

    def factory():
        detector.call("factory")
        return detector

    runtime = IRPresenceRuntime(factory, sample_interval=0.001)
    runtime.start()
    if phase == "stop":
        until(lambda: runtime.presence is False)
        runtime.close()
    assert detector.entered.wait(1)
    try:
        started = time.monotonic()
        assert not runtime.close()
        assert time.monotonic() - started < 0.1
        assert runtime.presence is None
        with pytest.raises(RuntimeError, match="cannot restart"):
            runtime.start()
    finally:
        detector.resume.set()
        assert runtime.close(timeout=1)
    assert [phase for phase, _ in detector.calls].count("stop") == 1


@pytest.mark.parametrize("phase", ["factory", "start", "read", "stop"])
def test_optional_hardware_failures_are_isolated_and_cleaned_up(phase):
    detector = Detector(failure=phase)

    def factory():
        if phase == "factory":
            raise OSError("synthetic discovery failure")
        return detector

    runtime = IRPresenceRuntime(factory, sample_interval=0.001)
    runtime.start()
    try:
        if phase in {"factory", "start"}:
            until(lambda: not runtime.is_running)
        else:
            until(lambda: any(name == "read" for name, _ in detector.calls))
        if phase != "stop":
            assert runtime.presence is None
    finally:
        assert runtime.close(timeout=1)
    if phase != "factory":
        assert detector.calls[-1][0] == "stop"


def test_unsuccessful_camera_start_is_released_without_reading():
    detector = Detector()
    detector.start = lambda: False
    runtime = IRPresenceRuntime(lambda: detector)
    runtime.start()
    until(lambda: not runtime.is_running)
    assert runtime.presence is None
    assert [name for name, _ in detector.calls] == ["stop"]
    assert runtime.close()

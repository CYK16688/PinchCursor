"""Live MainWindow wiring with camera/OS fakes and no Qt event pumping."""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from core.control_engine import ControlEngine
from core.control_runtime import ControlRuntime
from gui import main_window
from platform_services.contracts import PlatformCapabilities, PlatformServices
from platform_services.macos.input_controller import MacOSInputController
from platform_services.null import (
    GenericUIContextProvider, NullHoldShortcutMonitor, UnavailableCameraService,
    UnavailablePermissionProvider,
)
from tests.test_control_engine import pose
from utils.config_manager import ConfigManager


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.001)
    assert predicate(), "live control failed to progress without pumping Qt"


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)


class CameraWorker:
    instances = []

    def __init__(self, *, frame_consumer, **kwargs):
        self.frame_consumer = frame_consumer
        self.source_ready = Signal()
        self.source_error = Signal()
        self.finished = Signal()
        self.running = False
        self.instances.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def isRunning(self):
        return self.running

    def wait(self, _timeout):
        return not self.running

    def set_min_frame_interval(self, _interval):
        pass

    def deleteLater(self):
        pass


class Native:
    def __init__(self):
        self.events = []
        self.fail_release = False

    def cursor_position(self):
        return (300, 200)

    def post_mouse(self, kind, x, y, button, click_count=1):
        if kind.endswith("_up") and self.fail_release:
            raise OSError("synthetic release failure")
        self.events.append((kind, threading.current_thread().name))

    def post_scroll(self, vertical, horizontal):
        self.events.append(("scroll", threading.current_thread().name))


class BlockedContext(GenericUIContextProvider):
    def __init__(self):
        super().__init__()
        self.entered, self.unblock = threading.Event(), threading.Event()
        self.calls = 0

    def probe_targets(self, *_args):
        self.calls += 1
        self.entered.set()
        self.unblock.wait()
        return ()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(tmp_path / "settings.json")
    config.config["control_session"]["mode"] = "always"
    config.config["pointer_assist"]["enabled"] = False
    clock = SimpleNamespace(now=100.0)
    native, context = Native(), BlockedContext()
    controller = MacOSInputController(native, clock=lambda: clock.now)
    permissions = UnavailablePermissionProvider()
    services = PlatformServices(
        capabilities=PlatformCapabilities("test", "fake", controller.supported_actions),
        input_controller=controller, context_provider=context,
        permission_provider=permissions, hold_shortcut_monitor=NullHoldShortcutMonitor(),
        camera_service=UnavailableCameraService(),
    )
    CameraWorker.instances = []
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window, "create_platform_services", lambda **kwargs: services)
    monkeypatch.setattr(main_window, "MediaPipeVideoWorker", CameraWorker)
    # An offscreen Qt widget has no NSWindow to attach a native HUD to.
    monkeypatch.setattr(main_window.GestureOverlay, "enable_macos_global_panel", lambda *_args: None)

    def engine_factory(configuration, bounds, coordinator, **kwargs):
        coordinator.input_guard._clock = lambda: clock.now
        return ControlEngine(configuration, bounds, coordinator, clock=lambda: clock.now, **kwargs)

    monkeypatch.setattr(main_window, "ControlEngine", engine_factory)
    monkeypatch.setattr(main_window, "ControlRuntime", lambda engine: ControlRuntime(engine, clock=lambda: clock.now))
    window = main_window.MainWindow()
    window.hud_timer.stop()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def send(name, count, travel=0):
        """Exercise the exact capture callback from a non-GUI thread."""
        failures = []
        worker, runtime = window.video_worker, window.control_runtime

        def produce():
            try:
                for index in range(count):
                    target = runtime.metrics.processed + 1
                    clock.now += 1 / 30
                    worker.frame_consumer(main_window.LandmarkFrame(
                        frame, pose(name, dx=travel * index / max(1, count - 1)), clock.now * 1000,
                    ))
                    until(lambda: runtime.metrics.processed >= target)
            except BaseException as error:
                failures.append(error)

        producer = threading.Thread(target=produce, name="synthetic-camera")
        producer.start()
        producer.join(4)
        assert not producer.is_alive()
        if failures:
            raise failures[0]

    harness = SimpleNamespace(window=window, native=native, context=context, config=config,
                              clock=clock, send=send, frame=frame, app=app)
    yield harness
    context.unblock.set()
    native.fail_release = False
    window.is_running = False
    window._stop_video_worker()
    window.close()


def start(harness):
    harness.window.is_running = True
    assert harness.window._start_video_worker()


def test_live_window_runs_real_engine_and_native_adapter_without_gui_events(harness):
    start(harness)
    harness.send("point", 18)
    harness.send("pinch", 27, travel=100)
    assert any(kind == "left_down" for kind, _ in harness.native.events)
    assert any(kind == "left_dragged" for kind, _ in harness.native.events)
    harness.send("point", 10, travel=100)
    assert any(kind == "left_up" for kind, _ in harness.native.events)
    assert all(thread != threading.main_thread().name for _, thread in harness.native.events)
    assert {thread for kind, thread in harness.native.events if kind in {"move", "left_down"}} == {"gesture-control"}
    # No GUI presentation was needed to classify, dispatch, or release.
    assert harness.window._control_snapshot is None


def test_old_camera_callback_cannot_deliver_to_restarted_session(harness):
    start(harness)
    old_worker, old_runtime = harness.window.video_worker, harness.window.control_runtime
    harness.send("point", 15)
    assert harness.window._stop_video_worker()
    submitted = old_runtime.metrics.submitted
    assert harness.window._start_video_worker()
    new_runtime = harness.window.control_runtime
    assert new_runtime is not old_runtime
    harness.native.events.clear()
    old_worker.frame_consumer(main_window.LandmarkFrame(
        harness.frame, pose("pinch"), harness.clock.now * 1000,
    ))
    assert old_runtime.metrics.submitted == submitted
    assert new_runtime.metrics.submitted == 0
    assert harness.native.events == []
    harness.send("point", 15)
    assert any(kind == "move" for kind, _ in harness.native.events)


def test_restart_waits_for_outstanding_native_mouse_up(harness):
    start(harness)
    harness.send("point", 18)
    harness.send("pinch", 27, travel=100)
    harness.native.fail_release = True
    runtime = harness.window.control_runtime
    harness.window._stop_video_worker()
    until(lambda: not runtime.is_running)
    guard = harness.window._runtime_guard
    assert guard.release_pending
    instances = len(CameraWorker.instances)
    assert not harness.window._start_video_worker()
    assert len(CameraWorker.instances) == instances
    harness.native.fail_release = False
    until(lambda: not guard.release_pending)
    assert harness.window._start_video_worker()
    assert len(CameraWorker.instances) == instances + 1


def test_blocked_ax_is_bounded_and_reused_across_restart(harness):
    harness.config.config["pointer_assist"]["enabled"] = True
    start(harness)
    broker = harness.window._runtime_context
    harness.send("point", 18)
    assert harness.context.entered.wait(1)
    assert any(kind == "move" for kind, _ in harness.native.events)
    assert harness.window._stop_video_worker()
    assert harness.window._runtime_context is broker
    assert harness.window._start_video_worker()
    assert harness.window._runtime_context is broker
    harness.send("point", 15)
    assert harness.context.calls == 1
    assert broker.pending_count == 0


@pytest.mark.parametrize("failure", ["camera", "monitor"])
def test_settings_restart_failure_reports_stopped_state(harness, monkeypatch, failure):
    start(harness)

    class Settings:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr("gui.settings_dialog.SettingsDialog", Settings)
    if failure == "camera":
        monkeypatch.setattr(harness.window, "_start_video_worker", lambda: False)
    else:
        monkeypatch.setattr(harness.window, "_start_hold_shortcut_monitor", lambda: False)
    harness.window.open_settings()
    assert not harness.window.is_running
    assert harness.window.control_runtime is None
    assert harness.window.video_worker is None
    if failure == "camera":
        assert harness.window._status_override_key == "main.control_unavailable"
    else:
        assert harness.window._hold_shortcut_error_key == "main.hold_shortcut_unavailable"

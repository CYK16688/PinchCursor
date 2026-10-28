"""Control-thread ownership, bounded latency and stopped-session rejection."""
import threading
import time
from types import SimpleNamespace

import pytest

from core.action_coordinator import GestureActionCoordinator
from core.action_state_machine import ActionState
from core.control_engine import ControlEngine, ControlSnapshot, DispatchOutcome, HandObservation
from core.control_runtime import ControlRuntime
from core.control_session import SessionState
from core.input_guard import InputGuard
from core.pointer_mapping import ScreenBounds
from platform_services.contracts import ActionRequest, ActionResult, PlatformCapabilities, PlatformServices
from platform_services.null import GenericUIContextProvider, UnavailablePermissionProvider
from utils.config_manager import ConfigManager


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.002)
    assert predicate(), "control actor did not make progress without a GUI event loop"


class Controller:
    def __init__(self):
        self.events = []
        self.fail_release = False

    def execute(self, request):
        self.events.append((request.action, threading.current_thread().name))
        return ActionResult(True)

    def release_drag(self):
        self.events.append(("release", threading.current_thread().name))
        return ActionResult(not self.fail_release)


class BlockingEngine:
    def __init__(self, controller):
        self.entered, self.unblock = threading.Event(), threading.Event()
        self.observed = []
        self.action_coordinator = SimpleNamespace(input_guard=InputGuard(lambda: controller))
        self._outcomes = []

    def _snapshot(self, now, error=""):
        return ControlSnapshot(now, "point", "point", SessionState.POINTER,
                               ActionState.MOVING, True, (10, 20), None,
                               tuple(self._outcomes), error)

    def step(self, observation):
        self.observed.append(observation.timestamp)
        self.entered.set()
        assert self.unblock.wait(2)
        guard = self.action_coordinator.input_guard
        guard.observe_frame(time.monotonic())
        request = ActionRequest("left_click", x=10, y=20)
        self._outcomes = [DispatchOutcome(request, guard.execute(request))]
        return self._snapshot(observation.timestamp)

    def reset(self):
        self.action_coordinator.input_guard.release()
        return ()


def test_mailbox_replaces_pending_frames_and_bounds_feedback():
    controller = Controller()
    engine = BlockingEngine(controller)
    runtime = ControlRuntime(engine)
    runtime.start()
    try:
        runtime.submit(HandObservation(1, None, (640, 480)))
        assert engine.entered.wait(1)
        for timestamp in range(2, 102):
            runtime.submit(HandObservation(timestamp, None, (640, 480)))
        assert runtime.metrics.dropped == 99
        engine.unblock.set()
        until(lambda: runtime.metrics.processed == 2)
        assert engine.observed == [1, 101]
        view = runtime.take_latest()
        assert view.snapshot.timestamp == 101
        assert len(view.outcomes) == 2
        assert runtime.take_latest() is None
    finally:
        engine.unblock.set()
        assert runtime.stop()


def test_stop_revokes_inflight_and_pending_input_before_join():
    controller = Controller()
    engine = BlockingEngine(controller)
    runtime = ControlRuntime(engine)
    runtime.start()
    runtime.submit(HandObservation(1, None, (640, 480)))
    assert engine.entered.wait(1)
    runtime.submit(HandObservation(2, None, (640, 480)))
    assert not runtime.stop(timeout=0.001)
    assert not runtime.submit(HandObservation(3, None, (640, 480)))
    engine.unblock.set()
    until(lambda: not runtime.is_running)
    assert engine.observed == [1]
    assert all(action == "release" for action, _ in controller.events)
    assert runtime.take_latest() is None


def test_engine_exception_releases_and_publishes_fixed_diagnostic():
    controller = Controller()
    engine = BlockingEngine(controller)

    def broken(_):
        raise RuntimeError("private UI content")

    engine.step = broken
    runtime = ControlRuntime(engine)
    runtime.start()
    runtime.submit(HandObservation(time.monotonic(), None, (640, 480)))
    until(lambda: not runtime.is_running)
    view = runtime.take_latest()
    assert view.snapshot.error == "control_failed"
    assert "private" not in repr(view)
    assert controller.events
    assert not runtime.submit(HandObservation(time.monotonic(), None, (640, 480)))


def test_suspend_cannot_be_rearmed_by_an_observation():
    controller = Controller()
    guard = InputGuard(lambda: controller)
    guard.start(threaded=False)
    guard.observe_frame(time.monotonic())
    guard.suspend()
    guard.observe_frame(time.monotonic())
    assert guard.execute(ActionRequest("drag_start")).error_code == "session_stopped"
    guard.start(threaded=False)
    guard.observe_frame(time.monotonic())
    assert guard.execute(ActionRequest("drag_start")).executed
    guard.close()


def test_closed_guard_keeps_retrying_an_owed_release():
    controller = Controller()
    guard = InputGuard(lambda: controller)
    guard.start()
    controller.fail_release = True
    guard.close()
    assert guard.release_pending
    controller.fail_release = False
    until(lambda: not guard.release_pending)
    until(lambda: not guard._thread.is_alive())


def test_stop_is_bounded_when_native_post_is_stuck_and_releases_after_return():
    class BlockedController(Controller):
        entered = threading.Event()
        resume = threading.Event()

        def execute(self, request):
            self.entered.set()
            assert self.resume.wait(2)
            return super().execute(request)

    controller = BlockedController()
    engine = BlockingEngine(controller)
    engine.unblock.set()
    runtime = ControlRuntime(engine)
    runtime.start()
    runtime.submit(HandObservation(time.monotonic(), None, (640, 480)))
    assert controller.entered.wait(1)
    try:
        started = time.monotonic()
        assert not runtime.stop(timeout=0.01)
        assert time.monotonic() - started < 0.2
        assert engine.action_coordinator.input_guard.release_pending
    finally:
        controller.resume.set()
    until(lambda: not runtime.is_running)
    assert controller.events[0][0] == "left_click"
    assert controller.events[-1][0] == "release"
    assert not engine.action_coordinator.input_guard.release_pending


def test_stop_is_bounded_when_native_mouse_up_itself_is_stuck():
    class BlockedRelease(Controller):
        entered = threading.Event()
        resume = threading.Event()

        def release_drag(self):
            self.entered.set()
            assert self.resume.wait(2)
            return super().release_drag()

    controller = BlockedRelease()
    engine = BlockingEngine(controller)
    runtime = ControlRuntime(engine)
    runtime.start()
    started = time.monotonic()
    try:
        assert not runtime.stop(timeout=0.01)
        assert time.monotonic() - started < 0.2
        assert controller.entered.wait(1)
    finally:
        controller.resume.set()
    until(lambda: not runtime.is_running)
    assert not engine.action_coordinator.input_guard.release_pending


@pytest.mark.parametrize("blocked_auxiliary", [False, True])
def test_real_control_engine_runs_all_input_without_pumping_qt(tmp_path, blocked_auxiliary):
    # The actual classifier, dynamics, arbiter, session and state machine run
    # on the actor. Only the camera/native input and clock are replaced.
    from tests.test_continuous_pointer_pipeline import landmarks_for

    now = [10.0]
    clock = lambda: now[0]
    config = ConfigManager(config_path=tmp_path / "config.json").config
    config["control_session"]["mode"] = "always"
    config["pointer_assist"]["enabled"] = blocked_auxiliary
    controller = Controller()
    from core.async_services import AsyncContextProvider, AsyncTelemetry

    unblock = threading.Event()
    context_entered, log_entered = threading.Event(), threading.Event()

    class SlowContext(GenericUIContextProvider):
        def get_context(self, *args):
            context_entered.set()
            assert unblock.wait(3)
            return super().get_context(*args)

        def probe_targets(self, *args):
            context_entered.set()
            assert unblock.wait(3)
            return ()

    class SlowStore:
        enabled = True
        path = "unused"

        def record(self, *args, **kwargs):
            log_entered.set()
            assert unblock.wait(3)

        record_transition = record
        record_candidates = record

    broker = AsyncContextProvider(SlowContext(), clock=clock) if blocked_auxiliary else None
    writer = AsyncTelemetry(SlowStore()) if blocked_auxiliary else None
    services = PlatformServices(
        PlatformCapabilities("test", "test", frozenset({"move_cursor", "left_click", "drag_start", "drag", "drag_end"})),
        controller, broker or GenericUIContextProvider(), UnavailablePermissionProvider(),
    )
    coordinator = GestureActionCoordinator(services)
    coordinator.input_guard._clock = clock
    engine = ControlEngine(config, ScreenBounds(0, 0, 1920, 1080), coordinator,
                           cursor_position=lambda: (500, 400), clock=clock, telemetry=writer)
    runtime = ControlRuntime(engine, clock=clock)
    runtime.start()
    submitted = 0

    def send(pose, count, travel=0):
        nonlocal submitted
        for index in range(count):
            now[0] += 1 / 30
            runtime.submit(HandObservation(now[0], landmarks_for(pose, travel * index / max(1, count - 1)), (640, 480)))
            submitted += 1
            until(lambda: runtime.metrics.processed == submitted)

    try:
        send("point", 20)
        send("pinch", 30, 100)
        send("open_hand", 8)
        actions = [action for action, _ in controller.events]
        assert "move_cursor" in actions
        assert "drag_start" in actions
        assert "drag" in actions
        assert "drag_end" in actions
        assert all(name == "gesture-control" for action, name in controller.events if action != "release")
        view = runtime.take_latest()
        assert any(outcome.request.action == "drag_start" for outcome in view.outcomes)
        assert any(outcome.request.action == "drag_end" for outcome in view.outcomes)
        if blocked_auxiliary:
            assert context_entered.is_set()
            assert log_entered.is_set()
            assert not unblock.is_set(), "all mouse actions must finish while auxiliaries remain blocked"
    finally:
        assert runtime.stop()
        unblock.set()
        if broker:
            assert broker.close(timeout=1)
        if writer:
            assert writer.close(timeout=1)

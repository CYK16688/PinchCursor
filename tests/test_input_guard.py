"""Input leases expire even without a GUI callback or a successful mouse-up."""

import threading
from types import SimpleNamespace

import pytest

from core.action_coordinator import GestureActionCoordinator
from core.input_guard import InputGuard, frame_is_fresh
from platform_services.contracts import ActionRequest, ActionResult, UIContext
from platform_services.macos.input_controller import MacOSInputController


class Native:
    def __init__(self):
        self.events = []
        self.fail_up = False
        self.released = threading.Event()

    def post_mouse(self, kind, x, y, button, click_count=1):
        if kind.endswith("_up") and self.fail_up:
            raise RuntimeError("temporary native failure")
        self.events.append(kind)
        if kind.endswith("_up"):
            self.released.set()


def setup_guard():
    now = [10.0]
    native = Native()
    controller = MacOSInputController(native, clock=lambda: now[0])
    guard = InputGuard(lambda: controller, clock=lambda: now[0])
    guard.start(threaded=False)
    guard.observe_frame(now[0])
    return now, native, controller, guard


@pytest.mark.parametrize("timestamp", [9.0, 11.0, float("nan"), float("inf"), True, None])
def test_stale_future_and_invalid_evidence_is_not_fresh(timestamp):
    assert not frame_is_fresh(timestamp, 10.0)


def test_expired_evidence_releases_and_blocks_delayed_dispatch():
    now, native, controller, guard = setup_guard()
    assert guard.execute(ActionRequest("drag_start", x=100, y=100)).executed
    now[0] += 0.3
    result = guard.execute(ActionRequest("drag", x=200, y=200))
    assert result.error_code == "stale_frame"
    assert native.events == ["left_down", "left_up"]
    assert not controller._dragging
    assert guard.observe_frame(now[0]) is True


def test_watchdog_releases_without_pumping_qt_or_delivering_another_frame():
    now, native, controller, guard = setup_guard()
    guard.start()
    guard.observe_frame(now[0])
    try:
        guard.execute(ActionRequest("drag_start", x=100, y=100))
        now[0] += 0.3
        assert native.released.wait(1.0), "release must run independently of the GUI thread"
        assert native.events == ["left_down", "left_up"]
    finally:
        guard.close()


@pytest.mark.parametrize("action", ["drag_end", "left_click", "right_click"])
def test_failed_release_retries_even_while_fresh_frames_keep_arriving(action):
    now, native, controller, guard = setup_guard()
    if action == "drag_end":
        guard.execute(ActionRequest("drag_start", x=100, y=100))
    native.fail_up = True
    assert not guard.execute(ActionRequest(action, x=100, y=100)).executed
    now[0] += 0.03
    guard.observe_frame(now[0])
    assert not guard.check_timeout().executed
    native.fail_up = False
    now[0] += 0.03
    guard.observe_frame(now[0])
    assert guard.check_timeout().executed
    assert native.events[-1].endswith("_up")
    count = len(native.events)
    guard.check_timeout()
    assert len(native.events) == count


def test_slow_context_lookup_cannot_post_after_the_input_lease_expires():
    now, native, controller, _ = setup_guard()

    def context(*_args):
        now[0] += 0.4
        return UIContext(category="scrollable", target_id="doc")

    provider = SimpleNamespace(
        get_context=context, is_gesture_allowed=lambda *a: True,
        is_action_allowed=lambda *a: True,
    )
    services = SimpleNamespace(
        input_controller=controller, context_provider=provider,
        capabilities=SimpleNamespace(supported_actions=controller.supported_actions, platform="test"),
    )
    coordinator = GestureActionCoordinator(services)
    coordinator.input_guard._clock = lambda: now[0]
    coordinator.input_guard.start(threaded=False)
    coordinator.input_guard.observe_frame(now[0])
    result = coordinator.dispatch(ActionRequest(
        "left_click", x=100, y=100, gesture="point", contextual=True, expected_target_id="doc",
    ))
    assert not result.executed
    assert result.error_code == "stale_frame"
    assert native.events == []

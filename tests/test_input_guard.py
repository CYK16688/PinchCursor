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


def test_repeated_suspend_during_watchdog_exit_does_not_strand_a_release():
    exiting = threading.Event()
    finish_exit = threading.Event()

    class RetiringGuard(InputGuard):
        def _watch(self):
            super()._watch()
            # The watchdog has committed to exiting, but is_alive() is still
            # true: exactly the interleaving in stop/finalizer/close retries.
            exiting.set()
            assert finish_exit.wait(2)

    controller = MacOSInputController(Native())
    guard = RetiringGuard(lambda: controller)
    guard.start()
    try:
        guard.close()
        assert exiting.wait(1)
        assert guard._thread.is_alive()
        assert not guard.release_pending
        assert guard.suspend().executed
        guard.close()
        assert not guard.release_pending
    finally:
        finish_exit.set()
        guard._thread.join(timeout=1)
    assert not guard._thread.is_alive()
    assert guard.suspend().executed
    assert not guard.release_pending


def test_pending_release_prevents_start_until_mouse_up_succeeds():
    _, native, _, guard = setup_guard()
    assert guard.execute(ActionRequest("drag_start", x=100, y=100)).executed
    native.fail_up = True
    assert not guard.suspend().executed
    with pytest.raises(RuntimeError, match="pending release"):
        guard.start(threaded=False)
    assert guard.execute(ActionRequest("left_click", x=100, y=100)).error_code == "session_stopped"
    native.fail_up = False
    assert guard.release().executed
    guard.start(threaded=False)
    guard.observe_frame(10.0)
    assert guard.execute(ActionRequest("left_click", x=100, y=100)).executed
    guard.close()


def test_closed_guard_is_terminal_even_after_successful_release():
    _, _, _, guard = setup_guard()
    guard.close()
    assert not guard.release_pending
    with pytest.raises(RuntimeError, match="closed guard"):
        guard.start(threaded=False)


def test_close_publishes_terminal_state_before_native_release_can_reenter_start():
    rearmed = []

    class ReentrantController:
        def release_drag(self):
            try:
                guard.start(threaded=False)
            except RuntimeError:
                rearmed.append(False)
            else:
                rearmed.append(True)
            return ActionResult(True)

    guard = InputGuard(ReentrantController)
    guard.start(threaded=False)
    guard.close()
    assert rearmed == [False]
    assert guard.execute(ActionRequest("left_click")).error_code == "session_stopped"


def test_close_without_an_existing_watchdog_retries_a_failed_release():
    _, native, _, guard = setup_guard()
    guard.execute(ActionRequest("drag_start", x=100, y=100))
    native.fail_up = True
    guard.close()
    assert guard.release_pending
    native.fail_up = False
    assert native.released.wait(1), "close must give the owed release a retry owner"
    guard._thread.join(timeout=1)
    assert not guard.release_pending
    assert not guard._thread.is_alive()


def test_suspend_without_watchdog_releases_after_native_lock_becomes_available():
    _, native, _, guard = setup_guard()
    guard.execute(ActionRequest("drag_start", x=100, y=100))
    locked = threading.Event()
    unlock = threading.Event()

    def hold_native_lock():
        with guard._lock:
            locked.set()
            assert unlock.wait(2)

    owner = threading.Thread(target=hold_native_lock)
    owner.start()
    try:
        assert locked.wait(1)
        assert not guard.suspend(timeout=0).executed
        assert guard.release_pending
    finally:
        unlock.set()
        owner.join(timeout=1)
    try:
        assert native.released.wait(1)
        assert not guard.release_pending
    finally:
        guard.close()


def test_failed_release_after_watchdog_retirement_gets_a_new_retry_owner():
    retired = threading.Event()
    finish_exit = threading.Event()

    class RetiringGuard(InputGuard):
        def _watch(self):
            super()._watch()
            retired.set()
            assert finish_exit.wait(2)

    fail_release = [False]
    released = threading.Event()

    def release_drag():
        if fail_release[0]:
            return ActionResult(False, "Temporary release failure", "release_pending")
        released.set()
        return ActionResult(True)

    controller = SimpleNamespace(release_drag=release_drag)
    guard = RetiringGuard(lambda: controller)
    guard.start()
    old_thread = guard._thread
    try:
        guard.close()
        assert retired.wait(1)
        assert old_thread.is_alive()
        # A finalizer can still owe a release while the old worker is alive
        # but has retired. Failed mouse-up must not be delegated to that worker.
        released.clear()
        fail_release[0] = True
        assert not guard.release().executed
        assert guard._thread is not old_thread
        fail_release[0] = False
        assert released.wait(1)
    finally:
        finish_exit.set()
        old_thread.join(timeout=1)
        guard.close()
        guard._thread.join(timeout=1)
    assert not guard.release_pending
    assert not guard._thread.is_alive()

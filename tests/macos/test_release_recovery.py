"""Failed native releases stay recoverable across stop and subsequent requests."""

import pytest

from platform_services.contracts import ActionRequest
from platform_services.macos.input_controller import MacOSInputController


class RecoverableNative:
    def __init__(self):
        self.attempts = []
        self.events = []
        self.fail_on = set()
        self.fail_after_delivery = set()
        self.fail_up_number = None
        self.partial_failure_type = OSError
        self.up_attempts = 0
        self.other_events = []

    def post_mouse(self, event_type, x, y, button, click_count=1):
        event = (event_type, x, y, button, click_count)
        self.attempts.append(event)
        if event_type.endswith("_up"):
            self.up_attempts += 1
        if event_type in self.fail_on or (
            event_type.endswith("_up") and self.up_attempts == self.fail_up_number
        ):
            raise OSError("temporary posting failure")
        self.events.append(event)
        if event_type in self.fail_after_delivery:
            raise self.partial_failure_type("posting outcome is uncertain")

    def post_scroll(self, *args):
        self.other_events.append(("scroll", args))

    def post_hotkey(self, *args):
        self.other_events.append(("hotkey", args))


def test_failed_drag_release_retries_last_position_and_only_clears_after_success():
    native = RecoverableNative()
    controller = MacOSInputController(native)
    assert controller.execute(ActionRequest("drag_start", x=10, y=20)).executed
    assert controller.execute(ActionRequest("drag", x=30, y=40)).executed
    native.fail_on.add("left_up")

    assert not controller.release_drag().executed
    assert controller._dragging
    assert not controller.release_drag().executed

    native.fail_on.clear()
    assert controller.release_drag().executed
    assert not controller._dragging
    assert controller.release_drag().executed
    assert native.events == [
        ("left_down", 10, 20, "left", 1),
        ("left_dragged", 30, 40, "left", 1),
        ("left_up", 30, 40, "left", 1),
    ]
    assert len([event for event in native.attempts if event[0] == "left_up"]) == 3


@pytest.mark.parametrize(
    ("action", "button"),
    [("left_click", "left"), ("right_click", "right"), ("middle_click", "center")],
)
def test_stop_recovers_failed_click_release_with_original_button_and_position(action, button):
    native = RecoverableNative()
    native.fail_on.add(f"{button}_up")
    controller = MacOSInputController(native)

    assert not controller.execute(ActionRequest(action, x=12, y=24)).executed
    assert not controller.release_drag().executed
    native.fail_on.clear()
    assert controller.release_drag().executed
    assert controller.release_drag().executed
    assert native.events == [
        (f"{button}_down", 12, 24, button, 1),
        (f"{button}_up", 12, 24, button, 1),
    ]


@pytest.mark.parametrize(
    "next_request",
    [
        ActionRequest("left_click", x=50, y=60),
        ActionRequest("right_click", x=50, y=60),
        ActionRequest("drag_start", x=50, y=60),
        ActionRequest("move_cursor", x=50, y=60),
        ActionRequest("scroll_down", x=50, y=60),
        ActionRequest("custom_hotkey", hotkey="cmd+c"),
    ],
)
def test_unrecovered_click_release_blocks_new_input(next_request):
    native = RecoverableNative()
    native.fail_on.add("left_up")
    controller = MacOSInputController(native)
    assert not controller.execute(ActionRequest("left_click", x=10, y=20)).executed

    result = controller.execute(next_request)

    assert not result.executed
    assert result.error_code == "unavailable"
    assert native.events == [("left_down", 10, 20, "left", 1)]
    assert native.attempts[-1] == ("left_up", 10, 20, "left", 1)
    assert native.other_events == []


def test_next_click_recovers_old_release_before_a_new_press_and_starts_a_fresh_run():
    native = RecoverableNative()
    native.fail_on.add("left_up")
    controller = MacOSInputController(native, clock=lambda: 1.0)
    assert not controller.execute(ActionRequest("left_click", x=10, y=20)).executed

    native.fail_on.clear()
    assert controller.execute(ActionRequest("left_click", x=10, y=20)).executed
    assert native.events == [
        ("left_down", 10, 20, "left", 1),
        ("left_up", 10, 20, "left", 1),
        ("left_down", 10, 20, "left", 1),
        ("left_up", 10, 20, "left", 1),
    ]


def test_partially_delivered_failed_drag_press_remains_releasable():
    native = RecoverableNative()
    native.fail_after_delivery.add("left_down")
    native.fail_on.add("left_up")
    controller = MacOSInputController(native)

    assert not controller.execute(ActionRequest("drag_start", x=10, y=20)).executed
    assert not controller._dragging
    assert not controller.release_drag().executed
    native.fail_on.clear()
    assert controller.release_drag().executed
    assert native.events == [
        ("left_down", 10, 20, "left", 1),
        ("left_up", 10, 20, "left", 1),
    ]


def test_adapter_type_error_after_delivery_does_not_repeat_mouse_down():
    native = RecoverableNative()
    native.fail_after_delivery.add("left_down")
    native.partial_failure_type = TypeError
    controller = MacOSInputController(native)

    assert not controller.execute(ActionRequest("left_click", x=10, y=20)).executed
    assert native.events == [
        ("left_down", 10, 20, "left", 1),
        ("left_up", 10, 20, "left", 1),
    ]
    assert controller.release_drag().executed
    assert len(native.events) == 2


def test_failed_drag_move_and_release_prevent_continued_drag_until_recovery():
    native = RecoverableNative()
    controller = MacOSInputController(native)
    assert controller.execute(ActionRequest("drag_start", x=10, y=20)).executed
    native.fail_on.update({"left_dragged", "left_up"})
    assert not controller.execute(ActionRequest("drag", x=30, y=40)).executed
    attempts = len(native.attempts)

    assert not controller.execute(ActionRequest("drag", x=50, y=60)).executed
    assert native.attempts[attempts:] == [("left_up", 10, 20, "left", 1)]

    native.fail_on.clear()
    result = controller.execute(ActionRequest("drag", x=70, y=80))
    assert not result.executed
    assert result.error_code == "drag_not_started"
    assert native.events[-1] == ("left_up", 10, 20, "left", 1)


@pytest.mark.parametrize("failed_up", [1, 2])
def test_partial_double_click_retains_only_unfinished_release(failed_up):
    native = RecoverableNative()
    native.fail_up_number = failed_up
    controller = MacOSInputController(native)

    assert not controller.execute(ActionRequest("double_click", x=12, y=24)).executed
    assert len([event for event in native.events if event[0] == "left_down"]) == failed_up
    assert controller.release_drag().executed
    assert controller.release_drag().executed
    assert len([event for event in native.events if event[0] == "left_up"]) == failed_up
    assert native.events[-1] == ("left_up", 12, 24, "left", 2 if failed_up == 1 else 1)


def test_drag_end_without_coordinates_releases_at_last_successful_position():
    native = RecoverableNative()
    controller = MacOSInputController(native)
    assert controller.execute(ActionRequest("drag_start", x=10, y=20)).executed
    assert controller.execute(ActionRequest("drag", x=30, y=40)).executed

    assert controller.execute(ActionRequest("drag_end")).executed
    assert native.events[-1] == ("left_up", 30, 40, "left", 1)

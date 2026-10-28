"""Pointer events must be real clicks, and a failed post must never strand a button.

Two defects are pinned here:

* ``double_click`` posted two independent down/up pairs. macOS derives "double
  click" from ``kCGMouseEventClickState``, so apps saw two single clicks and
  double-click targets never opened.
* ``execute`` posted the press and the release with no error handling. When the
  process may no longer post events (Accessibility revoked mid-session) the
  press could land and the release could fail, leaving the whole system with a
  mouse button held down that the user cannot clear.
"""

from platform_services.contracts import ActionRequest
from platform_services.macos.input_controller import MacOSInputController


class RecordingNative:
    """Accepts the optional click state and records what was posted."""

    def __init__(self, fail_on=()):
        self.events = []
        self.fail_on = set(fail_on)

    def post_mouse(self, event_type, x, y, button, click_count=1):
        if event_type in self.fail_on:
            raise OSError("events can no longer be posted")
        self.events.append((event_type, click_count))

    def post_hotkey(self, hotkey):
        return None

    def post_scroll(self, vertical, horizontal):
        return None


def test_double_click_carries_the_click_state_macos_reads():
    native = RecordingNative()

    result = MacOSInputController(native).execute(
        ActionRequest(action="double_click", x=12, y=24)
    )

    assert result.executed is True
    # press/release at click state 2, then a normal click, is one double click.
    assert native.events == [
        ("left_down", 2),
        ("left_up", 2),
        ("left_down", 1),
        ("left_up", 1),
    ]


def test_a_single_click_never_sets_a_multi_click_state():
    native = RecordingNative()

    MacOSInputController(native).execute(ActionRequest(action="left_click", x=1, y=1))

    assert native.events == [("left_down", 1), ("left_up", 1)]


def test_a_failed_release_is_reported_instead_of_claimed_as_success():
    native = RecordingNative(fail_on={"left_up"})

    result = MacOSInputController(native).execute(
        ActionRequest(action="left_click", x=1, y=1)
    )

    assert result.executed is False
    assert result.error_code == "unavailable"


def test_a_failed_press_does_not_leave_the_controller_holding_a_drag():
    native = RecordingNative(fail_on={"left_down"})
    controller = MacOSInputController(native)

    result = controller.execute(ActionRequest(action="drag_start", x=1, y=1))

    assert result.executed is False
    # No press was delivered, so the controller must not believe a drag is open.
    assert controller._dragging is False
    assert controller.release_drag().executed is True


def test_a_failed_drag_move_releases_the_button_it_is_holding():
    native = RecordingNative(fail_on={"left_dragged"})
    controller = MacOSInputController(native)
    controller.execute(ActionRequest(action="drag_start", x=1, y=1))

    result = controller.execute(ActionRequest(action="drag", x=2, y=2))

    assert result.executed is False
    # The press is already out; it must be paired rather than stranded.
    assert controller._dragging is False
    assert ("left_up", 1) in native.events


def test_a_native_adapter_without_click_state_still_receives_the_event():
    """Click state is a refinement, not a contract requirement."""

    class LegacyNative:
        def __init__(self):
            self.events = []

        def post_mouse(self, event_type, x, y, button):
            self.events.append((event_type, x, y, button))

        def post_hotkey(self, hotkey):
            return None

        def post_scroll(self, vertical, horizontal):
            return None

    native = LegacyNative()
    result = MacOSInputController(native).execute(
        ActionRequest(action="left_click", x=3, y=4)
    )

    assert result.executed is True
    assert native.events == [("left_down", 3, 4, "left"), ("left_up", 3, 4, "left")]

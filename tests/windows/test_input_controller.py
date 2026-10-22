import pytest

from platform_services.contracts import ActionRequest
from platform_services.windows.input_controller import WindowsInputController


class RecordingNative:
    def __init__(self):
        self.events = []

    def move_to(self, x, y):
        self.events.append(("move", x, y))

    def hotkey(self, shortcut):
        self.events.append(("hotkey", shortcut))


def test_windows_controller_moves_pointer_through_native_facade():
    native = RecordingNative()

    result = WindowsInputController(native).execute(ActionRequest(action="move_cursor", x=12, y=24))

    assert result.executed is True
    assert native.events == [("move", 12, 24)]


def test_windows_controller_rejects_malformed_hotkeys_without_native_injection():
    native = RecordingNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="ctrl+bogus+p")
    )

    assert result.executed is False
    assert result.error_code == "invalid_hotkey"
    assert native.events == []


def test_windows_controller_canonicalizes_windows_hotkeys_before_native_injection():
    native = RecordingNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="windows + shift + P")
    )

    assert result.executed is True
    assert native.events == [("hotkey", "shift+win+p")]


def test_windows_controller_rejects_macos_only_modifier_without_native_injection():
    native = RecordingNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="command+shift+p")
    )

    assert result.executed is False
    assert result.error_code == "invalid_hotkey"
    assert native.events == []


def test_windows_controller_reports_unsupported_action_without_success():
    result = WindowsInputController.for_test().execute(ActionRequest(action="not_real"))

    assert result.executed is False
    assert result.reason


class ActionNative:
    """Fake facade for the full pointer/keyboard action surface."""

    def __init__(self, failing=()):
        self.events = []
        self.failing = set(failing)

    def _guard(self, name):
        if name in self.failing:
            raise RuntimeError("injection blocked")

    def move_to(self, x, y):
        self._guard("move_to")
        self.events.append(("move", x, y))

    def mouse_down(self, button="left", x=None, y=None):
        self._guard("mouse_down")
        self.events.append(("down", button, x, y))

    def mouse_up(self, button="left", x=None, y=None):
        self._guard("mouse_up")
        self.events.append(("up", button))

    def scroll(self, vertical, horizontal=0):
        self._guard("scroll")
        self.events.append(("scroll", vertical, horizontal))

    def hotkey(self, chord):
        self._guard("hotkey")
        self.events.append(("hotkey", chord))


def test_left_click_presses_and_releases_at_the_requested_point():
    native = ActionNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="left_click", x=12, y=24)
    )

    assert result.executed is True
    assert native.events == [("down", "left", 12, 24), ("up", "left")]


def test_right_and_middle_clicks_use_the_matching_button():
    native = ActionNative()
    controller = WindowsInputController(native)

    controller.execute(ActionRequest(action="right_click", x=1, y=2))
    controller.execute(ActionRequest(action="middle_click", x=1, y=2))

    assert native.events == [
        ("down", "right", 1, 2),
        ("up", "right"),
        ("down", "middle", 1, 2),
        ("up", "middle"),
    ]


def test_double_click_presses_twice():
    native = ActionNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="double_click", x=5, y=6)
    )

    assert result.executed is True
    assert native.events == [
        ("down", "left", 5, 6),
        ("up", "left"),
        ("down", "left", 5, 6),
        ("up", "left"),
    ]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("scroll_up", (3, 0)),
        ("scroll_down", (-3, 0)),
        ("scroll_left", (0, -3)),
        ("scroll_right", (0, 3)),
    ],
)
def test_scroll_directions_map_to_contract_signs(action, expected):
    native = ActionNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action=action, x=1, y=1, scroll_amount=3)
    )

    assert result.executed is True
    assert native.events == [("scroll", *expected)]


def test_scroll_defaults_to_one_notch():
    native = ActionNative()

    WindowsInputController(native).execute(
        ActionRequest(action="scroll_down", x=1, y=1, scroll_amount=0)
    )

    assert native.events == [("scroll", -1, 0)]


def test_drag_lifecycle_presses_once_moves_and_releases_once():
    native = ActionNative()
    controller = WindowsInputController(native)

    controller.execute(ActionRequest(action="drag_start", x=10, y=20))
    controller.execute(ActionRequest(action="drag_start", x=11, y=21))
    controller.execute(ActionRequest(action="drag", x=30, y=40))
    controller.execute(ActionRequest(action="drag_end", x=30, y=40))

    assert native.events == [
        ("down", "left", 10, 20),
        ("move", 30, 40),
        ("up", "left"),
    ]


def test_release_drag_is_idempotent():
    native = ActionNative()
    controller = WindowsInputController(native)
    controller.execute(ActionRequest(action="drag_start", x=1, y=2))

    assert controller.release_drag().executed is True
    assert controller.release_drag().executed is True

    assert native.events == [("down", "left", 1, 2), ("up", "left")]


def test_release_without_a_drag_touches_nothing():
    native = ActionNative()

    assert WindowsInputController(native).release_drag().executed is True
    assert native.events == []


def test_drag_without_start_is_rejected_before_moving_the_pointer():
    native = ActionNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="drag", x=5, y=5)
    )

    assert result.executed is False
    assert result.error_code == "drag_not_started"
    assert native.events == []


def test_failed_drag_start_does_not_leave_a_phantom_drag():
    native = ActionNative(failing={"mouse_down"})
    controller = WindowsInputController(native)

    started = controller.execute(ActionRequest(action="drag_start", x=1, y=2))
    dragged = controller.execute(ActionRequest(action="drag", x=3, y=4))

    assert started.executed is False
    assert started.error_code == "input_unavailable"
    assert dragged.error_code == "drag_not_started"
    assert native.events == []


def test_failed_release_keeps_the_drag_so_the_next_attempt_can_release():
    native = ActionNative(failing={"mouse_up"})
    controller = WindowsInputController(native)
    controller.execute(ActionRequest(action="drag_start", x=1, y=2))

    first = controller.release_drag()
    assert first.executed is False
    assert first.error_code == "input_unavailable"

    native.failing.clear()
    second = controller.release_drag()

    assert second.executed is True
    assert native.events == [("down", "left", 1, 2), ("up", "left")]


def test_pointer_actions_require_coordinates():
    native = ActionNative()

    result = WindowsInputController(native).execute(ActionRequest(action="left_click", x=1))

    assert result.executed is False
    assert result.error_code == "missing_coordinates"
    assert native.events == []


def test_blocked_injection_is_reported_as_input_unavailable():
    native = ActionNative(failing={"mouse_down"})

    result = WindowsInputController(native).execute(
        ActionRequest(action="left_click", x=1, y=2)
    )

    assert result.executed is False
    assert result.error_code == "input_unavailable"
    assert native.events == []


def test_hotkey_is_forwarded_as_a_canonical_chord():
    native = ActionNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="Ctrl + Alt + Delete")
    )

    assert result.executed is True
    assert native.events == [("hotkey", "ctrl+alt+delete")]


def test_empty_hotkey_is_rejected_without_injection():
    native = ActionNative()

    result = WindowsInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="")
    )

    assert result.executed is False
    assert result.error_code == "missing_hotkey"
    assert native.events == []


def test_supported_actions_cover_every_pointer_and_keyboard_action():
    assert WindowsInputController.for_test().supported_actions == frozenset(
        {
            "move_cursor",
            "left_click",
            "right_click",
            "middle_click",
            "double_click",
            "drag_start",
            "drag",
            "drag_end",
            "scroll_up",
            "scroll_down",
            "scroll_left",
            "scroll_right",
            "custom_hotkey",
        }
    )

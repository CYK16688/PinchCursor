from platform_services.contracts import ActionRequest
from platform_services.macos.input_controller import MacOSInputController


class RecordingNative:
    def __init__(self):
        self.events = []
        self.hotkeys = []
        self.scrolls = []

    def post_mouse(self, event_type, x, y, button):
        self.events.append((event_type, x, y, button))

    def post_hotkey(self, hotkey):
        self.hotkeys.append(hotkey)

    def post_scroll(self, vertical, horizontal):
        self.scrolls.append((vertical, horizontal))


def test_release_drag_posts_mouse_up_once_after_drag_start():
    native = RecordingNative()
    controller = MacOSInputController(native)

    controller.execute(ActionRequest(action="drag_start", x=30, y=40))
    first = controller.release_drag()
    second = controller.release_drag()

    assert first.executed is True
    assert second.executed is True
    assert native.events == [
        ("left_down", 30, 40, "left"),
        ("left_up", 30, 40, "left"),
    ]


def test_pointer_move_posts_normalized_mouse_event():
    native = RecordingNative()

    result = MacOSInputController(native).execute(
        ActionRequest(action="move_cursor", x=12, y=24)
    )

    assert result.executed is True
    assert native.events == [("move", 12, 24, "left")]


def test_middle_click_posts_center_mouse_down_and_up_events():
    native = RecordingNative()

    result = MacOSInputController(native).execute(
        ActionRequest(action="middle_click", x=12, y=24)
    )

    assert result.executed is True
    assert native.events == [
        ("center_down", 12, 24, "center"),
        ("center_up", 12, 24, "center"),
    ]


def test_scroll_down_posts_negative_vertical_amount():
    native = RecordingNative()

    result = MacOSInputController(native).execute(
        ActionRequest(action="scroll_down", x=12, y=24, scroll_amount=3)
    )

    assert result.executed is True
    assert native.scrolls == [(-3, 0)]


def test_custom_hotkey_dispatches_configured_command_shortcut():
    native = RecordingNative()

    result = MacOSInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="cmd+space")
    )

    assert result.executed is True
    assert native.hotkeys == ["cmd+space"]


def test_custom_hotkey_native_validation_failure_does_not_inject_events():
    class RejectingNative(RecordingNative):
        def post_hotkey(self, hotkey):
            raise ValueError("invalid shortcut")

    native = RejectingNative()

    result = MacOSInputController(native).execute(
        ActionRequest(action="custom_hotkey", hotkey="cmd+bogus+p")
    )

    assert result.executed is False
    assert result.error_code == "invalid_hotkey"
    assert native.hotkeys == []


def test_unimplemented_platform_action_reports_non_execution():
    native = RecordingNative()

    result = MacOSInputController(native).execute(ActionRequest(action="lock_screen"))

    assert result.executed is False
    assert result.reason

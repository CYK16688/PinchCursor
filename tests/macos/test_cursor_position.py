"""Read-only cursor boundary tests; no native frameworks or events are used."""

from types import SimpleNamespace

import pytest

from platform_services.macos.input_controller import MacOSInputController
from platform_services.macos.native import MacOSNativeFacade
from platform_services.null import UnavailableInputController


def forbidden_input(*_args):
    raise AssertionError("Reading cursor position must not inject input")


def native_with_point(point):
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)
    event = object()
    calls = []

    def create(source):
        calls.append(("create", source))
        return event

    def location(received_event):
        assert received_event is event
        calls.append(("location",))
        return point

    native.quartz = SimpleNamespace(
        CGEventCreate=create,
        CGEventGetLocation=location,
        CGEventPost=forbidden_input,
        CGEventCreateMouseEvent=forbidden_input,
    )
    return native, calls


def test_cursor_read_preserves_negative_and_fractional_screen_coordinates():
    point = SimpleNamespace(x=-120.5, y=42.25)
    native, calls = native_with_point(point)
    controller = MacOSInputController(native)

    assert controller.cursor_position() == (-120.5, 42.25)
    point.x = 140
    assert controller.cursor_position() == (140.0, 42.25)
    assert calls == [("create", None), ("location",)] * 2


@pytest.mark.parametrize("point", [None, object(), SimpleNamespace(x=float("nan"), y=2),
                                   SimpleNamespace(x=1, y=float("inf")),
                                   SimpleNamespace(x="5", y=2)])
def test_native_invalid_location_is_unavailable(point):
    native, _ = native_with_point(point)
    assert native.cursor_position() is None


def test_native_failed_event_creation_does_not_try_reading_or_posting():
    native, calls = native_with_point(SimpleNamespace(x=1, y=2))
    native.quartz.CGEventCreate = lambda _: None
    assert native.cursor_position() is None
    assert calls == []


def test_native_unavailable_api_is_safe():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)
    native.quartz = SimpleNamespace(CGEventCreate=forbidden_input)
    assert native.cursor_position() is None


@pytest.mark.parametrize("value", [None, "12", (1,), (1, 2, 3), (True, 1),
                                  ("1", "2"), (float("inf"), 1), (1, float("nan"))])
def test_controller_rejects_malformed_native_result(value):
    native = SimpleNamespace(post_mouse=forbidden_input, cursor_position=lambda: value)
    assert MacOSInputController(native).cursor_position() is None


def test_old_native_fake_without_cursor_getter_still_works():
    controller = MacOSInputController(SimpleNamespace(post_mouse=forbidden_input))
    assert controller.cursor_position() is None


def test_controller_read_failure_is_safe():
    native = SimpleNamespace(post_mouse=forbidden_input, cursor_position=forbidden_input)
    assert MacOSInputController(native).cursor_position() is None


def test_unavailable_controller_has_no_cursor_position():
    assert UnavailableInputController("unsupported").cursor_position() is None

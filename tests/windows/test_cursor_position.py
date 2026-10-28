"""Fake user32 cursor reads; no Windows library is loaded or input posted."""

import ctypes
from types import SimpleNamespace

import pytest

from platform_services.windows.input_controller import WindowsInputController
from platform_services.windows.native import POINT, WindowsApiBinding, WindowsNativeFacade


def forbidden_input(*_args):
    raise AssertionError("Reading cursor position must not inject input")


def binding_with_cursor(x, y, *, succeeds=True):
    calls = []

    def get_cursor(pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(POINT)).contents
        point.x, point.y = x, y
        calls.append((x, y))
        return int(succeeds)

    binding = WindowsApiBinding.__new__(WindowsApiBinding)
    binding._user32 = SimpleNamespace(GetCursorPos=get_cursor, SendInput=forbidden_input)
    return binding, calls


def test_cursor_read_uses_user32_point_and_preserves_negative_coordinates():
    binding, calls = binding_with_cursor(-1440, 680)
    native = WindowsNativeFacade(binding)
    controller = WindowsInputController(native)

    assert controller.cursor_position() == (-1440.0, 680.0)
    assert calls == [(-1440, 680)]


def test_unsuccessful_get_cursor_pos_does_not_return_zero_or_partial_coordinates():
    binding, _ = binding_with_cursor(12, 34, succeeds=False)
    assert WindowsNativeFacade(binding).cursor_position() is None


def test_cursor_binding_signature_uses_pointer_to_point_and_32_bit_bool():
    binding = WindowsApiBinding.__new__(WindowsApiBinding)
    binding._user32 = SimpleNamespace(**{
        name: SimpleNamespace() for name in (
            "SendInput", "GetAsyncKeyState", "GetCursorPos", "GetSystemMetrics",
            "WindowFromPoint", "GetClassNameW",
        )
    })
    binding._configure_signatures()

    assert binding._user32.GetCursorPos.argtypes == (ctypes.POINTER(POINT),)
    assert binding._user32.GetCursorPos.restype is ctypes.c_int32
    assert ctypes.sizeof(POINT) == 8


def test_missing_or_failing_user32_cursor_api_is_safe():
    binding = WindowsApiBinding.__new__(WindowsApiBinding)
    binding._user32 = SimpleNamespace()
    assert binding.cursor_position() is None
    binding._user32.GetCursorPos = forbidden_input
    assert binding.cursor_position() is None


@pytest.mark.parametrize("value", [None, "12", (1,), (1, 2, 3), (True, 1),
                                  ("1", "2"), (float("inf"), 1), (1, float("nan"))])
def test_invalid_native_and_binding_positions_are_unavailable(value):
    provider = SimpleNamespace(cursor_position=lambda: value)
    assert WindowsNativeFacade(provider).cursor_position() is None
    assert WindowsInputController(provider).cursor_position() is None


def test_old_binding_and_native_fakes_without_cursor_getter_still_work():
    assert WindowsNativeFacade(SimpleNamespace()).cursor_position() is None
    assert WindowsInputController(SimpleNamespace()).cursor_position() is None
    assert WindowsInputController.for_test().cursor_position() is None


def test_failed_native_and_binding_reads_are_unavailable():
    provider = SimpleNamespace(cursor_position=forbidden_input)
    assert WindowsNativeFacade(provider).cursor_position() is None
    assert WindowsInputController(provider).cursor_position() is None

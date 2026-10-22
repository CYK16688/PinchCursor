"""Fake-binding contract tests for the ctypes Windows input facade.

These run on macOS: the facade builds real ``INPUT`` structures and hands them to
an injected binding, so flag/chord/coordinate decisions are verified without
loading user32. Whether Windows *accepts* the input is a separate, manual check.
"""

import ctypes
import sys

import pytest

from platform_services.windows.native import (
    INPUT,
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_HWHEEL,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_VIRTUALDESK,
    MOUSEEVENTF_WHEEL,
    WINDOWS_MODIFIER_KEYCODES,
    WINDOWS_TERMINAL_KEYCODES,
    WindowsNativeFacade,
)
from utils.windows_hotkey_validation import TERMINAL_KEYS

_BUTTON_FLAGS = (
    MOUSEEVENTF_LEFTDOWN
    | MOUSEEVENTF_LEFTUP
    | MOUSEEVENTF_RIGHTDOWN
    | MOUSEEVENTF_MIDDLEDOWN
)

VK_CTRL = 0x11
VK_SHIFT = 0x10
VK_ALT = 0x12
VK_P = 0x50
VK_LEFT_ARROW = 0x25


class FakeBinding:
    """Records every batch instead of calling SendInput."""

    def __init__(self, bounds=(0, 0, 1920, 1080), window_class="", async_state=None, delivered=None):
        self.bounds = bounds
        self.window_class = window_class
        self.async_state = async_state or {}
        self.delivered = delivered
        self.batches = []
        self.queried_keys = []
        self.class_queries = []

    def send_inputs(self, inputs):
        self.batches.append(list(inputs))
        if self.delivered is not None:
            return self.delivered(len(inputs))
        return len(inputs)

    def async_key_state(self, virtual_key):
        self.queried_keys.append(virtual_key)
        return self.async_state.get(virtual_key, 0)

    def virtual_screen_bounds(self):
        return self.bounds

    def window_class_at_point(self, x, y):
        self.class_queries.append((x, y))
        if isinstance(self.window_class, Exception):
            raise self.window_class
        return self.window_class

    @property
    def last_batch(self):
        return self.batches[-1]


def _facade(binding=None):
    return WindowsNativeFacade(binding or FakeBinding())


def test_input_struct_matches_the_win32_abi_for_this_pointer_width():
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    expected_size = 40 if pointer_size == 8 else 28

    assert ctypes.sizeof(INPUT) == expected_size


def test_pointer_move_uses_virtual_desktop_absolute_coordinates():
    binding = FakeBinding()
    facade = _facade(binding)

    facade.move_to(0, 0)
    facade.move_to(1919, 1079)

    assert [record.u.mi.dwFlags for record in binding.batches[0]] == [
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    ]
    assert (binding.batches[0][0].u.mi.dx, binding.batches[0][0].u.mi.dy) == (0, 0)
    assert (binding.batches[1][0].u.mi.dx, binding.batches[1][0].u.mi.dy) == (65535, 65535)


def test_pointer_move_maps_a_negative_origin_secondary_monitor():
    binding = FakeBinding(bounds=(-1920, 0, 3840, 1080))
    facade = _facade(binding)

    facade.move_to(-1920, 0)
    facade.move_to(1919, 1079)

    assert (binding.batches[0][0].u.mi.dx, binding.batches[0][0].u.mi.dy) == (0, 0)
    assert (binding.batches[1][0].u.mi.dx, binding.batches[1][0].u.mi.dy) == (65535, 65535)


def test_pointer_move_is_clamped_to_the_virtual_desktop():
    binding = FakeBinding()
    facade = _facade(binding)

    facade.move_to(-5000, 5000)
    facade.move_to(10**6, -(10**6))

    assert (binding.batches[0][0].u.mi.dx, binding.batches[0][0].u.mi.dy) == (0, 65535)
    assert (binding.batches[1][0].u.mi.dx, binding.batches[1][0].u.mi.dy) == (65535, 0)


def test_move_refuses_to_guess_when_screen_bounds_are_unavailable():
    facade = _facade(FakeBinding(bounds=(0, 0, 1, 1)))

    with pytest.raises(RuntimeError):
        facade.move_to(10, 10)


def test_left_button_down_moves_and_presses_in_one_batch_then_releases():
    binding = FakeBinding()
    facade = _facade(binding)

    facade.mouse_down("left", 100, 200)
    facade.mouse_up("left")

    assert [record.u.mi.dwFlags for record in binding.batches[0]] == [
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        MOUSEEVENTF_LEFTDOWN,
    ]
    assert [record.u.mi.dwFlags for record in binding.batches[1]] == [MOUSEEVENTF_LEFTUP]


def test_right_and_middle_buttons_use_their_own_down_flags():
    binding = FakeBinding()
    facade = _facade(binding)

    facade.mouse_down("right")
    facade.mouse_down("middle")
    facade.mouse_down("center")

    assert [batch[0].u.mi.dwFlags for batch in binding.batches] == [
        MOUSEEVENTF_RIGHTDOWN,
        MOUSEEVENTF_MIDDLEDOWN,
        MOUSEEVENTF_MIDDLEDOWN,
    ]


def test_unknown_mouse_button_is_rejected_before_injection():
    binding = FakeBinding()

    with pytest.raises(ValueError):
        _facade(binding).mouse_down("side")

    assert binding.batches == []


def test_drag_movement_never_toggles_a_button_flag():
    binding = FakeBinding()
    facade = _facade(binding)

    facade.mouse_down("left", 10, 10)
    facade.move_to(20, 40)

    assert binding.last_batch[0].u.mi.dwFlags == (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    assert binding.last_batch[0].u.mi.dwFlags & _BUTTON_FLAGS == 0


def test_scroll_converts_notches_to_wheel_delta():
    binding = FakeBinding()
    facade = _facade(binding)

    facade.scroll(3)
    facade.scroll(0, -2)

    assert (binding.batches[0][0].u.mi.dwFlags, binding.batches[0][0].u.mi.mouseData) == (
        MOUSEEVENTF_WHEEL,
        360,
    )
    assert (binding.batches[1][0].u.mi.dwFlags, binding.batches[1][0].u.mi.mouseData) == (
        MOUSEEVENTF_HWHEEL,
        (-240) & 0xFFFFFFFF,
    )


def test_scroll_without_amount_sends_nothing():
    binding = FakeBinding()

    _facade(binding).scroll(0, 0)

    assert binding.batches == []


def test_hotkey_presses_modifiers_first_and_releases_in_reverse():
    binding = FakeBinding()

    _facade(binding).hotkey("ctrl+shift+p")

    keystrokes = [(record.u.ki.wVk, record.u.ki.dwFlags) for record in binding.last_batch]
    assert keystrokes == [
        (VK_CTRL, 0),
        (VK_SHIFT, 0),
        (VK_P, 0),
        (VK_P, KEYEVENTF_KEYUP),
        (VK_SHIFT, KEYEVENTF_KEYUP),
        (VK_CTRL, KEYEVENTF_KEYUP),
    ]


def test_hotkey_marks_navigation_keys_as_extended():
    binding = FakeBinding()

    _facade(binding).hotkey("alt+left")

    keystrokes = [(record.u.ki.wVk, record.u.ki.dwFlags) for record in binding.last_batch]
    assert keystrokes == [
        (VK_ALT, 0),
        (VK_LEFT_ARROW, KEYEVENTF_EXTENDEDKEY),
        (VK_LEFT_ARROW, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP),
        (VK_ALT, KEYEVENTF_KEYUP),
    ]


def test_hotkey_rejects_a_macos_only_modifier_without_injecting():
    binding = FakeBinding()

    with pytest.raises(ValueError):
        _facade(binding).hotkey("command+shift+p")

    assert binding.batches == []


def test_hotkey_rejects_an_unsupported_terminal_key_without_injecting():
    binding = FakeBinding()

    with pytest.raises(ValueError):
        _facade(binding).hotkey("ctrl+bogus")

    assert binding.batches == []


def test_keyboard_table_covers_every_validated_terminal_key():
    assert TERMINAL_KEYS <= set(WINDOWS_TERMINAL_KEYCODES)
    keycodes = list(WINDOWS_TERMINAL_KEYCODES.values())
    assert len(keycodes) == len(set(keycodes))
    assert all(0 < keycode < 0x100 for keycode in keycodes)
    assert {chr(ord("a") + offset) for offset in range(26)} <= set(WINDOWS_TERMINAL_KEYCODES)


def test_modifier_table_reports_both_physical_keys_for_polling():
    assert set(WINDOWS_MODIFIER_KEYCODES) == {"ctrl", "alt", "shift", "win"}
    for keycodes in WINDOWS_MODIFIER_KEYCODES.values():
        assert isinstance(keycodes, frozenset)
        assert len(keycodes) == 2


def test_key_polling_reads_the_high_bit_only():
    binding = FakeBinding(async_state={0xA2: 0x8000, 0xA3: 0x0001, 0x5B: 0x8001})
    facade = _facade(binding)

    assert facade.key_is_down(0xA2) is True
    assert facade.key_is_down(0xA3) is False
    assert facade.key_is_down(0x5B) is True
    assert binding.queried_keys == [0xA2, 0xA3, 0x5B]


def test_blocked_injection_raises_instead_of_reporting_success():
    binding = FakeBinding(delivered=lambda _count: 0)

    with pytest.raises(RuntimeError):
        _facade(binding).mouse_down("left", 5, 5)


def test_partially_blocked_injection_also_raises():
    binding = FakeBinding(delivered=lambda count: max(0, count - 1))

    with pytest.raises(RuntimeError):
        _facade(binding).hotkey("ctrl+p")


def test_role_lookup_maps_known_window_classes_and_ignores_unknown_ones():
    assert _facade(FakeBinding(window_class="Edit")).role_at_position(1, 2) == "Edit"
    assert _facade(FakeBinding(window_class="RICHEDIT50W")).role_at_position(1, 2) == "Edit"
    assert _facade(FakeBinding(window_class="Button")).role_at_position(1, 2) == "Button"
    assert _facade(FakeBinding(window_class="Chrome_WidgetWin_1")).role_at_position(1, 2) == ""


def test_role_lookup_fails_open_to_generic_on_native_errors():
    binding = FakeBinding(window_class=OSError("no desktop"))

    assert _facade(binding).role_at_position(0, 0) == ""
    assert binding.class_queries == [(0, 0)]


def test_camera_authorization_is_never_reported_as_granted():
    assert _facade().camera_authorization() == "not_determined"


def test_every_mapped_role_is_a_role_the_context_provider_understands():
    from platform_services.windows.native import WINDOW_CLASS_ROLES
    from platform_services.windows.ui_context import ROLE_CATEGORIES

    assert set(WINDOW_CLASS_ROLES.values()) <= set(ROLE_CATEGORIES)


def test_a_mapped_window_class_produces_a_specific_ui_category():
    from platform_services.windows.ui_context import WindowsUIContextProvider

    provider = WindowsUIContextProvider(_facade(FakeBinding(window_class="Edit")))

    context = provider.get_context(5, 5)

    assert context.category == "text_input"
    assert context.source == "uia"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows itself has user32 available")
def test_facade_without_an_injected_binding_fails_fast_off_windows():
    with pytest.raises(RuntimeError):
        WindowsNativeFacade()

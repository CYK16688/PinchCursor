"""ctypes-only Windows native bridge for the platform adapter layer.

Two layers live here so the adapter stays testable on non-Windows hosts:

``WindowsApiBinding``
    The only object that touches ``user32``. Every ctypes call, structure and
    constant used for input injection lives behind its four query/inject
    methods.

``WindowsNativeFacade``
    Pure-Python translation from semantic adapter calls (``move_to``,
    ``mouse_down``, ``scroll``, ``hotkey``, ``key_is_down``, ``role_at_position``)
    into ``INPUT`` records. It accepts an injected binding, so unit tests build
    real ``INPUT`` structures and inspect the resulting flags without ever
    loading user32.

Verification status: the flag/chord/coordinate contract is covered by
fake-binding tests that run on macOS. Whether Windows accepts the injected
input, and whether the foreground application reacts to it, still requires
manual validation on a Windows 10/11 host (UIPI blocks injection into elevated
windows, which this module reports as ``RuntimeError`` instead of pretending to
have clicked).

Two Windows-specific questions that only a real machine can answer:

* **DPI.** Absolute injection works in physical pixels while the app computes
  gesture targets from Qt's logical screen geometry. At 100% scaling they match;
  at 125%/150% the caller's coordinates need per-monitor DPI mapping, which
  requires an HWND and is therefore left to the coordinate pipeline rather than
  guessed here.
* **UIPI.** Injection into an elevated foreground window silently fails at the
  OS boundary. ``_send`` turns a short count into ``RuntimeError`` so the action
  reports failure instead of a phantom click.
"""

from __future__ import annotations

import ctypes
import sys

from utils.windows_hotkey_validation import normalize_windows_hotkey

# --- SendInput layout -------------------------------------------------------
#
# Fixed-width aliases instead of ctypes.wintypes: wintypes maps DWORD to
# c_ulong, which is 8 bytes off-Windows, so structure layout would differ from
# the real ABI on the host used for tests. Explicit widths keep sizeof(INPUT)
# identical to the Win32 ABI on every host (40 bytes on x64, 28 on x86).

DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

WHEEL_DELTA = 120

# Buttons are named after the shared contract vocabulary; "center" is accepted
# as an alias because the macOS adapter uses that spelling internally.
BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    "center": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# Virtual-key codes for the terminal keys accepted by
# utils.windows_hotkey_validation.TERMINAL_KEYS.
_NAMED_TERMINAL_KEYCODES = {
    "space": 0x20,
    "enter": 0x0D,
    "escape": 0x1B,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
}

WINDOWS_TERMINAL_KEYCODES = {
    **{chr(ord("a") + offset): 0x41 + offset for offset in range(26)},
    **{str(digit): 0x30 + digit for digit in range(10)},
    **{f"f{index}": 0x6F + index for index in range(1, 13)},
    **_NAMED_TERMINAL_KEYCODES,
}

# Polling checks both physical keys of a modifier pair, because
# GetAsyncKeyState reports the generic VK inconsistently across layouts.
WINDOWS_MODIFIER_KEYCODES = {
    "ctrl": frozenset({0xA2, 0xA3}),
    "alt": frozenset({0xA4, 0xA5}),
    "shift": frozenset({0xA0, 0xA1}),
    "win": frozenset({0x5B, 0x5C}),
}

# Injection presses the generic VK so either physical key is acceptable.
_GENERIC_MODIFIER_KEYCODES = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}

# Keys that require KEYEVENTF_EXTENDEDKEY to be seen as the navigation key
# rather than its numpad equivalent.
_EXTENDED_KEYCODES = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E})

# Best-effort Win32 window-class to UI role mapping. This is deliberately a
# heuristic: a real UIAutomation role query needs a COM/UIA client, which would
# add a dependency. Unknown classes return "" so the context provider falls back
# to the generic category instead of guessing.
WINDOW_CLASS_ROLES = {
    "edit": "Edit",
    "richedit": "Edit",
    "richedit20a": "Edit",
    "richedit20w": "Edit",
    "richedit50w": "Edit",
    "button": "Button",
    "combobox": "ComboBox",
    "comboboxex32": "ComboBox",
    "scrollbar": "ScrollBar",
    "msctls_trackbar32": "Slider",
    "syslistview32": "List",
    "systreeview32": "Tree",
    "listbox": "List",
}

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

_ASYNC_KEY_DOWN_MASK = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", DWORD),
        ("wParamL", WORD),
        ("wParamH", WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


def mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    """Build one mouse INPUT record."""
    record = INPUT()
    record.type = INPUT_MOUSE
    record.mi = MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=DWORD(int(data) & 0xFFFFFFFF),
                           dwFlags=int(flags), time=0, dwExtraInfo=0)
    return record


def key_input(virtual_key: int, down: bool, *, extended: bool = False) -> INPUT:
    """Build one keyboard INPUT record."""
    flags = 0
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if not down:
        flags |= KEYEVENTF_KEYUP
    record = INPUT()
    record.type = INPUT_KEYBOARD
    record.ki = KEYBDINPUT(wVk=int(virtual_key), wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return record


class WindowsApiBinding:
    """Direct ctypes binding to user32; the only object allowed to call it."""

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Windows user32 bindings require a Windows host")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        user32 = self._user32
        user32.SendInput.argtypes = (DWORD, ctypes.POINTER(INPUT), ctypes.c_int)
        user32.SendInput.restype = DWORD
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.WindowFromPoint.argtypes = (POINT,)
        user32.WindowFromPoint.restype = ctypes.c_void_p
        user32.GetClassNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        user32.GetClassNameW.restype = ctypes.c_int

    def send_inputs(self, inputs: list[INPUT]) -> int:
        """Insert a batch of INPUT records atomically; return how many landed."""
        if not inputs:
            return 0
        array = (INPUT * len(inputs))(*inputs)
        return int(self._user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)))

    def async_key_state(self, virtual_key: int) -> int:
        return int(self._user32.GetAsyncKeyState(int(virtual_key)))

    def virtual_screen_bounds(self) -> tuple[int, int, int, int]:
        metrics = self._user32.GetSystemMetrics
        return (
            int(metrics(SM_XVIRTUALSCREEN)),
            int(metrics(SM_YVIRTUALSCREEN)),
            int(metrics(SM_CXVIRTUALSCREEN)),
            int(metrics(SM_CYVIRTUALSCREEN)),
        )

    def window_class_at_point(self, x: int, y: int) -> str:
        window = self._user32.WindowFromPoint(POINT(int(x), int(y)))
        if not window:
            return ""
        buffer = ctypes.create_unicode_buffer(256)
        if self._user32.GetClassNameW(window, buffer, len(buffer)) == 0:
            return ""
        return buffer.value


class WindowsNativeFacade:
    """Injectable Windows native facade used by every Windows platform service."""

    def __init__(self, binding=None):
        self.binding = binding if binding is not None else WindowsApiBinding()

    # --- capability tables ------------------------------------------------

    @property
    def shortcut_keycodes(self) -> dict[str, int]:
        """Return the shared source-controlled virtual-key table."""
        return dict(WINDOWS_TERMINAL_KEYCODES)

    @property
    def shortcut_modifier_keycodes(self) -> dict[str, frozenset[int]]:
        return dict(WINDOWS_MODIFIER_KEYCODES)

    # --- pointer input ----------------------------------------------------

    def move_to(self, x: int, y: int) -> None:
        self._send([self._absolute_move(x, y)])

    def mouse_down(self, button: str = "left", x: int | None = None, y: int | None = None) -> None:
        """Press a mouse button, optionally moving to (x, y) in the same batch."""
        flags = self._button_down_flag(button)
        inputs = []
        if x is not None and y is not None:
            inputs.append(self._absolute_move(x, y))
        inputs.append(mouse_input(flags))
        self._send(inputs)

    def mouse_up(self, button: str = "left", x: int | None = None, y: int | None = None) -> None:
        flags = self._button_up_flag(button)
        inputs = []
        if x is not None and y is not None:
            inputs.append(self._absolute_move(x, y))
        inputs.append(mouse_input(flags))
        self._send(inputs)

    def scroll(self, vertical: int, horizontal: int = 0) -> None:
        """Scroll by wheel notches; positive is up/right, matching the contract."""
        inputs = []
        if vertical:
            inputs.append(mouse_input(MOUSEEVENTF_WHEEL, data=int(vertical) * WHEEL_DELTA))
        if horizontal:
            inputs.append(mouse_input(MOUSEEVENTF_HWHEEL, data=int(horizontal) * WHEEL_DELTA))
        if inputs:
            self._send(inputs)

    # --- keyboard input ---------------------------------------------------

    def hotkey(self, hotkey: str) -> None:
        """Inject a full press-and-release chord parsed from canonical text."""
        normalized = normalize_windows_hotkey(hotkey)
        parts = normalized.split("+")
        terminal = parts[-1]
        try:
            terminal_keycode = WINDOWS_TERMINAL_KEYCODES[terminal]
        except KeyError as error:
            raise ValueError(f"Unsupported Windows shortcut key: {terminal}") from error
        modifiers = parts[:-1]
        inputs = [
            key_input(_GENERIC_MODIFIER_KEYCODES[modifier], down=True) for modifier in modifiers
        ]
        extended = terminal_keycode in _EXTENDED_KEYCODES
        inputs.append(key_input(terminal_keycode, True, extended=extended))
        inputs.append(key_input(terminal_keycode, False, extended=extended))
        inputs.extend(
            key_input(_GENERIC_MODIFIER_KEYCODES[modifier], down=False)
            for modifier in reversed(modifiers)
        )
        self._send(inputs)

    def key_is_down(self, virtual_key: int) -> bool:
        """Poll physical key state without installing a keyboard hook."""
        return bool(self.binding.async_key_state(int(virtual_key)) & _ASYNC_KEY_DOWN_MASK)

    # --- UI context -------------------------------------------------------

    def role_at_position(self, x: int, y: int) -> str:
        """Return a UI role for the window class under the pointer, else ""."""
        try:
            class_name = self.binding.window_class_at_point(int(x), int(y))
        except Exception:
            return ""
        return WINDOW_CLASS_ROLES.get(str(class_name).lower(), "")

    # --- permissions ------------------------------------------------------

    def camera_authorization(self) -> str:
        """Report camera consent honestly.

        Windows only gates packaged (UWP) apps through the WinRT capability
        consent store; the registry-shaped consent data for desktop apps is
        per-user and keyed by hashed executable paths, which this adapter does
        not attempt to decode. Capturing therefore starts optimistically and a
        failure surfaces from ``VideoCapture``; we never claim GRANTED.
        """
        return "not_determined"

    # --- internals --------------------------------------------------------

    def _send(self, inputs: list[INPUT]) -> None:
        delivered = self.binding.send_inputs(inputs)
        if delivered != len(inputs):
            raise RuntimeError(
                f"Windows blocked {len(inputs) - delivered} of {len(inputs)} injected input events"
            )

    def _absolute_move(self, x: int, y: int) -> INPUT:
        dx, dy = self._absolute_coordinates(x, y)
        return mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, dx, dy)

    def _absolute_coordinates(self, x: int, y: int) -> tuple[int, int]:
        left, top, width, height = self.binding.virtual_screen_bounds()
        if width <= 1 or height <= 1:
            raise RuntimeError("Windows virtual screen bounds are unavailable")
        dx = int(round((int(x) - left) * 65535 / (width - 1)))
        dy = int(round((int(y) - top) * 65535 / (height - 1)))
        return max(0, min(65535, dx)), max(0, min(65535, dy))

    @staticmethod
    def _button_down_flag(button: str) -> int:
        try:
            return BUTTON_FLAGS[button][0]
        except KeyError as error:
            raise ValueError(f"Unsupported Windows mouse button: {button}") from error

    @staticmethod
    def _button_up_flag(button: str) -> int:
        try:
            return BUTTON_FLAGS[button][1]
        except KeyError as error:
            raise ValueError(f"Unsupported Windows mouse button: {button}") from error

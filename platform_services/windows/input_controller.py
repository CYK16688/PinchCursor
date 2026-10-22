from __future__ import annotations

from platform_services.contracts import ActionRequest, ActionResult
from utils.windows_hotkey_validation import normalize_windows_hotkey


SUPPORTED_ACTIONS = frozenset(
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

_CLICK_BUTTONS = {
    "left_click": "left",
    "right_click": "right",
    "middle_click": "middle",
}

_SCROLL_VECTORS = {
    "scroll_up": (1, 0),
    "scroll_down": (-1, 0),
    "scroll_left": (0, -1),
    "scroll_right": (0, 1),
}


class WindowsInputController:
    """Injectable Windows adapter; native imports stay out of shared modules."""

    def __init__(self, native):
        self.native = native
        self._dragging = False
        self._drag_position: tuple[int, int] | None = None

    @classmethod
    def for_test(cls):
        return cls(_UnavailableWindowsNative())

    @property
    def supported_actions(self) -> frozenset[str]:
        return SUPPORTED_ACTIONS

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.action not in self.supported_actions:
            return ActionResult(False, f"Unsupported Windows action: {request.action}", "unsupported_action")
        if request.action == "custom_hotkey":
            return self._execute_hotkey(request.hotkey)
        if request.x is None or request.y is None:
            return ActionResult(False, "Pointer coordinates are required", "missing_coordinates")
        try:
            return self._execute_pointer(request)
        except RuntimeError:
            # SendInput is blocked, most often by UIPI against an elevated
            # foreground window. Report it instead of claiming the action ran.
            return ActionResult(False, "Windows input is unavailable", "input_unavailable")

    def release_drag(self) -> ActionResult:
        """Release a started drag; safe and successful when nothing is dragging."""
        if not self._dragging:
            return ActionResult(True)
        try:
            self.native.mouse_up()
        except RuntimeError:
            # Keep the dragging flag so the next stop() retries the release
            # rather than silently leaving a mouse button held down.
            return ActionResult(False, "Windows input is unavailable", "input_unavailable")
        self._dragging = False
        self._drag_position = None
        return ActionResult(True)

    def _execute_hotkey(self, hotkey: str) -> ActionResult:
        if not hotkey:
            return ActionResult(False, "No shortcut configured", "missing_hotkey")
        try:
            normalized = normalize_windows_hotkey(hotkey)
        except (TypeError, ValueError):
            return ActionResult(False, "Invalid shortcut", "invalid_hotkey")
        try:
            self.native.hotkey(normalized)
        except RuntimeError:
            return ActionResult(False, "Windows input is unavailable", "input_unavailable")
        return ActionResult(True)

    def _execute_pointer(self, request: ActionRequest) -> ActionResult:
        action = request.action
        x, y = request.x, request.y

        if action == "move_cursor":
            self.native.move_to(x, y)
        elif action in _CLICK_BUTTONS:
            button = _CLICK_BUTTONS[action]
            self.native.mouse_down(button, x, y)
            self.native.mouse_up(button)
        elif action == "double_click":
            for _repeat in range(2):
                self.native.mouse_down("left", x, y)
                self.native.mouse_up("left")
        elif action == "drag_start":
            if not self._dragging:
                self.native.mouse_down("left", x, y)
                self._dragging = True
            self._drag_position = (x, y)
        elif action == "drag":
            if not self._dragging:
                return ActionResult(False, "No active drag", "drag_not_started")
            self.native.move_to(x, y)
            self._drag_position = (x, y)
        elif action == "drag_end":
            self._drag_position = (x, y)
            return self.release_drag()
        elif action in _SCROLL_VECTORS:
            amount = request.scroll_amount or 1
            vertical, horizontal = _SCROLL_VECTORS[action]
            self.native.scroll(vertical * amount, horizontal * amount)
        return ActionResult(True)


class _UnavailableWindowsNative:
    """Test double and last-resort fallback for non-Windows hosts."""

    def move_to(self, x, y):
        raise RuntimeError("Windows native input is unavailable on this host")

    def mouse_down(self, button="left", x=None, y=None):
        raise RuntimeError("Windows native input is unavailable on this host")

    def scroll(self, vertical, horizontal=0):
        raise RuntimeError("Windows native input is unavailable on this host")

    def hotkey(self, hotkey):
        raise RuntimeError("Windows native input is unavailable on this host")

    def mouse_up(self, button="left", x=None, y=None):
        # Releasing must never raise: shutdown paths call it unconditionally.
        pass

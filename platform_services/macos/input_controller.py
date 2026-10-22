from __future__ import annotations

from platform_services.contracts import ActionRequest, ActionResult


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


class MacOSInputController:
    def __init__(self, native):
        self.native = native
        self._dragging = False
        self._drag_position: tuple[int, int] | None = None

    @property
    def supported_actions(self) -> frozenset[str]:
        return SUPPORTED_ACTIONS

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.action not in self.supported_actions:
            return ActionResult(False, f"{request.action} is not implemented on macOS", "unsupported_action")

        if request.action == "custom_hotkey":
            if not request.hotkey:
                return ActionResult(False, "No shortcut configured", "missing_hotkey")
            try:
                self.native.post_hotkey(request.hotkey)
            except (TypeError, ValueError):
                return ActionResult(False, "Invalid shortcut", "invalid_hotkey")
            return ActionResult(True)

        if request.x is None or request.y is None:
            return ActionResult(False, "Pointer coordinates are required", "missing_coordinates")

        x, y = request.x, request.y
        if request.action == "move_cursor":
            self.native.post_mouse("move", x, y, "left")
        elif request.action == "left_click":
            self._click("left", x, y)
        elif request.action == "right_click":
            self._click("right", x, y)
        elif request.action == "middle_click":
            self._click("center", x, y)
        elif request.action == "double_click":
            self._click("left", x, y)
            self._click("left", x, y)
        elif request.action == "drag_start":
            if not self._dragging:
                self.native.post_mouse("left_down", x, y, "left")
                self._dragging = True
            self._drag_position = (x, y)
        elif request.action == "drag":
            if not self._dragging:
                return ActionResult(False, "No active drag", "drag_not_started")
            self.native.post_mouse("left_dragged", x, y, "left")
            self._drag_position = (x, y)
        elif request.action == "drag_end":
            self._drag_position = (x, y)
            return self.release_drag()
        elif request.action.startswith("scroll_"):
            amount = request.scroll_amount or 1
            direction = {
                "scroll_up": (amount, 0),
                "scroll_down": (-amount, 0),
                "scroll_left": (0, -amount),
                "scroll_right": (0, amount),
            }[request.action]
            self.native.post_scroll(*direction)
        return ActionResult(True)

    def release_drag(self) -> ActionResult:
        if not self._dragging:
            return ActionResult(True)
        x, y = self._drag_position or (0, 0)
        self.native.post_mouse("left_up", x, y, "left")
        self._dragging = False
        self._drag_position = None
        return ActionResult(True)

    def _click(self, button: str, x: int, y: int) -> None:
        event_prefix = {"left": "left", "right": "right", "center": "center"}[button]
        self.native.post_mouse(f"{event_prefix}_down", x, y, button)
        self.native.post_mouse(f"{event_prefix}_up", x, y, button)

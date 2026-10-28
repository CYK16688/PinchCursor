from __future__ import annotations

import time
from inspect import signature

from platform_services.contracts import ActionRequest, ActionResult, normalize_cursor_position


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
    # macOS decides "double click" from kCGMouseEventClickState, not from the
    # timing of separate click events. Two plain left clicks 200 ms apart are two
    # single clicks to every app; the second one has to carry click state 2. These
    # mirror NSEvent.doubleClickInterval (0.5 s) and the usual few-point slop.
    DOUBLE_CLICK_INTERVAL = 0.5
    CLICK_SLOP = 4
    MAX_CLICK_RUN = 3  # triple click is the most macOS itself tracks

    def __init__(self, native, clock=time.monotonic):
        self.native = native
        self._clock = clock
        # Inspect compatibility before sending an event. Catching TypeError and
        # retrying a down with fewer arguments can send it twice if the adapter
        # raised after delivering the first one.
        try:
            post_signature = signature(native.post_mouse)
        except (TypeError, ValueError):
            self._supports_click_count = True
        else:
            try:
                post_signature.bind("move", 0, 0, "left", 1)
            except TypeError:
                self._supports_click_count = False
            else:
                self._supports_click_count = True
        self._dragging = False
        self._drag_position: tuple[int, int] | None = None
        # An attempted down may have reached the OS even when posting raises.
        # Keep its matching up until the native adapter accepts it. This also
        # covers ordinary clicks, whose release can fail after a successful down.
        self._pending_releases: dict[str, tuple[int, int, int]] = {}
        self._release_required = False
        # button -> (when, where, how many clicks into the run)
        self._click_runs: dict[str, tuple[float, tuple[int, int], int]] = {}

    def _next_click_state(self, button: str, x: int, y: int) -> int:
        """Return the click state for this click: 1, then 2 for a fast repeat."""
        now = self._clock()
        previous = self._click_runs.get(button)
        state = 1
        if previous is not None:
            when, where, run = previous
            same_place = (
                abs(x - where[0]) <= self.CLICK_SLOP
                and abs(y - where[1]) <= self.CLICK_SLOP
            )
            if now - when <= self.DOUBLE_CLICK_INTERVAL and same_place:
                state = min(run + 1, self.MAX_CLICK_RUN)
        self._click_runs[button] = (now, (x, y), state)
        return state

    @property
    def supported_actions(self) -> frozenset[str]:
        return SUPPORTED_ACTIONS

    def cursor_position(self) -> tuple[float, float] | None:
        try:
            getter = getattr(self.native, "cursor_position", None)
            return normalize_cursor_position(getter()) if callable(getter) else None
        except Exception:
            # Cursor anchoring is optional; a failed read must never inject input.
            return None

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.action not in self.supported_actions:
            return ActionResult(False, f"{request.action} is not implemented on macOS", "unsupported_action")

        if request.action == "drag_end":
            # Releasing must still work after tracking has lost its coordinates.
            if self._dragging and request.x is not None and request.y is not None:
                self._remember_drag_position(request.x, request.y)
            return self.release_drag()

        continuing_drag = self._dragging and request.action in {"drag", "drag_start"}
        if self._pending_releases and (self._release_required or not continuing_drag):
            # Never issue another down (or an unrelated command) while a failed
            # release may still leave a button held in the destination app.
            result = self.release_drag()
            if not result.executed:
                return result

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
            if not self._post("move", x, y, "left"):
                return ActionResult(False, "Pointer move could not be sent", "unavailable")
        elif request.action == "left_click":
            # A fast repeat must carry an incremented click state or the second
            # press is just another single click. This is what makes two quick
            # pinches behave like a mouse double click.
            if not self._click("left", x, y, click_count=self._next_click_state("left", x, y)):
                return ActionResult(False, "Click could not be sent", "unavailable")
        elif request.action == "right_click":
            if not self._click("right", x, y, click_count=self._next_click_state("right", x, y)):
                return ActionResult(False, "Click could not be sent", "unavailable")
        elif request.action == "middle_click":
            if not self._click("center", x, y, click_count=self._next_click_state("center", x, y)):
                return ActionResult(False, "Click could not be sent", "unavailable")
        elif request.action == "double_click":
            # Two presses with the click state set to 2 and 1 is what macOS (and
            # every app listening for a double click) accepts as one gesture.
            if not (self._click("left", x, y, click_count=2)
                    and self._click("left", x, y, click_count=1)):
                return ActionResult(False, "Click could not be sent", "unavailable")
            # The pair above already delivered a complete double click; the next
            # press must not be counted as a third.
            self._click_runs.pop("left", None)
        elif request.action == "drag_start":
            if not self._dragging:
                self._pending_releases["left"] = (x, y, 1)
                if not self._post("left_down", x, y, "left"):
                    self.release_drag()
                    return ActionResult(False, "Pointer press could not be sent", "unavailable")
                self._dragging = True
            self._remember_drag_position(x, y)
        elif request.action == "drag":
            if not self._dragging:
                return ActionResult(False, "No active drag", "drag_not_started")
            if not self._post("left_dragged", x, y, "left"):
                # The button is already down; release it rather than leaving the
                # OS with a held mouse button the user cannot clear.
                self.release_drag()
                return ActionResult(False, "Pointer move could not be sent", "unavailable")
            self._remember_drag_position(x, y)
        elif request.action.startswith("scroll_"):
            amount = request.scroll_amount or 1
            direction = {
                "scroll_up": (amount, 0),
                "scroll_down": (-amount, 0),
                "scroll_left": (0, -amount),
                "scroll_right": (0, amount),
            }[request.action]
            try:
                self.native.post_scroll(*direction)
            except (OSError, RuntimeError):
                return ActionResult(False, "Scroll could not be sent", "unavailable")
        return ActionResult(True)

    def _post(self, event_type: str, x: int, y: int, button: str, click_count: int = 1) -> bool:
        """Post one mouse event, reporting failure instead of raising.

        A native adapter that predates click-state support only accepts the four
        positional fields; the click state is an optional refinement, not part of
        the contract, so it is dropped rather than failing the action.
        """
        try:
            if self._supports_click_count:
                self.native.post_mouse(event_type, x, y, button, click_count)
            else:
                self.native.post_mouse(event_type, x, y, button)
        except (OSError, RuntimeError, TypeError):
            return False
        return True

    def release_drag(self) -> ActionResult:
        """Release every outstanding press, retaining failures for the next stop.

        The public name is retained for callers, but an interrupted click owes
        a release just as a drag does. Successful retries consume that obligation
        once; a failed retry never reports a clean controller.
        """
        self._release_required = bool(self._pending_releases)
        for button in tuple(self._pending_releases):
            self._release_button(button)
        if self._pending_releases:
            return ActionResult(False, "Pointer release could not be sent", "unavailable")
        return ActionResult(True)

    def _remember_drag_position(self, x: int, y: int) -> None:
        self._drag_position = (x, y)
        self._pending_releases["left"] = (x, y, 1)

    def _release_button(self, button: str) -> bool:
        x, y, click_count = self._pending_releases[button]
        if not self._post(f"{button}_up", x, y, button, click_count):
            self._release_required = True
            return False
        del self._pending_releases[button]
        if button == "left":
            self._dragging = False
            self._drag_position = None
        self._release_required = bool(self._pending_releases)
        return True

    def _click(self, button: str, x: int, y: int, click_count: int = 1) -> bool:
        """Press and release one button, retaining any undelivered release."""
        self._pending_releases[button] = (x, y, click_count)
        pressed = self._post(f"{button}_down", x, y, button, click_count)
        # The release is attempted even when the press failed, because a partially
        # delivered press is exactly the case that strands a held button.
        released = self._release_button(button)
        if not (pressed and released):
            # A failed click cannot be reliable evidence for the next click run.
            self._click_runs.pop(button, None)
        return pressed and released

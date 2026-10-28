"""Pure state and timing policy for pointer-adjacent gesture feedback."""

from enum import StrEnum


class HudState(StrEnum):
    HIDDEN = "hidden"
    POINTER = "pointer"
    LOCKING = "locking"
    CLICKED = "clicked"
    DRAGGING = "dragging"
    SECONDARY_CLICK = "secondary_click"
    CONTEXTUAL = "contextual"
    ERROR = "error"


class HudController:
    """Tracks persistent and transient feedback without depending on Qt or native input."""

    MODES = ("quiet", "standard", "learn")

    TRANSIENT_DURATIONS = {
        HudState.CLICKED: 0.22,
        HudState.SECONDARY_CLICK: 0.22,
        HudState.CONTEXTUAL: 0.75,
        HudState.ERROR: 2.50,
    }

    # "Learn — continuous guidance" is the mode for someone still building the
    # muscle memory: the same feedback, held long enough to read while the hand
    # is moving. A mode that behaves exactly like "standard" is a control that
    # lies about what it does, so the difference is explicit here.
    LEARN_MULTIPLIER = 3.0
    LEARN_STATES = frozenset(
        {HudState.CLICKED, HudState.SECONDARY_CLICK, HudState.CONTEXTUAL}
    )

    def __init__(self, mode="standard"):
        self.mode = mode if mode in self.MODES else "standard"
        self._persistent_state = HudState.HIDDEN
        self._transient_state = HudState.HIDDEN
        self._transient_until = 0.0
        self.message = ""

    def show_pointer(self, now):
        # Quiet suppresses the continuous pointer badge. Learn keeps it: the
        # badge is the thing a new user needs in order to trust the hand-to-
        # pointer mapping before they understand where the anchors are.
        if self.mode != "quiet" and self._persistent_state is not HudState.DRAGGING:
            self._persistent_state = HudState.POINTER

    def show_locking(self, now):
        self._persistent_state = HudState.LOCKING

    def show_dragging(self, now):
        self._persistent_state = HudState.DRAGGING

    def hide_dragging(self):
        if self._persistent_state is HudState.DRAGGING:
            self._persistent_state = HudState.HIDDEN

    def hide_persistent(self):
        self._persistent_state = HudState.HIDDEN

    def show_click(self, now):
        self._show_transient(HudState.CLICKED, now)

    def show_secondary_click(self, now):
        self._show_transient(HudState.SECONDARY_CLICK, now)

    def show_contextual(self, message, now):
        self.message = message
        self._show_transient(HudState.CONTEXTUAL, now)

    def show_error(self, message, now):
        self.message = message
        self._show_transient(HudState.ERROR, now)

    def current_state(self, now):
        if self._transient_state is not HudState.HIDDEN and now < self._transient_until:
            return self._transient_state
        if self._transient_state is not HudState.HIDDEN:
            self._transient_state = HudState.HIDDEN
            self.message = ""
        return self._persistent_state

    def _show_transient(self, state, now):
        duration = self.TRANSIENT_DURATIONS[state]
        if self.mode == "learn" and state in self.LEARN_STATES:
            duration *= self.LEARN_MULTIPLIER
        self._transient_state = state
        self._transient_until = now + duration

from __future__ import annotations

from enum import StrEnum


class ActivationMode(StrEnum):
    GESTURE = "gesture"
    HOLD_SHORTCUT = "hold_shortcut"
    GESTURE_OR_SHORTCUT = "gesture_or_shortcut"
    ALWAYS = "always"


class SessionState(StrEnum):
    INACTIVE = "inactive"
    ARMED = "armed"
    POINTER = "pointer"


class ControlSession:
    """Pure gate between hand detection and desktop pointer actions."""

    def __init__(
        self,
        mode: ActivationMode,
        activation_gesture: str,
        exit_gesture: str,
        stability_seconds: float,
        no_hand_timeout_seconds: float,
        activation_template=None,
        exit_template=None,
        matcher=None,
    ):
        self.mode = ActivationMode(mode)
        self.activation_gesture = activation_gesture
        self.exit_gesture = exit_gesture
        self.stability_seconds = stability_seconds
        self.no_hand_timeout_seconds = no_hand_timeout_seconds
        self.activation_template = activation_template
        self.exit_template = exit_template
        self.matcher = matcher
        self.state = SessionState.INACTIVE
        self._activation_started_at: float | None = None
        self._last_hand_at: float | None = None

    def update(
        self,
        gesture: str,
        has_hand: bool,
        shortcut_held: bool,
        now: float,
        landmarks=None,
    ) -> SessionState:
        if has_hand:
            self._last_hand_at = now
        elif self._last_hand_at is not None and now - self._last_hand_at >= self.no_hand_timeout_seconds:
            self.reset()
            return self.state

        if self.mode is ActivationMode.ALWAYS:
            self.state = SessionState.POINTER if has_hand else SessionState.INACTIVE
            return self.state

        exit_template_matches = bool(
            self.exit_template and self.matcher and self.matcher.match(landmarks, self.exit_template)
        )
        exit_gesture_matches = (
            exit_template_matches
            if self.exit_template is not None
            else gesture == self.exit_gesture
        )
        if self.state is not SessionState.INACTIVE and exit_gesture_matches:
            self.reset()
            return self.state

        shortcut_active = shortcut_held and self.mode in {
            ActivationMode.HOLD_SHORTCUT,
            ActivationMode.GESTURE_OR_SHORTCUT,
        }
        if self.activation_template is not None:
            gesture_active = self._template_activation_ready(landmarks, now)
        else:
            gesture_active = self._gesture_activation_ready(gesture, now)

        if self.state is SessionState.INACTIVE:
            if shortcut_active or gesture_active:
                self.state = SessionState.ARMED
            return self.state

        if self.mode is ActivationMode.HOLD_SHORTCUT and not shortcut_held:
            self.reset()
            return self.state
        if self.mode is ActivationMode.GESTURE_OR_SHORTCUT and not shortcut_held and self._activation_started_at is None:
            self.reset()
            return self.state
        if gesture == "point" and has_hand:
            self.state = SessionState.POINTER
        return self.state

    def allows_pointer_actions(self) -> bool:
        return self.state in {SessionState.ARMED, SessionState.POINTER}

    def reset(self) -> None:
        self.state = SessionState.INACTIVE
        self._activation_started_at = None
        self._last_hand_at = None

    def _template_activation_ready(self, landmarks, now: float) -> bool:
        if self.mode not in {ActivationMode.GESTURE, ActivationMode.GESTURE_OR_SHORTCUT}:
            return False
        if not self.matcher or not self.matcher.match(landmarks, self.activation_template):
            self._activation_started_at = None
            return False
        if self._activation_started_at is None:
            self._activation_started_at = now
            return self.stability_seconds <= 0
        return now - self._activation_started_at >= self.stability_seconds

    def _gesture_activation_ready(self, gesture: str, now: float) -> bool:
        if self.mode not in {ActivationMode.GESTURE, ActivationMode.GESTURE_OR_SHORTCUT}:
            return False
        if gesture != self.activation_gesture:
            self._activation_started_at = None
            return False
        if self._activation_started_at is None:
            self._activation_started_at = now
            return self.stability_seconds <= 0
        return now - self._activation_started_at >= self.stability_seconds

"""Pure lifecycle gate for optional recorded dynamic gestures.

This state machine only decides when a non-pointer motion may be accumulated.
It has no Qt, camera, matcher, or native-input dependencies; the pointer lane
passes ``allowed=False`` whenever it owns an observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from core.intent_arbiter import CORE_POINTER_GESTURES


class DynamicIntentState(StrEnum):
    NEUTRAL = "neutral"
    ARMED = "armed"
    RECORDING = "recording"


@dataclass(frozen=True)
class DynamicIntentObservation:
    state: DynamicIntentState
    recording: bool
    completed_frames: tuple | None = None
    # The current observation was consumed by a dynamic take even if that take
    # was discarded for a safety limit. Callers must not reinterpret it as a
    # static/combo command after recording began.
    owns_frame: bool = False


class DynamicIntentLifecycle:
    """Require a neutral boundary around a bounded optional motion recording."""

    def __init__(
        self,
        *,
        neutral_rearm_frames: int = 3,
        end_neutral_frames: int = 2,
        max_recording_frames: int = 180,
        max_duration_seconds: float = 3.0,
    ):
        self.neutral_rearm_frames = self._positive_int(
            neutral_rearm_frames, "neutral_rearm_frames"
        )
        self.end_neutral_frames = self._positive_int(
            end_neutral_frames, "end_neutral_frames"
        )
        self.max_recording_frames = self._positive_int(
            max_recording_frames, "max_recording_frames"
        )
        if (
            not isinstance(max_duration_seconds, (int, float))
            or isinstance(max_duration_seconds, bool)
            or not isfinite(max_duration_seconds)
            or max_duration_seconds <= 0
        ):
            raise ValueError("max_duration_seconds must be a positive finite number")
        self.max_duration_seconds = float(max_duration_seconds)
        self.reset()

    @staticmethod
    def _positive_int(value, name):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
        return value

    def reset(self) -> None:
        """Drop any partial motion and require a fresh neutral rearm."""
        self.state = DynamicIntentState.NEUTRAL
        self._neutral_frames = 0
        self._ending_neutral_frames = 0
        self._recorded_frames = []
        self._started_at = None
        self._last_time = None

    def observe(self, gesture, frame, *, allowed: bool, hand_present: bool, now: float):
        """Consume one classified frame and return safe lifecycle output."""
        was_recording = self.state is DynamicIntentState.RECORDING
        # An invalid or regressed clock cannot safely delimit a live take. It
        # still belongs to that take, however, so the caller must not reinterpret
        # this terminal frame as a static shortcut after the reset.
        if not self._is_valid_time(now):
            self.reset()
            return self._observation(owns_frame=was_recording)
        # Pointer ownership or tracking loss cancels optional recording but must
        # not consume the current frame: the pointer/session safety path owns it.
        if not allowed or not hand_present:
            self.reset()
            return self._observation()
        if self._last_time is not None and now < self._last_time:
            self.reset()
            return self._observation(owns_frame=was_recording)
        self._last_time = now

        # Pointer labels are never dynamic recording evidence, even for a
        # direct caller that forgot to close the optional lane first.
        if gesture in CORE_POINTER_GESTURES:
            self.reset()
            return self._observation()

        if self.state is DynamicIntentState.NEUTRAL:
            if gesture == "none":
                self._neutral_frames += 1
                if self._neutral_frames >= self.neutral_rearm_frames:
                    self.state = DynamicIntentState.ARMED
            else:
                self._neutral_frames = 0
            return self._observation()

        if self.state is DynamicIntentState.ARMED:
            # A deliberate open-hand start boundary prevents ordinary shortcut
            # poses (for example peace or thumb-up) from being silently
            # reinterpreted as the beginning of a recorded dynamic command.
            if gesture == "open_hand" and frame:
                self.state = DynamicIntentState.RECORDING
                self._recorded_frames = [frame]
                self._started_at = now
                self._ending_neutral_frames = 0
            return self._observation()

        if self._timed_out(now):
            self._discard_to_neutral()
            return self._observation(owns_frame=True)

        # Neutral frames delimit the motion and are deliberately excluded from
        # payload so DTW sees only the dynamic evidence.
        if gesture == "none":
            self._ending_neutral_frames += 1
            if self._ending_neutral_frames >= self.end_neutral_frames:
                completed = tuple(self._recorded_frames)
                self._discard_to_armed()
                return self._observation(completed)
            return self._observation()

        if not frame:
            self.reset()
            return self._observation(owns_frame=was_recording)
        self._ending_neutral_frames = 0
        self._recorded_frames.append(frame)
        if len(self._recorded_frames) >= self.max_recording_frames:
            self._discard_to_neutral()
            return self._observation(owns_frame=True)
        return self._observation()

    def _discard_to_neutral(self) -> None:
        """Abort a take and require a fresh neutral rearm before retrying."""
        self.state = DynamicIntentState.NEUTRAL
        self._neutral_frames = 0
        self._ending_neutral_frames = 0
        self._recorded_frames = []
        self._started_at = None

    def _discard_to_armed(self) -> None:
        self.state = DynamicIntentState.ARMED
        self._neutral_frames = self.neutral_rearm_frames
        self._ending_neutral_frames = 0
        self._recorded_frames = []
        self._started_at = None

    def _timed_out(self, now: float) -> bool:
        return self._started_at is not None and now - self._started_at > self.max_duration_seconds

    @staticmethod
    def _is_valid_time(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
        )

    def _observation(self, completed_frames=None, *, owns_frame=False):
        return DynamicIntentObservation(
            state=self.state,
            recording=self.state is DynamicIntentState.RECORDING,
            completed_frames=completed_frames,
            owns_frame=owns_frame,
        )

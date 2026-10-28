"""Deterministic wheel intent independent of accessibility metadata.

Point at rest to arm, then hold a confirmed thumb direction to scroll. The
controller neither dispatches input nor consults application context: the
engine supplies the exclusive ownership/freshness gate and the input guard
retains final control of every wheel event.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from numbers import Real


@dataclass(frozen=True)
class ScrollIntent:
    action: str
    anchor: tuple[float, float]


class ScrollIntentController:
    """Turn time-qualified pointing/thumb evidence into bounded wheel ticks.

    A continuous point dwell within 12 screen points arms one scroll episode.
    Thumb classification must agree with the raw pose for ``enter_seconds``.
    Direction reversal keeps the original anchor, but must qualify again.
    Non-thumb raw evidence stops the episode immediately; hand loss, disarm,
    pinch/drag, or competing shortcut ownership must pass ``allowed=False``.
    Returning to pointing starts a fresh dwell. Missed repeats never accumulate.
    """

    POINT_DRIFT = 12.0

    def __init__(self, dwell_seconds=0.3, repeat_seconds=0.12, enter_seconds=0.08):
        self.dwell_seconds = self._duration(dwell_seconds, "dwell_seconds", 0.0)
        self.repeat_seconds = self._duration(repeat_seconds, "repeat_seconds", 0.02)
        self.enter_seconds = self._duration(enter_seconds, "enter_seconds", 0.0)
        self.reset()

    @staticmethod
    def _duration(value, name, minimum):
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
        return max(minimum, float(value))

    def reset(self) -> None:
        self._point_started_at: float | None = None
        self._point_origin: tuple[float, float] | None = None
        self._point_anchor: tuple[float, float] | None = None
        self._armed = False
        self._scroll_anchor: tuple[float, float] | None = None
        self._candidate_direction: str | None = None
        self._candidate_started_at: float | None = None
        self._last_emit_at: float | None = None
        self._last_observed_at: float | None = None

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def active(self) -> bool:
        """Whether thumb evidence currently owns the armed scroll episode."""
        return self._scroll_anchor is not None

    def update(self, *, gesture, raw_gesture, anchor, allowed, now) -> ScrollIntent | None:
        if (
            not allowed
            or isinstance(now, bool)
            or not isinstance(now, Real)
            or not isfinite(now)
            or not isinstance(anchor, (tuple, list))
            or len(anchor) != 2
            or any(isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value)
                   for value in anchor)
        ):
            self.reset()
            return None
        if self._last_observed_at is not None and now <= self._last_observed_at:
            # Replayed/backward timestamps cannot earn a dwell or repeat tick.
            self.reset()
            return None
        self._last_observed_at = now
        point = (float(anchor[0]), float(anchor[1]))

        if gesture == raw_gesture == "point":
            if self.active:
                self.reset()
                self._last_observed_at = now
            if (self._point_origin is None or hypot(
                point[0] - self._point_origin[0], point[1] - self._point_origin[1],
            ) > self.POINT_DRIFT):
                self._point_origin = point
                self._point_started_at = now
                self._armed = False
            self._point_anchor = point
            if now - self._point_started_at + 1e-9 >= self.dwell_seconds:
                self._armed = True
            return None

        if raw_gesture not in {"thumb_up", "thumb_down"}:
            self.reset()
            return None
        if not self._armed:
            # An interrupted point dwell must begin again; merely waiting with
            # a thumb held cannot earn a point-at-rest qualification.
            self.reset()
            return None
        if self._scroll_anchor is None:
            self._scroll_anchor = self._point_anchor
        if gesture != raw_gesture:
            # Raw pose changes take effect before stabilized classification.
            # Keep the episode/anchor for natural reversal, but emit nothing.
            self._candidate_direction = None
            self._candidate_started_at = None
            return None
        if self._candidate_direction != gesture:
            self._candidate_direction = gesture
            self._candidate_started_at = now
        if now - self._candidate_started_at + 1e-9 < self.enter_seconds:
            return None
        if self._last_emit_at is not None and now - self._last_emit_at + 1e-9 < self.repeat_seconds:
            return None
        self._last_emit_at = now
        return ScrollIntent(
            action="scroll_up" if gesture == "thumb_up" else "scroll_down",
            anchor=self._scroll_anchor,
        )

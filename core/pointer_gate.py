"""Reject one implausible hand sample before it reaches the OS pointer.

The visible pointer lane maps a camera position straight onto the screen, so a
single bad observation is a visible teleport: MediaPipe occasionally relabels
the hand for one frame, and an absolute mapping of 640x480 onto a multi-display
union turns one wrong landmark into a jump of hundreds of points.

The pinch lane already refuses incoherent palm geometry (see
``core/pinch_intent``). That check is about pose, which cannot help a pointer
that follows a fingertip across the frame. This gate therefore judges the
*trajectory*: it extrapolates the last accepted samples with constant velocity
and refuses a sample that lands far from that prediction. Deliberate fast motion
is predicted by that extrapolation, so it still passes; a relabel or a spurious
detection does not.

Two agreement samples are required to adopt a new place. A real re-acquisition
(tracking loss, hand re-entry, a genuine fast jump) is consistent across
consecutive frames, while detector noise is not. Refusing one frame costs at
most a frame of pointer travel; following a bad frame costs the user their aim.
"""

from __future__ import annotations

import math
from collections import deque

# Fraction of the frame diagonal a sample may deviate from the constant-velocity
# prediction. Scaled to the frame so it does not depend on camera resolution;
# 0.35 of an 800 px diagonal is about 280 px, well above a fast hand sweep and
# well below a relabelled detection on the other side of the frame.
MAX_JUMP_SPAN = 0.35
# Older history cannot predict: a pause, a dropped frame or a clock reset means
# the previous sample says nothing about where the hand is now.
MAX_SAMPLE_AGE = 0.25
# Two samples give one velocity; below that there is nothing to compare against.
MIN_SAMPLES = 2


class PointerJumpGate:
    """Accept or refuse one camera-space pointer sample at a time."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_jump_span: float = MAX_JUMP_SPAN,
        clock=None,
    ) -> None:
        self.enabled = bool(enabled)
        try:
            span = float(max_jump_span)
        except (TypeError, ValueError):
            span = MAX_JUMP_SPAN
        self.max_jump_span = span if math.isfinite(span) and span > 0.0 else MAX_JUMP_SPAN
        self._clock = clock
        self._history = deque(maxlen=MIN_SAMPLES + 1)
        self._pending = None

    @property
    def pending(self):
        """The refused position, kept until a second sample agrees with it."""
        return self._pending

    def reset(self) -> None:
        self._history.clear()
        self._pending = None

    def accept(self, pos, frame_size, now=None) -> bool:
        """Return True when this sample may move the pointer."""
        if not self.enabled:
            return True
        point = _finite_point(pos)
        size = _finite_size(frame_size)
        if point is None or size is None:
            return True
        moment = self._time(now)
        if moment is None:
            return True
        width, height = size
        diagonal = math.hypot(width, height)
        if diagonal <= 0.0:
            return True

        if self._pending is not None:
            # A second sample in the same new place: this is a real position, so
            # adopt it and re-anchor the filters here instead of at the old place.
            offset_x = point[0] - self._pending[0]
            offset_y = point[1] - self._pending[1]
            if math.hypot(offset_x, offset_y) / diagonal <= self.max_jump_span:
                self._pending = None
                self._history.clear()
                self._remember(moment, point)
                return True
            # Otherwise the sample does not confirm the refused one. It may be the
            # honest trajectory resuming, so let the prediction below decide
            # rather than charging the pointer a second frozen frame.

        if len(self._history) < MIN_SAMPLES:
            self._pending = None
            self._remember(moment, point)
            return True

        last_at, last_x, last_y = self._history[-1]
        dt = moment - last_at
        if dt <= 0.0 or dt > MAX_SAMPLE_AGE:
            # A pause or a clock reset makes the old trajectory uninformative.
            self._history.clear()
            self._pending = None
            self._remember(moment, point)
            return True

        first_at, first_x, first_y = self._history[0]
        span = last_at - first_at
        if span > 0.0:
            vx = (last_x - first_x) / span
            vy = (last_y - first_y) / span
        else:
            vx = vy = 0.0
        predicted_x = last_x + vx * dt
        predicted_y = last_y + vy * dt
        residual = math.hypot(point[0] - predicted_x, point[1] - predicted_y) / diagonal
        if residual > self.max_jump_span:
            self._pending = point
            return False
        # An honest frame after a refused one continues the old trajectory, so the
        # refusal never outlives the sample that caused it.
        self._pending = None
        self._remember(moment, point)
        return True

    def _remember(self, moment, point):
        self._history.append((moment, point[0], point[1]))

    def _time(self, now):
        if now is None:
            return None if self._clock is None else float(self._clock())
        try:
            value = float(now)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None


def _finite_point(pos):
    try:
        x, y = float(pos[0]), float(pos[1])
    except (TypeError, IndexError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _finite_size(size):
    try:
        width, height = float(size[0]), float(size[1])
    except (TypeError, IndexError, ValueError):
        return None
    if not math.isfinite(width) or not math.isfinite(height):
        return None
    if width <= 0.0 or height <= 0.0:
        return None
    return (width, height)
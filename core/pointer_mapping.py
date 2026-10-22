"""Deterministic hand-to-screen pointer mapping.

Two strategies live here, and neither knows about Qt, cameras, or gestures:

``AbsoluteMapper``
    The hand's position in the frame *is* the cursor position. Cheap, direct,
    and the only option that lets a user point at something they can see at a
    known arm position. It requires the hand to sweep the whole frame, which is
    also its cost.

``RelativeMapper``
    The hand's displacement from an anchor moves the cursor by that fraction of
    the screen times a gain. Small, relaxed hand movements cover the display,
    at the price of an explicit re-anchor (the "clutch" that trackpads and
    distant-pointing systems both rely on).

Both clamp to the supplied bounds, so multi-display unions and a single screen
are the same problem.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenBounds:
    """A screen-space rectangle in points, possibly with a negative origin."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen bounds must have positive width and height")

    @property
    def right(self) -> int:
        # QRect-style inclusive right edge; the desktop union uses the same
        # convention, so a cursor on the last pixel is still inside.
        return self.x + self.width - 1

    @property
    def bottom(self) -> int:
        return self.y + self.height - 1

    def clamp(self, x: float, y: float) -> tuple[int, int]:
        """Return the nearest integer point inside the bounds."""
        cx = min(max(int(round(x)), self.x), self.right)
        cy = min(max(int(round(y)), self.y), self.bottom)
        return (cx, cy)


def _finite_point(pos) -> tuple[float, float] | None:
    try:
        x, y = float(pos[0]), float(pos[1])
    except (TypeError, IndexError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def _frame_size(size) -> tuple[float, float] | None:
    try:
        width, height = float(size[0]), float(size[1])
    except (TypeError, IndexError, ValueError):
        return None
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        return None
    return (width, height)


class AbsoluteMapper:
    """Hand position maps directly onto the screen rectangle."""

    mode = "absolute"

    def begin(self, pos, frame_size, bounds: ScreenBounds, cursor=None) -> None:
        """Absolute mapping needs no anchor; kept for a uniform interface."""
        return None

    def reset(self) -> None:
        return None

    def map(self, pos, frame_size, bounds: ScreenBounds) -> tuple[int, int] | None:
        point = _finite_point(pos)
        size = _frame_size(frame_size)
        if point is None or size is None:
            return None
        width, height = size
        return bounds.clamp(
            bounds.x + point[0] / width * bounds.width,
            bounds.y + point[1] / height * bounds.height,
        )

    def unmap(self, screen, frame_size, bounds: ScreenBounds) -> tuple[int, int] | None:
        """Inverse, used to draw a screen-space cursor back onto the preview."""
        point = _finite_point(screen)
        size = _frame_size(frame_size)
        if point is None or size is None:
            return None
        width, height = size
        fx = (point[0] - bounds.x) / bounds.width * width
        fy = (point[1] - bounds.y) / bounds.height * height
        return (int(round(fx)), int(round(fy)))


class RelativeMapper:
    """Hand displacement from an anchor moves the cursor by ``gain``.

    ``gain`` is expressed in screens-per-hand-sweep: at 2.0, moving the hand
    across half the frame covers the whole display. ``begin`` fixes the anchor;
    the caller decides when to re-anchor (gesture re-entry, tracking loss), and
    that re-anchor is the clutch.
    """

    mode = "relative"

    def __init__(self, gain: float = 2.0) -> None:
        value = float(gain)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("gain must be a positive finite number")
        self.gain = value
        self._hand_anchor: tuple[float, float] | None = None
        self._cursor_anchor: tuple[int, int] | None = None

    def begin(self, pos, frame_size, bounds: ScreenBounds, cursor=None) -> None:
        """Fix the anchor pair; ``cursor`` defaults to the display centre."""
        point = _finite_point(pos)
        size = _frame_size(frame_size)
        if point is None or size is None:
            self.reset()
            return
        width, height = size
        self._hand_anchor = (point[0] / width, point[1] / height)
        if cursor is None:
            self._cursor_anchor = bounds.clamp(
                bounds.x + bounds.width / 2, bounds.y + bounds.height / 2
            )
        else:
            self._cursor_anchor = bounds.clamp(cursor[0], cursor[1])

    def reset(self) -> None:
        self._hand_anchor = None
        self._cursor_anchor = None

    def map(self, pos, frame_size, bounds: ScreenBounds) -> tuple[int, int] | None:
        point = _finite_point(pos)
        size = _frame_size(frame_size)
        if point is None or size is None:
            return None
        width, height = size
        if self._hand_anchor is None or self._cursor_anchor is None:
            # First frame after a reset defines the anchor; it must not move
            # the cursor, or every re-entry would jump.
            self.begin(pos, frame_size, bounds)
            return self._cursor_anchor
        dx = (point[0] / width - self._hand_anchor[0]) * bounds.width * self.gain
        dy = (point[1] / height - self._hand_anchor[1]) * bounds.height * self.gain
        return bounds.clamp(self._cursor_anchor[0] + dx, self._cursor_anchor[1] + dy)

    def unmap(self, screen, frame_size, bounds: ScreenBounds) -> tuple[int, int] | None:
        """Relative mapping has no stable inverse; report the hand anchor."""
        if self._hand_anchor is None:
            return None
        size = _frame_size(frame_size)
        if size is None:
            return None
        width, height = size
        return (
            int(round(self._hand_anchor[0] * width)),
            int(round(self._hand_anchor[1] * height)),
        )

"""Bayesian target selection and pointer snapping for pinch-to-click assists.

The model follows the Bayesian Touch formulation (Bi & Zhai, UIST'13): the
likelihood of a target decays with the squared distance from the pointer to the
target rectangle, normalised by a per-target sigma derived from the smaller
dimension of that rectangle. The posteriors are then compared against a
confidence floor, and only a confident, nearby winner is allowed to move the
cursor.

The module is intentionally dependency free (standard library only) so the
assist policy can be unit tested and reused without Qt or any platform service.
Every entry point is fail-closed: input that cannot be scored with finite
numbers produces no decision, leaving the raw pointer position untouched.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# A rectangle narrower than this cannot keep a 2 px inset on both sides, so the
# snap point degrades to the rectangle centre on that axis.
_MIN_INSET_SIZE = 5.0
_INSET = 2.0
# Floor for sigma: below ~6 pt the Gaussian becomes so narrow that a one pixel
# jitter would erase an otherwise obvious target.
_MIN_SIGMA = 6.0


@dataclass(frozen=True)
class Target:
    """A clickable screen region expressed in screen points."""

    target_id: str
    bounds: tuple[int, int, int, int]  # x, y, width, height
    role: str = ""  # AX role, e.g. "AXButton"; reserved for future ranking
    enabled: bool = True


@dataclass(frozen=True)
class SnapDecision:
    """The winning target and the point the cursor should be moved to."""

    target_id: str
    x: int
    y: int
    confidence: float


@dataclass(frozen=True)
class _Candidate:
    """A scored target: its log posterior numerator and geometry."""

    target: Target
    bounds: tuple[float, float, float, float]
    logit: float


class TargetModel:
    """Picks the most probable target under the pointer and snaps onto it.

    ``max_snap_distance`` bounds how far the cursor may travel, so a distant but
    certain target never yanks the pointer. ``min_confidence`` is the posterior
    floor that rejects ambiguous layouts (two identical targets side by side).
    ``search_radius`` limits which targets are scored at all.
    """

    def __init__(
        self,
        *,
        max_snap_distance: float = 24.0,
        min_confidence: float = 0.55,
        search_radius: float = 120.0,
    ) -> None:
        self.max_snap_distance = _finite_or_raise("max_snap_distance", max_snap_distance)
        self.min_confidence = _finite_or_raise("min_confidence", min_confidence)
        self.search_radius = _finite_or_raise("search_radius", search_radius)
        if self.max_snap_distance < 0.0:
            raise ValueError("max_snap_distance must be non-negative")
        if self.search_radius < 0.0:
            raise ValueError("search_radius must be non-negative")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0.0, 1.0]")

    def choose(self, x: int, y: int, targets: Sequence[Target]) -> SnapDecision | None:
        """Return the target to snap to, or ``None`` when the choice is unsafe."""
        try:
            return self._choose(x, y, targets)
        except Exception:  # noqa: BLE001 - the assist lane must never break input
            # Fail-closed: a malformed target list degrades to "no assist" so the
            # caller keeps the pointer exactly where the hand put it.
            return None

    def posteriors(
        self, x: int, y: int, targets: Sequence[Target]
    ) -> list[tuple[Target, float]]:
        """Return ``(target, posterior)`` pairs, best first.

        Shared by the snap decision and by the learned ranker's features, so a
        model never sees a probability computed by a different formula.
        """
        if not _is_coordinate(x) or not _is_coordinate(y) or targets is None:
            return []
        try:
            raw_targets = list(targets)
        except TypeError:
            return []
        scored: list[_Candidate] = []
        for target in raw_targets:
            candidate = _score(target, float(x), float(y), self.search_radius)
            if candidate is not None:
                scored.append(candidate)
        if not scored:
            return []
        best_logit = max(candidate.logit for candidate in scored)
        if not math.isfinite(best_logit):
            return []
        weights = [math.exp(candidate.logit - best_logit) for candidate in scored]
        total = math.fsum(weights)
        if not math.isfinite(total) or total <= 0.0:
            return []
        scored.sort(key=lambda candidate: (-candidate.logit, candidate.target.target_id))
        return [
            (candidate.target, math.exp(candidate.logit - best_logit) / total)
            for candidate in scored
        ]

    def _choose(self, x: int, y: int, targets: Sequence[Target]) -> SnapDecision | None:
        if not _is_coordinate(x) or not _is_coordinate(y):
            return None
        if targets is None:
            return None
        try:
            raw_targets = list(targets)
        except TypeError:
            return None

        px = float(x)
        py = float(y)
        ranked = self.posteriors(px, py, raw_targets)
        if not ranked:
            return None
        winner, confidence = ranked[0]
        if not math.isfinite(confidence) or confidence < self.min_confidence:
            return None

        snap_x, snap_y = _snap_point(px, py, tuple(winner.bounds))
        if math.hypot(snap_x - px, snap_y - py) > self.max_snap_distance:
            return None
        return SnapDecision(
            target_id=winner.target_id,
            x=snap_x,
            y=snap_y,
            confidence=confidence,
        )


def _finite_or_raise(name: str, value: object) -> float:
    """Validate a tuning knob, mirroring the rest of ``core`` on bad config."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _is_coordinate(value: object) -> bool:
    """True for a finite int/float pointer coordinate (bool is not a coordinate)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _bounds(target: object) -> tuple[float, float, float, float] | None:
    """Return validated float bounds, or ``None`` when the rectangle is unusable."""
    raw = getattr(target, "bounds", None)
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != 4:
        return None
    values: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        values.append(number)
    left, top, width, height = values
    if width <= 0.0 or height <= 0.0:
        return None
    return left, top, width, height


def _score(target: Target, px: float, py: float, search_radius: float) -> _Candidate | None:
    """Score one candidate, or reject it as disabled, invalid or out of range."""
    if not getattr(target, "enabled", False):
        return None
    target_id = getattr(target, "target_id", None)
    if not isinstance(target_id, str):
        return None
    bounds = _bounds(target)
    if bounds is None:
        return None

    left, top, width, height = bounds
    # Distance to the rectangle, not to its centre: a pointer already inside the
    # target sits at distance 0 and keeps its own position.
    dx = max(left - px, 0.0, px - (left + width))
    dy = max(top - py, 0.0, py - (top + height))
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance) or distance > search_radius:
        return None

    sigma = max(_MIN_SIGMA, 0.5 * min(width, height))
    logit = -(distance * distance) / (2.0 * sigma * sigma)
    if not math.isfinite(logit):
        return None
    return _Candidate(target=target, bounds=bounds, logit=logit)


def _snap_point(px: float, py: float, bounds: tuple[float, float, float, float]) -> tuple[int, int]:
    """Clamp the pointer into the rectangle, inset 2 px from every edge."""
    left, top, width, height = bounds
    snap_x = _snap_axis(px, left, width)
    snap_y = _snap_axis(py, top, height)
    return _inside_int(snap_x, left, width), _inside_int(snap_y, top, height)


def _snap_axis(value: float, start: float, size: float) -> float:
    """Inset clamp on one axis; degenerate rectangles fall back to their centre."""
    if size < _MIN_INSET_SIZE:
        return start + size / 2.0
    low = start + _INSET
    high = start + size - _INSET
    return min(max(value, low), high)


def _inside_int(value: float, start: float, size: float) -> int:
    """Round to an integer point and keep it inside the integer extent."""
    point = int(round(value))
    low = math.ceil(start)
    high = math.floor(start + size)
    if low <= high:
        point = min(max(point, low), high)
    return point

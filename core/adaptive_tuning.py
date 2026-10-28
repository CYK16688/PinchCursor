"""Bounded tuning of the aim assist from local click outcomes.

This is the first adaptation layer, and it is deliberately narrow: it reads the
aggregate telemetry summary, moves at most two numbers, and refuses to act on
thin evidence. Three invariants make it safe to run without supervision:

* **It only ever makes the assist more conservative.** The radius may shrink and
  the confidence floor may rise; neither can grow past what the user configured,
  because a wider snap is the change most likely to grab the wrong control.
* **Every step is bounded.** At most 15 % of the radius and 0.03 of the floor per
  pass, inside hard limits, so no single noisy session can redefine the feel.
* **It explains itself.** Each decision carries a reason string the UI can show,
  and a no-change decision is still a decision worth recording.

The tuner is pure: it takes numbers and returns numbers, so the rules above are
unit-testable without a camera, a database, or a QApplication.
"""

from __future__ import annotations

from dataclasses import dataclass

# Below this there is not enough evidence to move anything: a handful of clicks
# is one bad afternoon, not a trend.
MIN_CLICKS = 40

# Repeat clicks above this share mean the pointer keeps landing on the wrong
# thing; below the clean rate the assist is not getting in the way at all.
MISS_RATE_TIGHTEN = 0.20
MISS_RATE_CLEAN = 0.03
CLEAN_CLICKS = 100

# Hard limits, independent of configuration: a 6 px snap is indistinguishable
# from no assist, and a 60 px snap reaches across most toolbar rows.
RADIUS_MIN = 12.0
RADIUS_MAX = 60.0
CONFIDENCE_MIN = 0.50
CONFIDENCE_MAX = 0.72

RADIUS_STEP = 0.15
CONFIDENCE_STEP = 0.03

# When the observed snaps already sit near the edge of the search radius, the
# assist is reaching too far and shrinking is the honest fix. When they are
# shallow, the problem is ambiguity between neighbours, so only the floor moves.
OVER_REACH_RATIO = 0.75


@dataclass(frozen=True)
class SnappingTuning:
    """The values to use next, plus why they were chosen."""

    max_snap_distance: float
    min_confidence: float
    changed: bool
    reason: str
    clicks: int
    misses: int
    miss_rate: float | None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _coerce(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def tune_snapping(
    *,
    max_snap_distance: object,
    min_confidence: object,
    clicks: object,
    misses: object,
    snaps: object = 0,
    mean_snap_distance: object = None,
) -> SnappingTuning:
    """Return the next snapping parameters, moving them at most one step.

    ``clicks`` and ``misses`` come from the telemetry summary; ``snaps`` and
    ``mean_snap_distance`` describe the assists that actually engaged. A missing
    or malformed number holds the current values instead of raising, because
    this runs at startup and must never be the reason an app fails to open.
    """
    radius = _coerce(max_snap_distance)
    floor = _coerce(min_confidence)
    click_count = _coerce(clicks)
    miss_count = _coerce(misses)
    snap_count = _coerce(snaps) or 0.0
    mean_snap = _coerce(mean_snap_distance)

    if radius is None or floor is None:
        return SnappingTuning(
            max_snap_distance=radius if radius is not None else RADIUS_MIN,
            min_confidence=floor if floor is not None else CONFIDENCE_MIN,
            changed=False,
            reason="invalid_parameters",
            clicks=0,
            misses=0,
            miss_rate=None,
        )

    radius = _clamp(radius, RADIUS_MIN, RADIUS_MAX)
    floor = _clamp(floor, CONFIDENCE_MIN, CONFIDENCE_MAX)
    clicks_i = int(click_count) if click_count is not None else 0
    misses_i = int(miss_count) if miss_count is not None else 0
    misses_i = max(0, min(misses_i, clicks_i))

    if clicks_i < MIN_CLICKS:
        return SnappingTuning(radius, floor, False, "insufficient_evidence", clicks_i, misses_i, None)

    miss_rate = misses_i / clicks_i

    if miss_rate >= MISS_RATE_TIGHTEN:
        over_reach = (
            snap_count > 0
            and mean_snap is not None
            and mean_snap >= OVER_REACH_RATIO * radius
        )
        new_radius = (
            round(max(RADIUS_MIN, radius * (1.0 - RADIUS_STEP)), 1) if over_reach else radius
        )
        new_floor = round(min(CONFIDENCE_MAX, floor + CONFIDENCE_STEP), 2)
        reason = "over_reach" if over_reach else "ambiguous_targets"
        return SnappingTuning(
            new_radius, new_floor, (new_radius, new_floor) != (radius, floor), reason, clicks_i, misses_i, miss_rate
        )

    if miss_rate <= MISS_RATE_CLEAN and clicks_i >= CLEAN_CLICKS:
        new_floor = round(max(CONFIDENCE_MIN, floor - CONFIDENCE_STEP), 2)
        return SnappingTuning(
            radius, new_floor, new_floor != floor, "clean_clicks", clicks_i, misses_i, miss_rate
        )

    return SnappingTuning(radius, floor, False, "within_band", clicks_i, misses_i, miss_rate)

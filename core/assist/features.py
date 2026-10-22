"""Candidate features shared by the trainer and the runtime ranker.

One definition, used twice: anything the model is trained on must be computed
exactly the same way at inference, or the weights mean nothing. The vector is
deliberately small and numeric — no labels, no text, no images.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .target_model import Target

# Role buckets. Anything not listed falls into "other" rather than exploding
# into a one-hot dimension per accessibility role.
_ROLE_BUCKETS = {
    "AXButton": "button",
    "AXMenuItem": "menu",
    "AXMenu": "menu",
    "AXSlider": "slider",
    "AXScrollBar": "slider",
    "AXCheckBox": "checkbox",
    "AXRadioButton": "checkbox",
}
_BUCKETS = ("button", "menu", "slider", "checkbox", "other")

FEATURE_NAMES = (
    "dx",
    "dy",
    "edge",
    "inside",
    "w",
    "h",
    "area",
    "aspect",
    "role_button",
    "role_menu",
    "role_slider",
    "role_checkbox",
    "role_other",
    "bayes",
    "dist_rank",
)

FEATURE_COUNT = len(FEATURE_NAMES)


def _rect_distance(px: float, py: float, bounds: tuple[int, int, int, int]) -> float:
    """Euclidean distance from a point to a rectangle (0 inside)."""
    x, y, width, height = bounds
    dx = max(x - px, 0.0, px - (x + width))
    dy = max(y - py, 0.0, py - (y + height))
    return math.hypot(dx, dy)


def build_features(
    cursor: tuple[int, int],
    screen_bounds: tuple[int, int, int, int],
    targets: Sequence[Target],
    posteriors: dict[str, float],
) -> list[list[float]]:
    """Return one feature row per target, in the given order.

    Rows are aligned with ``targets`` so a caller can zip them back without
    carrying ids through the model.
    """
    screen_w = max(float(screen_bounds[2]), 1.0)
    screen_h = max(float(screen_bounds[3]), 1.0)
    scale = min(screen_w, screen_h)
    px, py = float(cursor[0]), float(cursor[1])

    distances = [
        _rect_distance(px, py, tuple(target.bounds)) for target in targets
    ]
    # Rank by distance: 0 = nearest, 1 = farthest. Ties share the average rank,
    # which keeps the feature stable regardless of probe order.
    order = sorted(range(len(targets)), key=lambda index: (distances[index], targets[index].target_id))
    rank_of = [0.0] * len(targets)
    for position, index in enumerate(order):
        rank_of[index] = position / max(len(targets) - 1, 1)

    rows: list[list[float]] = []
    for target, distance in zip(targets, distances):
        x, y, width, height = target.bounds
        centre_x = x + width / 2.0
        centre_y = y + height / 2.0
        bucket = _ROLE_BUCKETS.get(target.role, "other")
        row = [
            (px - centre_x) / screen_w,
            (py - centre_y) / screen_h,
            distance / scale,
            1.0 if distance <= 0.0 else 0.0,
            width / screen_w,
            height / screen_h,
            (width * height) / (screen_w * screen_h),
            min(max(width / max(height, 1.0), 0.1), 10.0) / 10.0,
        ]
        row.extend(1.0 if bucket == name else 0.0 for name in _BUCKETS)
        row.append(posteriors.get(target.target_id, 0.0))
        row.append(rank_of[len(rows)])
        rows.append(row)
    return rows


def sigmoid(value: float) -> float:
    if value >= 40:
        return 1.0
    if value <= -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))

"""Feature vector shared by the transition trainer and the runtime shadow.

The rule in :mod:`core.hand_dynamics` asks one question: are the other fingers
closing fast? A learned boundary can weigh more evidence than that, so this
module fixes the features once, in one order, and both the trainer and the
runtime read them through the same function. If a feature is added here, the
stored vectors and the model schema disagree loudly rather than silently.

Everything is a dimensionless ratio or a per-second rate, so a 640×480 laptop
camera and a 1280×720 external camera produce comparable numbers.
"""

from __future__ import annotations

import math

FEATURE_NAMES = (
    "pinch_ratio",       # thumb–index distance in palm units
    "pinch_confidence",  # sticky posterior from the causal filter
    "others_distance",   # mean other-tip distance in palm units
    "others_rate",       # its derivative, palm/s (negative = closing)
    "wrist_speed",       # wrist travel, palm/s
    "pinch_slope",       # derivative of the pinch ratio, ratio/s
)
FEATURE_COUNT = len(FEATURE_NAMES)

# Loose physical bounds. Anything outside is a tracking artefact, not evidence,
# and clamping keeps one bad frame from dominating a trained weight.
_BOUNDS = (
    (0.0, 3.0),    # pinch_ratio
    (0.0, 1.0),    # pinch_confidence
    (0.0, 4.0),    # others_distance
    (-12.0, 12.0), # others_rate
    (0.0, 12.0),   # wrist_speed
    (-30.0, 30.0), # pinch_slope
)


def build_features(assessment) -> tuple[float, ...] | None:
    """Return the feature vector for one assessment, or None if it is unusable.

    ``None`` means "no evidence": a dropout frame must not be recorded as a
    negative example, because that would teach the classifier about the camera
    rather than about the hand.
    """
    raw = [
        getattr(assessment, "pinch_ratio", None),
        getattr(assessment, "pinch_confidence", None),
        getattr(assessment, "others_distance", None),
        getattr(assessment, "others_rate", None),
        getattr(assessment, "wrist_speed", None),
        getattr(assessment, "pinch_slope", None),
    ]
    numbers: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return tuple(
        round(min(max(number, low), high), 4)
        for number, (low, high) in zip(numbers, _BOUNDS)
    )


def validate_vector(values) -> tuple[float, ...] | None:
    """Coerce a stored vector back into shape, or reject it."""
    if not isinstance(values, (list, tuple)) or len(values) != FEATURE_COUNT:
        return None
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        result.append(number)
    return tuple(result)

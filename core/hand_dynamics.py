"""Causal hand dynamics: what the hand is *doing*, not how it looks.

A single frame cannot tell a settled pinch from a hand that happens to pass
through a pinch shape on its way to a fist. The motion can, so this module keeps
a short causal history (~200 ms) and answers two questions per frame:

``pinch_confidence``
    A bounded, sticky posterior that a pinch is currently intended. It rises
    only when the pinch distance stays low, and drops quickly when it stops
    being true, which is the safe asymmetry for a click gate.

``transition``
    True when the pinch threshold is being crossed *while the rest of the hand
    closes fast* — the signature of a fist (or a hand leaving the frame), not a
    click. The pointer lane uses this to suppress a click without stopping the
    cursor.

Everything is causal: only past frames are consulted, so the pointer lane gains
no latency. No model, no training data, and no Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# MediaPipe hand landmark indices.
WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_TIP = 16
PINKY_TIP = 20
_OTHER_TIPS = (MIDDLE_TIP, RING_TIP, PINKY_TIP)

# A fist closes the three "other" fingers by roughly half a palm in ~200 ms,
# i.e. about -2.5 palm/s. A pinch leaves them almost still. -0.8 separates the
# two with margin on both sides.
DEFAULT_TRANSITION_OTHERS_RATE = -0.8
DEFAULT_HISTORY_SECONDS = 0.20
# Shorter histories make the derivative meaningless; wait for real data.
MIN_HISTORY_SECONDS = 0.08


@dataclass(frozen=True)
class DynamicAssessment:
    """One frame's verdict on the hand's motion."""

    pinch_ratio: float
    pinch_confidence: float
    transition: bool
    others_rate: float
    wrist_speed: float


def _valid_landmarks(landmarks) -> bool:
    try:
        if len(landmarks) < 21:
            return False
    except TypeError:
        return False
    return True


def _point(landmark) -> tuple[float, float]:
    try:
        return (float(landmark[0]), float(landmark[1]))
    except (TypeError, IndexError, ValueError):
        return (float("nan"), float("nan"))


def _distance(first, second) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


class HandDynamics:
    """Causal pinch confidence and transition detection for one hand."""

    def __init__(
        self,
        *,
        enter_ratio: float = 0.29,
        exit_ratio: float = 0.42,
        transition_others_rate: float = DEFAULT_TRANSITION_OTHERS_RATE,
        history_seconds: float = DEFAULT_HISTORY_SECONDS,
        stickiness: float = 0.35,
    ) -> None:
        self.enter_ratio = float(enter_ratio)
        self.exit_ratio = max(float(exit_ratio), self.enter_ratio + 1e-3)
        self.transition_others_rate = float(transition_others_rate)
        self.history_seconds = max(MIN_HISTORY_SECONDS, float(history_seconds))
        self.stickiness = min(max(float(stickiness), 0.0), 0.6)
        # Softness of the ratio -> likelihood curve: a third of the hysteresis
        # band, so the curve spans the region the thresholds bracket.
        self.softness = max(0.02, (self.exit_ratio - self.enter_ratio) / 3.0)
        self._history: list[tuple[float, float, float, float, float]] = []
        self._confidence = 0.0
        self._last_transition_at: float | None = None

    def reset(self) -> None:
        self._history.clear()
        self._confidence = 0.0
        self._last_transition_at = None

    def update(self, landmarks, now: float) -> DynamicAssessment | None:
        """Fold one frame in and return the current assessment."""
        if not _valid_landmarks(landmarks):
            return None
        wrist = _point(landmarks[WRIST])
        middle_mcp = _point(landmarks[MIDDLE_MCP])
        if not all(math.isfinite(value) for value in (*wrist, *middle_mcp)):
            return None
        palm = _distance(wrist, middle_mcp)
        if not math.isfinite(palm) or palm <= 1e-6:
            return None

        pinch = _distance(_point(landmarks[THUMB_TIP]), _point(landmarks[INDEX_TIP])) / palm
        others = sum(_distance(_point(landmarks[i]), wrist) for i in _OTHER_TIPS) / (
            palm * len(_OTHER_TIPS)
        )
        wrist_x, wrist_y = wrist[0] / palm, wrist[1] / palm
        if not all(math.isfinite(value) for value in (pinch, others, wrist_x, wrist_y)):
            return None

        self._history.append((now, pinch, others, wrist_x, wrist_y))
        cutoff = now - self.history_seconds
        while len(self._history) > 2 and self._history[0][0] < cutoff:
            self._history.pop(0)

        others_rate = 0.0
        wrist_speed = 0.0
        if len(self._history) >= 2:
            first = self._history[0]
            last = self._history[-1]
            span = last[0] - first[0]
            if span >= MIN_HISTORY_SECONDS:
                others_rate = (last[2] - first[2]) / span
                wrist_speed = math.hypot(last[3] - first[3], last[4] - first[4]) / span

        transition = bool(
            pinch <= self.enter_ratio * 1.35
            and others_rate <= self.transition_others_rate
        )

        likelihood = self._likelihood(pinch)
        prior = 0.5 + self.stickiness * self._confidence
        denominator = prior * likelihood + (1.0 - prior) * (1.0 - likelihood)
        if denominator <= 1e-9:
            posterior = 0.0
        else:
            posterior = (prior * likelihood) / denominator
        if transition:
            # Passing through is never an intended pinch, however low the ratio.
            posterior = 0.0
        self._confidence = min(max(posterior, 0.0), 1.0)

        if transition:
            self._last_transition_at = now
        return DynamicAssessment(
            pinch_ratio=pinch,
            pinch_confidence=self._confidence,
            transition=transition,
            others_rate=others_rate,
            wrist_speed=wrist_speed,
        )

    def _likelihood(self, pinch_ratio: float) -> float:
        """Smooth probability that this distance means "pinching"."""
        z = (pinch_ratio - self.enter_ratio) / self.softness
        if z >= 40:
            return 0.0
        if z <= -40:
            return 1.0
        return 1.0 / (1.0 + math.exp(z))

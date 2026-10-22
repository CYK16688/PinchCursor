"""A tiny learned ranker over accessibility candidates.

The runtime side of the training pipeline in ``scripts/train_target_ranker.py``.
It is deliberately a *linear* model: with a few hundred to a few thousand
locks, a handful of weights is what the data can actually support, and it is
auditable line by line. The file format is plain JSON so a trained model can be
inspected, versioned, and deleted without a build step.

Nothing here changes the pointer pipeline on its own: the caller decides whether
the ranker's choice is used (shadow / active) or ignored.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

from .features import FEATURE_COUNT, FEATURE_NAMES, build_features
from .target_model import SnapDecision, Target, _snap_point

MODEL_VERSION = 1


@dataclass(frozen=True)
class LinearRanker:
    """Logistic scoring of candidate rows, normalised across candidates."""

    weights: tuple[float, ...]
    intercept: float
    feature_names: tuple[str, ...] = FEATURE_NAMES
    version: int = MODEL_VERSION
    trained_locks: int = 0
    accuracy: float | None = None

    def __post_init__(self) -> None:
        if len(self.weights) != len(self.feature_names):
            raise ValueError("weight vector does not match the feature list")
        if not all(math.isfinite(value) for value in self.weights):
            raise ValueError("weights must be finite")
        if not math.isfinite(self.intercept):
            raise ValueError("intercept must be finite")

    def score(self, row: Sequence[float]) -> float:
        """Return the logit for one candidate row."""
        if len(row) != len(self.weights):
            raise ValueError("feature row has the wrong width")
        total = self.intercept
        for weight, value in zip(self.weights, row):
            total += weight * value
        return total

    def choose(
        self,
        cursor: tuple[int, int],
        screen_bounds: tuple[int, int, int, int],
        targets: Sequence[Target],
        posteriors: dict[str, float],
        *,
        min_confidence: float = 0.55,
        max_snap_distance: float = 24.0,
    ) -> SnapDecision | None:
        """Pick the most likely target, or None when the choice is unsafe."""
        try:
            return self._choose(
                cursor, screen_bounds, targets, posteriors, min_confidence, max_snap_distance
            )
        except Exception:  # noqa: BLE001 - a model must never break the click lane
            return None

    def _choose(
        self,
        cursor: tuple[int, int],
        screen_bounds: tuple[int, int, int, int],
        targets: Sequence[Target],
        posteriors: dict[str, float],
        min_confidence: float,
        max_snap_distance: float,
    ) -> SnapDecision | None:
        if not targets:
            return None
        rows = build_features(cursor, screen_bounds, targets, posteriors)
        if not rows or len(rows[0]) != FEATURE_COUNT:
            return None
        logits = [self.score(row) for row in rows]
        best = max(logits)
        if not math.isfinite(best):
            return None
        weights = [math.exp(logit - best) for logit in logits]
        total = math.fsum(weights)
        if not math.isfinite(total) or total <= 0.0:
            return None
        order = sorted(
            range(len(targets)), key=lambda index: (-weights[index], targets[index].target_id)
        )
        winner = targets[order[0]]
        confidence = weights[order[0]] / total
        if not math.isfinite(confidence) or confidence < min_confidence:
            return None
        snap_x, snap_y = _snap_point(float(cursor[0]), float(cursor[1]), tuple(winner.bounds))
        if math.hypot(snap_x - cursor[0], snap_y - cursor[1]) > max_snap_distance:
            return None
        return SnapDecision(
            target_id=winner.target_id, x=snap_x, y=snap_y, confidence=confidence
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "feature_names": list(self.feature_names),
            "weights": list(self.weights),
            "intercept": self.intercept,
            "trained_locks": self.trained_locks,
            "accuracy": self.accuracy,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "LinearRanker":
        if not isinstance(payload, dict):
            raise ValueError("model payload must be an object")
        names = tuple(payload.get("feature_names") or FEATURE_NAMES)
        weights = tuple(float(value) for value in payload.get("weights") or ())
        if names != FEATURE_NAMES:
            # A model trained on a different feature set would score garbage.
            raise ValueError("model feature set does not match this build")
        return cls(
            weights=weights,
            intercept=float(payload.get("intercept", 0.0)),
            feature_names=names,
            version=int(payload.get("version", MODEL_VERSION)),
            trained_locks=int(payload.get("trained_locks", 0)),
            accuracy=(
                float(payload["accuracy"]) if payload.get("accuracy") is not None else None
            ),
        )

    @classmethod
    def load(cls, path: str) -> "LinearRanker | None":
        """Load a model file, returning None for anything unusable."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return cls.from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

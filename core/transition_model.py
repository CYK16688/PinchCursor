"""Runtime reader for a trained pinch-transition boundary.

The model is a plain logistic regression over the six features in
:mod:`core.transition_features`. It exists so the rule's one hard threshold can
eventually be replaced by a boundary fitted to the user's own hand — but only
after it has proved itself in shadow mode, where its score is recorded next to
the rule's decision and nobody acts on it.

Loading is strict on purpose: a model trained against a different feature order
is worse than no model, so the names must match exactly or the file is ignored.
"""

from __future__ import annotations

import json
import math

from .transition_features import FEATURE_COUNT, FEATURE_NAMES, validate_vector

DEFAULT_THRESHOLD = 0.5


class TransitionModel:
    """A validated logistic boundary; immutable once loaded."""

    __slots__ = ("weights", "intercept", "mean", "scale", "threshold", "metadata")

    def __init__(
        self,
        *,
        weights,
        intercept: float,
        mean,
        scale,
        threshold: float = DEFAULT_THRESHOLD,
        metadata: dict | None = None,
    ) -> None:
        self.weights = tuple(float(value) for value in weights)
        self.intercept = float(intercept)
        self.mean = tuple(float(value) for value in mean)
        self.scale = tuple(float(value) for value in scale)
        self.threshold = float(threshold)
        self.metadata = dict(metadata or {})

    @classmethod
    def load(cls, path: str) -> "TransitionModel | None":
        """Return a model, or None when the file is missing or does not fit."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("feature_names") != list(FEATURE_NAMES):
            return None
        try:
            weights = payload["weights"]
            mean = payload["mean"]
            scale = payload["scale"]
            intercept = float(payload["intercept"])
        except (KeyError, TypeError, ValueError):
            return None
        if not all(
            isinstance(vector, list) and len(vector) == FEATURE_COUNT
            for vector in (weights, mean, scale)
        ):
            return None
        if any(float(value) == 0.0 for value in scale):
            return None
        return cls(
            weights=weights,
            intercept=intercept,
            mean=mean,
            scale=scale,
            threshold=float(payload.get("threshold", DEFAULT_THRESHOLD)),
            metadata={key: payload.get(key) for key in ("trained_at", "episodes", "validation_accuracy")},
        )

    def probability(self, features) -> float | None:
        """P(intended pinch) for one feature vector, or None if malformed."""
        vector = validate_vector(features)
        if vector is None:
            return None
        total = self.intercept
        for value, weight, mean, scale in zip(vector, self.weights, self.mean, self.scale):
            total += weight * ((value - mean) / scale)
        if not math.isfinite(total):
            return None
        if total >= 40.0:
            return 1.0
        if total <= -40.0:
            return 0.0
        return 1.0 / (1.0 + math.exp(-total))

    def agrees_with_rule(self, features, *, rule_rejected: bool) -> bool | None:
        """Whether the model and the rule reach the same verdict."""
        probability = self.probability(features)
        if probability is None:
            return None
        model_rejects = probability < self.threshold
        return model_rejects == bool(rule_rejected)

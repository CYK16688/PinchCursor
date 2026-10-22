from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from numbers import Real
from uuid import uuid4


@dataclass(frozen=True)
class StaticGestureTemplate:
    template_id: str
    name: str
    feature_vector: tuple[float, ...]
    threshold: float = 0.18


class StaticGestureMatcher:
    WRIST = 0
    MIDDLE_MCP = 9

    def normalize(self, landmarks) -> tuple[float, ...] | None:
        """Return a finite, wrist-relative feature vector for exactly 21 landmarks."""
        if not isinstance(landmarks, (list, tuple)) or len(landmarks) != 21:
            return None
        try:
            points = tuple(self._point(landmark) for landmark in landmarks)
        except (TypeError, ValueError, IndexError):
            return None
        if not all(isfinite(value) for point in points for value in point):
            return None
        wrist = points[self.WRIST]
        palm = points[self.MIDDLE_MCP]
        scale = self._distance(wrist, palm)
        if not isfinite(scale) or scale <= 0:
            return None
        features = tuple(
            round((value - wrist[axis]) / scale, 8)
            for point in points
            for axis, value in enumerate(point)
        )
        return features if all(isfinite(value) for value in features) else None

    def create_template(
        self,
        name: str,
        landmark_samples,
        threshold: float = 0.18,
        template_id: str | None = None,
    ) -> StaticGestureTemplate | None:
        features = [self.normalize(sample) for sample in landmark_samples]
        features = [feature for feature in features if feature is not None]
        if not features:
            return None
        average = tuple(
            round(sum(values) / len(values), 8) for values in zip(*features, strict=True)
        )
        return StaticGestureTemplate(
            template_id=template_id or str(uuid4()),
            name=name,
            feature_vector=average,
            threshold=threshold,
        )

    def distance(self, landmarks, template: StaticGestureTemplate) -> float | None:
        current = self.normalize(landmarks)
        if current is None or len(current) != len(template.feature_vector):
            return None
        squared = sum((value - expected) ** 2 for value, expected in zip(current, template.feature_vector))
        return sqrt(squared / len(current))

    def match(self, landmarks, template: StaticGestureTemplate) -> bool:
        distance = self.distance(landmarks, template)
        return distance is not None and distance <= template.threshold

    @staticmethod
    def _point(landmark) -> tuple[float, float, float]:
        if not isinstance(landmark, (list, tuple)) or len(landmark) != 3:
            raise ValueError("a landmark must be an (x, y, z) triple")
        if any(
            not isinstance(value, Real) or isinstance(value, bool)
            for value in landmark
        ):
            raise ValueError("landmark coordinates must be real numbers")
        point = tuple(float(value) for value in landmark)
        if not all(isfinite(value) for value in point):
            raise ValueError("landmark coordinates must be finite")
        return point

    @staticmethod
    def _distance(first, second) -> float:
        return sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))

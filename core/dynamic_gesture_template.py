"""Pure, deterministic dynamic gesture feature extraction and DTW matching."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf, isfinite, sqrt
import re
from time import monotonic
from typing import Iterable, Sequence
from uuid import uuid4

FeatureFrame = tuple[float, ...]
FeatureSequence = tuple[FeatureFrame, ...]

# This is the sole public action allowlist for user-recorded motion. Keep it
# aligned with Settings and persisted-template normalization: dynamic gestures
# are optional semantic commands, never pointer lifecycle controls.
ALLOWED_DYNAMIC_ACTIONS = frozenset(
    {"scroll_up", "scroll_down", "custom_hotkey"}
)
_SAFE_TEMPLATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_FEATURE_WIDTH = 63
# Two extra dimensions (wrist displacement from the segment origin, in palm
# units) make spatial motion visible. Without them the feature is translation
# invariant by construction, so a swipe and a still hand look identical.
_TRAJECTORY_WIDTH = 65
_SUPPORTED_WIDTHS = (_FEATURE_WIDTH, _TRAJECTORY_WIDTH)


def is_allowed_dynamic_action(action: object) -> bool:
    """Return whether ``action`` is an allowed first-version dynamic action."""
    return isinstance(action, str) and action in ALLOWED_DYNAMIC_ACTIONS


def _is_nonnegative_finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return isfinite(value) and value >= 0
    except OverflowError:
        return False


def _has_safe_template_id(template_id: object) -> bool:
    return isinstance(template_id, str) and _SAFE_TEMPLATE_ID.fullmatch(template_id) is not None


def _has_valid_samples(samples: object) -> bool:
    if not isinstance(samples, tuple) or not samples:
        return False
    for sample in samples:
        if not isinstance(sample, tuple) or len(sample) < 2:
            return False
        widths = set()
        for frame in sample:
            if (
                not isinstance(frame, tuple)
                or len(frame) not in _SUPPORTED_WIDTHS
                or not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                    for value in frame
                )
            ):
                return False
            widths.add(len(frame))
        # A sample is one recording; mixed widths mean the sequence was built
        # incorrectly and DTW would compare mismatched channels.
        if len(widths) != 1:
            return False
    return True


@dataclass(frozen=True)
class DynamicGestureTemplate:
    template_id: str
    name: str
    action: str
    samples: tuple[FeatureSequence, ...]
    threshold: float = 0.18
    cooldown_seconds: float = 0.75
    min_motion_energy: float = 0.05
    # Optional AX category this motion is bound to ("" = anywhere). The same
    # gesture can mean different things over a canvas and over a list.
    context_category: str = ""

    def __post_init__(self) -> None:
        """Fail closed when callers bypass the recording factory."""
        if not _is_valid_dynamic_template(self):
            raise ValueError("invalid dynamic gesture template")


def _is_valid_dynamic_template(template: object) -> bool:
    """Return whether a template is safe to use, including bypassed instances."""
    if not isinstance(template, DynamicGestureTemplate):
        return False
    try:
        return (
            _has_safe_template_id(template.template_id)
            and isinstance(template.name, str)
            and bool(template.name.strip())
            and is_allowed_dynamic_action(template.action)
            and _has_valid_samples(template.samples)
            and all(
                _is_nonnegative_finite_number(value)
                for value in (template.threshold, template.cooldown_seconds, template.min_motion_energy)
            )
            and isinstance(template.context_category, str)
            and len(template.context_category) <= 40
        )
    except (AttributeError, TypeError, ValueError):
        return False


class DynamicGestureRuntimeMatcher:
    """Stateful, one-shot runtime gate around a pure template matcher."""

    def __init__(self, matcher: DynamicGestureMatcher, templates: Iterable[DynamicGestureTemplate]):
        self._matcher = matcher
        self._templates = tuple(template for template in templates if _is_valid_dynamic_template(template))
        self._armed = True
        self._last_fired_at: float | None = None

    def ingest(
        self,
        landmarks,
        *,
        active: bool,
        now: float | None = None,
        context_category: str = "",
    ) -> DynamicGestureTemplate | None:
        """Return one matching template, gated by activation, rearm, and cooldown."""
        sequence = self._matcher.prepare_runtime_sequence(landmarks)
        if sequence is None:
            return None

        energy = self._matcher.motion_energy(sequence)
        if not self._armed:
            if energy <= self._matcher.neutral_motion_energy:
                self._armed = True
            return None
        if not active:
            return None

        try:
            current_time = monotonic() if now is None else float(now)
        except (TypeError, ValueError):
            return None
        if not isfinite(current_time):
            return None
        matches: list[tuple[float, DynamicGestureTemplate]] = []
        for template in self._templates:
            if not _is_valid_dynamic_template(template):
                continue
            # A bound template only competes in its own context; unbound ones
            # stay global.
            if template.context_category and template.context_category != context_category:
                continue
            if energy < template.min_motion_energy:
                continue
            if self._last_fired_at is not None and current_time - self._last_fired_at < template.cooldown_seconds:
                continue
            distance = self._matcher.distance_to_template(sequence, template)
            if distance is not None and distance <= template.threshold:
                matches.append((distance, template))

        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], item[1].template_id))
        winner_distance, winner = matches[0]
        if len(matches) > 1 and winner_distance >= matches[1][0]:
            return None
        self._armed = False
        self._last_fired_at = current_time
        return winner

    def reset(self) -> None:
        """Forget the current live gesture sequence after a tracking boundary."""
        self._armed = True
        self._last_fired_at = None


class DynamicGestureMatcher:
    """Extract normalized 21x3 frames, validate recordings, and compare with DTW."""

    WRIST = 0
    MIDDLE_MCP = 9

    def __init__(
        self,
        *,
        sequence_length: int = 24,
        min_recording_frames: int = 8,
        max_recording_frames: int = 180,
        sakoe_chiba_band: int = 6,
        neutral_motion_energy: float = 0.01,
    ):
        if sequence_length < 2:
            raise ValueError("sequence_length must be at least 2")
        if min_recording_frames < 2 or min_recording_frames > max_recording_frames:
            raise ValueError("invalid recording frame bounds")
        if sakoe_chiba_band < 0:
            raise ValueError("sakoe_chiba_band cannot be negative")
        self.sequence_length = sequence_length
        self.min_recording_frames = min_recording_frames
        self.max_recording_frames = max_recording_frames
        self.sakoe_chiba_band = sakoe_chiba_band
        self.neutral_motion_energy = neutral_motion_energy

    def normalize_frame(self, landmarks, origin=None) -> FeatureFrame | None:
        """Return a wrist-relative, palm-scale-normalized 21 x 3 feature frame.

        With ``origin`` (the wrist pixel position at the start of the segment),
        two extra dimensions append the wrist displacement from that origin in
        palm units. That is what makes translation visible to DTW while keeping
        the shape channels scale invariant.
        """
        if landmarks is None:
            return None
        try:
            if len(landmarks) < 21:
                return None
            points = tuple(self._point(landmark) for landmark in landmarks[:21])
        except (TypeError, ValueError, IndexError):
            return None
        if not all(isfinite(value) for point in points for value in point):
            return None
        wrist = points[self.WRIST]
        scale = self._euclidean(wrist, points[self.MIDDLE_MCP])
        if not isfinite(scale) or scale <= 1e-12:
            return None
        shape = tuple(
            round((value - wrist[axis]) / scale, 8)
            for point in points
            for axis, value in enumerate(point)
        )
        if origin is None:
            return shape
        try:
            origin_x, origin_y = float(origin[0]), float(origin[1])
        except (TypeError, IndexError, ValueError):
            return None
        if not (isfinite(origin_x) and isfinite(origin_y)):
            return None
        return shape + (
            round((wrist[0] - origin_x) / scale, 6),
            round((wrist[1] - origin_y) / scale, 6),
        )

    @staticmethod
    def _segment_origin(landmark_frames):
        """Return the wrist pixel position of the first frame, or None."""
        try:
            wrist = landmark_frames[0][0]
            origin = (float(wrist[0]), float(wrist[1]))
        except (TypeError, IndexError, ValueError):
            return None
        return origin

    def prepare_recording(self, landmark_frames) -> FeatureSequence | None:
        """Accept bounded, valid, sufficiently moving takes as fixed-length features."""
        try:
            frame_count = len(landmark_frames)
        except TypeError:
            return None
        if not self.min_recording_frames <= frame_count <= self.max_recording_frames:
            return None
        origin = self._segment_origin(landmark_frames)
        if origin is None:
            return None
        normalized = tuple(self.normalize_frame(frame, origin) for frame in landmark_frames)
        if any(frame is None for frame in normalized):
            return None
        sequence = self.resample(normalized)
        if self.motion_energy(sequence) <= self.neutral_motion_energy:
            return None
        return sequence

    def prepare_runtime_sequence(self, landmark_frames) -> FeatureSequence | None:
        """Normalize one bounded live window without applying recording-length rules."""
        try:
            if len(landmark_frames) < 2:
                return None
        except TypeError:
            return None
        origin = self._segment_origin(landmark_frames)
        if origin is None:
            return None
        normalized = tuple(self.normalize_frame(frame, origin) for frame in landmark_frames)
        if any(frame is None for frame in normalized):
            return None
        return self.resample(normalized)

    def resample(self, sequence: Sequence[FeatureFrame | None]) -> FeatureSequence:
        """Causally interpolate a normalized sequence to the configured fixed length."""
        if len(sequence) < 2 or any(frame is None for frame in sequence):
            raise ValueError("a sequence needs at least two complete feature frames")
        frames = tuple(sequence)  # type: ignore[arg-type]
        width = len(frames[0])
        if width == 0 or any(len(frame) != width for frame in frames):
            raise ValueError("feature frames must share a non-zero width")
        if len(frames) == self.sequence_length:
            return frames
        last = len(frames) - 1
        result: list[FeatureFrame] = []
        for output_index in range(self.sequence_length):
            source = output_index * last / (self.sequence_length - 1)
            lower = int(source)
            upper = min(lower + 1, last)
            fraction = source - lower
            result.append(
                tuple(
                    frames[lower][index] * (1.0 - fraction) + frames[upper][index] * fraction
                    for index in range(width)
                )
            )
        return tuple(result)

    def motion_energy(self, sequence: Sequence[FeatureFrame]) -> float:
        """Mean normalized feature displacement between adjacent frames."""
        if len(sequence) < 2:
            return 0.0
        try:
            displacements = [
                self._frame_distance(previous, current)
                for previous, current in zip(sequence, sequence[1:])
            ]
        except (TypeError, ValueError):
            return 0.0
        return sum(displacements) / len(displacements)

    def create_template(
        self,
        name: str,
        action: str,
        landmark_samples,
        *,
        threshold: float = 0.18,
        cooldown_seconds: float = 0.75,
        min_motion_energy: float = 0.05,
        template_id: str | None = None,
        context_category: str = "",
    ) -> DynamicGestureTemplate | None:
        """Build a template from every valid accepted recording sample."""
        if not is_allowed_dynamic_action(action):
            return None
        if not name or not isinstance(name, str):
            return None
        if not all(_is_nonnegative_finite_number(value) for value in (threshold, cooldown_seconds, min_motion_energy)):
            return None
        if template_id is not None and not _has_safe_template_id(template_id):
            return None
        samples = tuple(
            prepared
            for sample in landmark_samples
            if (prepared := self.prepare_recording(sample)) is not None
        )
        if not samples:
            return None
        return DynamicGestureTemplate(
            template_id=template_id or str(uuid4()),
            name=name,
            action=action,
            samples=samples,
            threshold=threshold,
            cooldown_seconds=cooldown_seconds,
            min_motion_energy=min_motion_energy,
            context_category=context_category,
        )

    def dtw_distance(self, first: Sequence[FeatureFrame], second: Sequence[FeatureFrame]) -> float:
        """Deterministic DTW normalized by path length within a Sakoe-Chiba band."""
        if not first or not second:
            return inf
        n, m = len(first), len(second)
        if any(len(frame) != len(first[0]) for frame in first) or any(len(frame) != len(second[0]) for frame in second):
            return inf
        band = max(self.sakoe_chiba_band, abs(n - m))
        previous: dict[int, tuple[float, int]] = {0: (0.0, 0)}
        for i in range(1, n + 1):
            current: dict[int, tuple[float, int]] = {}
            for j in range(max(1, i - band), min(m, i + band) + 1):
                candidates = (previous.get(j), current.get(j - 1), previous.get(j - 1))
                best = min((candidate for candidate in candidates if candidate is not None), default=None, key=lambda item: (item[0], item[1]))
                if best is None:
                    continue
                local = self._frame_distance(first[i - 1], second[j - 1])
                current[j] = (best[0] + local, best[1] + 1)
            previous = current
        total, path_length = previous.get(m, (inf, 0))
        return total / path_length if path_length else inf

    def distance_to_template(self, sequence: FeatureSequence, template: DynamicGestureTemplate) -> float | None:
        if not _is_valid_dynamic_template(template) or not sequence:
            return None
        best = inf
        for sample in template.samples:
            if not sample:
                continue
            width = min(len(sequence[0]), len(sample[0]))
            current = tuple(frame[:width] for frame in sequence)
            recorded = tuple(frame[:width] for frame in sample)
            best = min(best, self.dtw_distance(current, recorded))
        return best if isfinite(best) else None

    def suggest_threshold(
        self, samples, *, slack: float = 1.5, floor: float = 0.06, cap: float = 0.45
    ) -> float | None:
        """Derive a template threshold from how far apart the user's takes are.

        A fixed 0.18 either rejects a stable motion or accepts everything,
        depending on the person. The worst pairwise distance between the takes
        times ``slack`` is a per-user estimate of "still the same motion".
        """
        prepared = [sample for sample in samples if sample]
        if len(prepared) < 2:
            return None
        worst = 0.0
        for index, first in enumerate(prepared):
            for second in prepared[index + 1:]:
                width = min(len(first[0]), len(second[0]))
                value = self.dtw_distance(
                    tuple(frame[:width] for frame in first),
                    tuple(frame[:width] for frame in second),
                )
                if not isfinite(value):
                    return None
                worst = max(worst, value)
        return max(floor, min(cap, worst * slack))

    def create_runtime_matcher(self, templates: Iterable[DynamicGestureTemplate]) -> DynamicGestureRuntimeMatcher:
        return DynamicGestureRuntimeMatcher(self, templates)

    @staticmethod
    def _point(landmark) -> tuple[float, float, float]:
        return float(landmark[0]), float(landmark[1]), float(landmark[2])

    @staticmethod
    def _euclidean(first: Sequence[float], second: Sequence[float]) -> float:
        return sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))

    @staticmethod
    def _frame_distance(first: FeatureFrame, second: FeatureFrame) -> float:
        if len(first) != len(second) or not first:
            return inf
        return sqrt(sum((a - b) ** 2 for a, b in zip(first, second)) / len(first))

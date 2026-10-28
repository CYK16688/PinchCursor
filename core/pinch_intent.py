"""Causal physical pinch admission and a palm-transported pointing channel.

All distances are in wrist-to-middle-MCP units, positions in camera space,
and times in seconds. These are conservative *policies*, not learned camera
calibration: 200 ms history/gap, 40 ms open qualification, 55 ms closed
qualification, and 250 ms candidate timeout need real camera validation.
Palm transport assumes a locally rigid, approximately planar palm; perspective
or tracking changes that violate it cancel the episode rather than click.
There is deliberately no maximum hand speed: motion consistency uses changes
in velocity, allowing a moving hand to pinch and subsequently drag.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import atan2, hypot, isfinite, pi
from numbers import Real

Point = tuple[float, float]


@dataclass(frozen=True)
class PinchEvidence:
    """One frame of physical intent; trace is fixed at ``new_episode``.

    ``reference_at`` identifies a trusted open filter snapshot. ``corrections``
    includes that sample and the causal closing lead-in through admission.
    ``target_at`` identifies the first >0.03-unit gap reduction in that trace;
    the 0.03 jitter floor is another policy requiring camera validation.
    Filter replay should restore the reference snapshot and skip any trace
    sample already represented by that snapshot.
    """

    phase: str = "idle"
    owns_pointer: bool = False
    new_episode: bool = False
    motion_position: Point | None = None
    target_position: Point | None = None
    closed_at: float | None = None
    opened_at: float | None = None
    reason: str = ""
    reference_at: float | None = None
    target_at: float | None = None
    corrections: tuple[tuple[float, Point], ...] = ()
    # Current, coherent open pointing can move even while click rearming waits.
    movement_allowed: bool = False


@dataclass(frozen=True)
class _Palm:
    wrist: Point
    up: Point
    scale: float
    shape: tuple[float, ...]

    def local(self, point: Point) -> Point:
        dx, dy = point[0] - self.wrist[0], point[1] - self.wrist[1]
        return ((dx * self.up[1] - dy * self.up[0]) / self.scale,
                (dx * self.up[0] + dy * self.up[1]) / self.scale)

    def transport(self, point: Point) -> Point:
        x, y = point
        return (self.wrist[0] + self.scale * (x * self.up[1] + y * self.up[0]),
                self.wrist[1] + self.scale * (-x * self.up[0] + y * self.up[1]))


@dataclass(frozen=True)
class _Sample:
    now: float
    palm: _Palm
    tip: Point
    gap: float
    others: tuple[float, ...]


class PinchIntentObserver:
    """Reserve one physical episode, including rejected/chattering frames.

    ``pointing`` must describe the current raw pose, not a delayed UI label.
    ``raw_pinching`` is the physical thumb-index gate before label stabilization.
    ``competing_pose`` identifies a known alternative raw pose (for example a
    thumb scroll pose); it excludes idle contraction-only admission, but cannot
    relinquish an existing episode or override a physically closed pinch.
    Confirmed/released evidence carries the first physical closed/open time;
    confidence qualification has a separate clock and never shortens a hold.
    A rejected episode remains cancelled until genuine open pointing returns;
    ``reset`` is intended for explicit hand/session lifecycle boundaries.
    """

    HISTORY_SECONDS = 0.20
    OPEN_SECONDS = 0.04
    CLOSED_SECONDS = 0.055
    CANDIDATE_SECONDS = 0.25
    OPEN_GAP = 0.50
    CONTRACTION = 0.10
    CONTRACTION_FRACTION = 0.15
    MIN_CONFIDENCE = 0.45
    MAX_SHAPE_CHANGE = 0.30
    MAX_SCALE_STEP = 1.40
    MAX_ROTATION_STEP = pi / 3
    MAX_MOTION_RESIDUAL = 1.50

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._phase = "idle"
        self._history: deque[_Sample] = deque(maxlen=64)
        self._open_history: deque[_Sample] = deque(maxlen=64)
        self._last: _Sample | None = None
        self._velocity: Point | None = None
        self._open_at: float | None = None
        self._open_count = 0
        self._closed_at: float | None = None
        self._confident_closed_at: float | None = None
        self._closed_count = 0
        self._release_at: float | None = None
        self._release_count = 0
        self._reopen_history: deque[_Sample] = deque(maxlen=64)
        self._candidate_at: float | None = None
        self._local_tip: Point | None = None
        self._reference: _Sample | None = None
        self._target: Point | None = None
        self._motion: Point | None = None
        self._reason = ""
        self._reference_at: float | None = None
        self._target_at: float | None = None
        self._corrections: tuple[tuple[float, Point], ...] = ()
        self._seen_closed = False

    @staticmethod
    def _finite(value) -> bool:
        return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)

    @classmethod
    def _sample(cls, landmarks, now: float) -> _Sample | None:
        if not isinstance(landmarks, (tuple, list)) or len(landmarks) != 21:
            return None
        points = []
        for point in landmarks:
            if (not isinstance(point, (tuple, list)) or len(point) < 2
                    or not all(cls._finite(value) for value in point)):
                return None
            points.append((float(point[0]), float(point[1])))
        wrist, middle = points[0], points[9]
        scale = hypot(middle[0] - wrist[0], middle[1] - wrist[1])
        if scale < 1e-6:
            return None
        up = ((middle[0] - wrist[0]) / scale, (middle[1] - wrist[1]) / scale)
        palm = _Palm(wrist, up, scale, ())
        left, right = palm.local(points[5]), palm.local(points[17])
        # MCP separation is required to distinguish a palm from collapsed or
        # collinear landmark hallucinations, while allowing either handedness.
        if not 0.25 <= hypot(left[0] - right[0], left[1] - right[1]) <= 3.0:
            return None
        if left[0] * right[0] >= 0 or max(abs(left[1]), abs(right[1])) > 2.2:
            return None
        palm = _Palm(wrist, up, scale, (*left, *right))
        gap = hypot(points[4][0] - points[8][0], points[4][1] - points[8][1]) / scale
        others = tuple(hypot(points[i][0] - wrist[0], points[i][1] - wrist[1]) / scale
                       for i in (12, 16, 20))
        return _Sample(now, palm, points[8], gap, others)

    def _evidence(self, *, new=False, phase=None, movement_allowed=False) -> PinchEvidence:
        phase = self._phase if phase is None else phase
        return PinchEvidence(phase, phase in {"candidate", "confirmed", "cancelled", "released"},
                             new, self._motion, self._target, self._closed_at,
                             self._release_at, self._reason, self._reference_at,
                             self._target_at, self._corrections, movement_allowed)

    def _cancel(self, reason: str) -> None:
        self._phase = "cancelled"
        self._reason = reason
        self._history.clear()
        self._open_history.clear()
        self._open_at = None
        self._open_count = 0
        self._release_at = None
        self._release_count = 0
        self._reopen_history.clear()

    def _coherence_reason(self, sample: _Sample) -> str:
        previous = self._last
        if previous is None:
            return ""
        palm, old = sample.palm, previous.palm
        ratio = palm.scale / old.scale
        if not 1 / self.MAX_SCALE_STEP <= ratio <= self.MAX_SCALE_STEP:
            return "palm_scale"
        reference = (self._reference.palm if self._reference is not None
                     and self._phase in {"candidate", "confirmed"} else old)
        if max(abs(a - b) for a, b in zip(palm.shape, reference.shape)) > self.MAX_SHAPE_CHANGE:
            return "palm_shape"
        turn = atan2(palm.up[1], palm.up[0]) - atan2(old.up[1], old.up[0])
        if abs((turn + pi) % (2 * pi) - pi) > self.MAX_ROTATION_STEP:
            return "palm_rotation"
        if self._velocity is not None:
            dt = sample.now - previous.now
            expected = (old.wrist[0] + self._velocity[0] * dt,
                        old.wrist[1] + self._velocity[1] * dt)
            residual = hypot(palm.wrist[0] - expected[0], palm.wrist[1] - expected[1])
            if residual / max(palm.scale, old.scale) > self.MAX_MOTION_RESIDUAL:
                return "palm_teleport"
        return ""

    def _observe_open(self, sample: _Sample) -> bool:
        if self._open_at is None:
            self._open_at = sample.now
        self._open_count += 1
        self._history.append(sample)
        self._open_history.append(sample)
        return self._open_count >= 2 and sample.now - self._open_at + 1e-9 >= self.OPEN_SECONDS

    def _clear_open_references(self) -> None:
        self._history.clear()
        self._open_history.clear()
        self._open_at = None
        self._open_count = 0

    def update(self, landmarks, *, now, raw_pinching: bool, pointing: bool,
               transition: bool = False, pinch_confidence: float = 1.0,
               enabled: bool = True, competing_pose: bool = False) -> PinchEvidence:
        if not enabled:
            self.reset()
            return self._evidence()
        sample = self._sample(landmarks, float(now)) if self._finite(now) else None
        if sample is None:
            self._cancel("invalid_observation")
            self._last = None
            self._velocity = None
            return self._evidence()
        now = sample.now
        if self._last is not None and (now <= self._last.now
                                       or now - self._last.now > self.HISTORY_SECONDS):
            self._cancel("timestamp_discontinuity")
            self._last = None
            self._velocity = None
            # This frame cannot count as either an opening or closing sample.
            return self._evidence()
        while self._history and now - self._history[0].now > self.HISTORY_SECONDS:
            self._history.popleft()
        while self._open_history and now - self._open_history[0].now > self.HISTORY_SECONDS:
            self._open_history.popleft()
        while self._reopen_history and now - self._reopen_history[0].now > self.HISTORY_SECONDS:
            self._reopen_history.popleft()
        reason = self._coherence_reason(sample)
        previous = self._last
        self._last = sample
        if previous is not None:
            dt = now - previous.now
            self._velocity = ((sample.palm.wrist[0] - previous.palm.wrist[0]) / dt,
                              (sample.palm.wrist[1] - previous.palm.wrist[1]) / dt)
        if reason:
            self._cancel(reason)
            self._velocity = None
            return self._evidence()
        self._motion = sample.palm.transport(self._local_tip) if self._local_tip is not None else sample.tip
        genuinely_open = bool(pointing and not raw_pinching and not transition and sample.gap >= self.OPEN_GAP)

        if self._phase == "released":
            # Genuine open evidence gathered while qualifying release already
            # forms the next baseline. Do not discard it at this boundary.
            self._phase = "idle"
            self._target = self._local_tip = self._reference = None
            self._closed_at = self._release_at = self._candidate_at = None
            self._confident_closed_at = None
            self._closed_count = self._release_count = 0
            self._seen_closed = False
            self._reference_at = self._target_at = None
            self._corrections = ()
            self._open_at = self._open_history[0].now if self._open_history else None
            self._open_count = len(self._open_history)
            self._reopen_history.clear()
            self._motion = sample.tip

        if self._phase == "cancelled":
            if genuinely_open and self._observe_open(sample):
                self._phase = "idle"
                self._reason = ""
                self._local_tip = self._target = self._reference = None
                self._closed_at = self._release_at = None
                self._confident_closed_at = None
                self._closed_count = self._release_count = 0
                self._reference_at = self._target_at = None
                self._corrections = ()
                self._seen_closed = False
                self._motion = sample.tip
            elif not genuinely_open:
                self._open_at = None
                self._open_count = 0
                self._history.clear()
                self._open_history.clear()
            return self._evidence(movement_allowed=genuinely_open)

        new = False
        if self._phase == "idle":
            if competing_pose and not raw_pinching:
                self._clear_open_references()
                return self._evidence()
            qualified = (len(self._open_history) >= 2
                         and self._open_history[-1].now - self._open_history[0].now
                         + 1e-9 >= self.OPEN_SECONDS)
            reference = None
            if qualified:
                peak = max(item.gap for item in self._open_history)
                reference = next(item for item in reversed(self._open_history) if item.gap >= peak - 0.02)
            contracting = bool(reference is not None
                               and reference.gap - sample.gap >= self.CONTRACTION
                               and sample.gap <= reference.gap * (1 - self.CONTRACTION_FRACTION))
            if raw_pinching or contracting:
                if not qualified or transition:
                    self._cancel("unqualified_onset" if not qualified else "transition")
                    return self._evidence()
                self._phase = "candidate"
                self._candidate_at = now
                self._reference = reference
                self._local_tip = reference.palm.local(reference.tip)
                self._motion = sample.palm.transport(self._local_tip)
                trace = [item for item in self._history if item.now >= reference.now]
                trace.append(sample)
                onset = next((item for item in trace if reference.gap - item.gap > 0.03), sample)
                self._target = onset.palm.transport(self._local_tip)
                self._reference_at, self._target_at = reference.now, onset.now
                self._corrections = tuple((item.now, item.palm.transport(self._local_tip)) for item in trace)
                self._closed_at = self._release_at = None
                self._confident_closed_at = None
                self._closed_count = self._release_count = 0
                self._reopen_history.clear()
                self._seen_closed = False
                self._reason = ""
                new = True
            else:
                if genuinely_open:
                    self._observe_open(sample)
                elif qualified and not transition:
                    # Keep causal lead-in samples even when the index no
                    # longer earns a point label while approaching the thumb.
                    self._history.append(sample)
                else:
                    self._history.clear()
                    self._open_history.clear()
                    self._open_at = None
                    self._open_count = 0
                return self._evidence()

        other_contraction = sum(before - after > 0.22 for before, after in
                                zip(self._reference.others, sample.others)) >= 2
        if transition or other_contraction:
            self._cancel("transition" if transition else "other_fingers_contracting")
            return self._evidence(new=new)

        # Closure qualification follows physical evidence, independent of any
        # stabilized gesture label and independent of candidate lead-in time.
        confident_closed = (raw_pinching and self._finite(pinch_confidence)
                            and pinch_confidence >= self.MIN_CONFIDENCE)
        if raw_pinching:
            self._seen_closed = True
            if self._closed_at is None:
                self._closed_at = now
        if confident_closed:
            self._release_at = None
            self._release_count = 0
            self._reopen_history.clear()
            if self._confident_closed_at is None:
                self._confident_closed_at = now
                self._closed_count = 0
            self._closed_count += 1
            if (self._closed_count >= 2
                    and now - self._confident_closed_at + 1e-9 >= self.CLOSED_SECONDS):
                self._phase = "confirmed"
        elif raw_pinching:
            if self._phase != "confirmed":
                self._confident_closed_at = None
                self._closed_count = 0
            self._release_at = None
            self._release_count = 0
            self._reopen_history.clear()
        elif self._seen_closed or sample.gap >= self._reference.gap - 0.04:
            if self._release_at is None:
                self._release_at = now
            self._release_count += 1
            if genuinely_open:
                self._reopen_history.append(sample)
            else:
                self._reopen_history.clear()
            if (self._release_count >= 2
                    and now - self._release_at + 1e-9 >= self.OPEN_SECONDS):
                if self._phase == "confirmed":
                    self._phase = "released"
                    self._history.clear()
                    self._open_history.clear()
                    self._history.extend(self._reopen_history)
                    self._open_history.extend(self._reopen_history)
                    return self._evidence(new=new)
                self._cancel("unconfirmed_release")
                return self._evidence(new=new, movement_allowed=genuinely_open)
            if self._phase != "confirmed":
                # A brief false sample may be tracking chatter. It reserves
                # the same episode but cannot earn closed dwell time.
                self._closed_at = None
                self._confident_closed_at = None
                self._closed_count = 0
        else:
            self._release_at = None
            self._release_count = 0
            self._reopen_history.clear()
        if (self._phase == "candidate"
                and now - self._candidate_at > self.CANDIDATE_SECONDS):
            self._cancel("candidate_timeout")
        return self._evidence(new=new, movement_allowed=self._phase == "cancelled" and genuinely_open)

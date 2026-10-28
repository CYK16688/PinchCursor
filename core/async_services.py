"""Bounded auxiliary work outside the pointer-control thread.

Accessibility lookups and telemetry writes can take arbitrarily long. Neither
service waits for them on the producer path, and neither creates a thread per
request. A stuck native call therefore disables context assistance while basic
pointer control remains available.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import islice
import math
import threading
import time

from platform_services.contracts import UIContext
from platform_services.policy import ContextPolicy


_UNAVAILABLE = UIContext(category="generic", source="async_unavailable", is_enabled=False)


@dataclass(frozen=True)
class _ContextRequest:
    x: int | None
    y: int | None
    radius: int | float | None
    generation: int


@dataclass(frozen=True)
class _ContextSnapshot:
    request: _ContextRequest
    started_at: float
    value: UIContext | tuple[UIContext, ...]


def _immutable_context(value: UIContext) -> UIContext:
    if not isinstance(value, UIContext):
        raise TypeError("context provider must return UIContext")
    if not all(isinstance(field, str) for field in (
        value.category, value.native_role, value.source, value.target_id,
    )):
        raise TypeError("context metadata must be immutable strings")
    bounds = None if value.bounds is None else tuple(value.bounds)
    if bounds is not None and (
        len(bounds) != 4
        or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds)
    ):
        raise ValueError("invalid context bounds")
    return UIContext(
        category=value.category,
        native_role=value.native_role,
        source=value.source,
        target_id=value.target_id,
        bounds=bounds,
        is_enabled=value.is_enabled,
    )


class AsyncContextProvider:
    """Latest-only accessibility snapshots, never synchronous native lookups.

    At most one lookup is executing and one request per kind is pending. Cache
    age includes the duration of the lookup, rather than starting when it
    finishes. Missing, failed, expired, or spatially unrelated snapshots cannot
    authorize contextual actions. Core pointer actions bypass contextual policy
    in the coordinator, as they do for a synchronous provider.
    """

    def __init__(
        self,
        provider,
        policy: ContextPolicy | None = None,
        clock=time.monotonic,
        max_age: float = 0.12,
        max_distance: float = 12,
    ):
        if not math.isfinite(max_age) or max_age < 0:
            raise ValueError("max_age must be finite and nonnegative")
        if not math.isfinite(max_distance) or max_distance < 0:
            raise ValueError("max_distance must be finite and nonnegative")
        self._provider = provider
        inherited_policy = getattr(provider, "policy", None)
        self.policy = policy if policy is not None else inherited_policy or ContextPolicy.default()
        self._clock = clock
        self.max_age = max_age
        self.max_distance = max_distance
        self._condition = threading.Condition()
        self._pending: dict[str, _ContextRequest] = {}
        self._snapshots: dict[str, _ContextSnapshot] = {}
        self._generation = 0
        self._closed = False
        self._active: str | None = None
        self._last_kind = "probe"
        self._dropped = 0
        self._errors = 0
        self._completed = 0
        self._worker = threading.Thread(target=self._run, name="context-lookups", daemon=True)
        self._worker.start()

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def dropped_requests(self) -> int:
        with self._condition:
            return self._dropped

    @property
    def errors(self) -> int:
        with self._condition:
            return self._errors

    @property
    def statistics(self) -> dict[str, int]:
        with self._condition:
            return {
                "pending": len(self._pending),
                "inflight": int(self._active is not None),
                "dropped": self._dropped,
                "errors": self._errors,
                "completed": self._completed,
            }

    def get_context(self, x: int | None = None, y: int | None = None) -> UIContext:
        snapshot = self._request("context", x, y)
        return snapshot.value if snapshot is not None else _UNAVAILABLE

    def probe_targets(self, x: int, y: int, radius: int = 120) -> tuple[UIContext, ...]:
        if isinstance(radius, bool) or not isinstance(radius, (int, float)):
            return ()
        if not math.isfinite(radius) or radius <= 0:
            return ()
        snapshot = self._request("probe", x, y, radius)
        return snapshot.value if snapshot is not None else ()

    def is_gesture_allowed(self, gesture: str, x: int | None = None, y: int | None = None) -> bool:
        if not self.policy.enabled:
            # Disabling context filtering must preserve ordinary user bindings
            # even if AX is unavailable. Explicit target identity remains the
            # coordinator's independent check for contextual requests.
            return not self._closed
        snapshot = self._request("context", x, y)
        return (
            self._can_authorize(snapshot)
            and self.policy.is_gesture_allowed(snapshot.value, gesture)
        )

    def is_action_allowed(self, action: str, x: int | None = None, y: int | None = None) -> bool:
        if not self.policy.enabled:
            return not self._closed
        snapshot = self._request("context", x, y)
        return (
            self._can_authorize(snapshot)
            and self.policy.is_action_allowed(snapshot.value, action)
        )

    @staticmethod
    def _can_authorize(snapshot: _ContextSnapshot | None) -> bool:
        return (
            snapshot is not None
            and snapshot.value.is_enabled
            and snapshot.value.source not in {"accessibility_unavailable", "missing_coordinates"}
        )

    def invalidate(self) -> None:
        """Discard cached and queued lookups, including eventual in-flight results."""
        with self._condition:
            self._invalidate_locked()

    def _invalidate_locked(self) -> None:
        self._generation += 1
        self._snapshots.clear()
        self._dropped += len(self._pending)
        self._pending.clear()

    def close(self, timeout: float = 0.1) -> bool:
        """Stop accepting requests; return whether the daemon exited in time."""
        with self._condition:
            self._closed = True
            self._invalidate_locked()
            self._condition.notify_all()
        self._worker.join(max(0.0, timeout))
        return not self._worker.is_alive()

    def _request(self, kind: str, x, y, radius=None) -> _ContextSnapshot | None:
        if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)) for v in (x, y)):
            return None
        with self._condition:
            if self._closed:
                return None
            request = _ContextRequest(x, y, radius, self._generation)
            pending = self._pending.get(kind)
            if pending != request:
                if pending is not None:
                    self._dropped += 1
                self._pending[kind] = request
                self._condition.notify()
            snapshot = self._snapshots.get(kind)
            if snapshot is None:
                return None
            age = self._clock() - snapshot.started_at
            if not 0 <= age <= self.max_age or snapshot.request.radius != radius:
                return None
            old_x, old_y = snapshot.request.x, snapshot.request.y
            if None in (x, y, old_x, old_y):
                # An implicit cursor position cannot be spatially verified after
                # a background lookup. Keep that result unavailable to actions.
                return None
            if math.hypot(x - old_x, y - old_y) > self.max_distance:
                return None
            return snapshot

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or bool(self._pending))
                if self._closed:
                    return
                # Give probes a turn even while context is requested every frame.
                kind = "probe" if self._last_kind == "context" else "context"
                if kind not in self._pending:
                    kind = next(iter(self._pending))
                request = self._pending.pop(kind)
                self._active = kind
                self._last_kind = kind
            started_at = self._clock()
            try:
                if kind == "context":
                    value = _immutable_context(self._provider.get_context(request.x, request.y))
                else:
                    probe = getattr(self._provider, "probe_targets", None)
                    targets = () if probe is None else probe(request.x, request.y, request.radius)
                    value = tuple(_immutable_context(target) for target in islice(targets, 64))
                snapshot = _ContextSnapshot(request, started_at, value)
            except Exception:
                snapshot = None
                with self._condition:
                    self._errors += 1
            with self._condition:
                self._active = None
                self._completed += 1
                if not self._closed and request.generation == self._generation:
                    if snapshot is None:
                        self._snapshots.pop(kind, None)
                    else:
                        self._snapshots[kind] = snapshot
                self._condition.notify_all()


# Copy only the store's diagnostic schema. Unknown values, including accidental
# image/landmark payloads, must not even remain queued in memory.
_EVENT_FIELDS = frozenset({
    "app", "category", "role", "gesture", "action", "executed", "confidence",
    "latency_ms", "x", "y", "target_w", "target_h", "snap_distance",
})
_CANDIDATE_FIELDS = frozenset({
    "role", "x", "y", "w", "h", "dist", "inside", "bayes", "chosen_bayes", "chosen_raw",
})


def _scalar(value):
    if isinstance(value, str):
        return value[:256]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def _vector(values) -> tuple[float, ...]:
    if values is None:
        return ()
    try:
        return tuple(float(value) for value in islice(values, 64))
    except (TypeError, ValueError, OverflowError):
        return ()


@dataclass(frozen=True)
class _TelemetryWrite:
    sequence: int
    method: str
    args: tuple
    kwargs: dict


class AsyncTelemetry:
    """Opt-in telemetry delivery on one worker with a bounded FIFO.

    Saturation drops the newest event instead of delaying pointer control.
    Payloads are schema-filtered copies with at most 64 candidates/features.
    ``flush`` waits for already accepted calls to reach the underlying store;
    its normal commit policy still governs disk durability. The owner must only
    close the store after ``close`` returns True, or defer store disposal until
    a later successful close. This wrapper never closes the store itself.
    """

    def __init__(self, store, max_pending: int = 256):
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be a positive integer")
        self._store = store
        self.max_pending = max_pending
        self._condition = threading.Condition()
        self._pending: deque[_TelemetryWrite] = deque()
        self._closed = False
        self._inflight = False
        self._accepted = 0
        self._completed = 0
        self._dropped = 0
        self._errors = 0
        self._worker = threading.Thread(target=self._run, name="telemetry-writer", daemon=True)
        self._worker.start()

    @property
    def enabled(self) -> bool:
        return not self._closed and bool(self._store.enabled)

    @property
    def path(self):
        return self._store.path

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def dropped_records(self) -> int:
        with self._condition:
            return self._dropped

    @property
    def errors(self) -> int:
        with self._condition:
            return self._errors

    @property
    def statistics(self) -> dict[str, int]:
        with self._condition:
            return {
                "pending": len(self._pending),
                "inflight": int(self._inflight),
                "accepted": self._accepted,
                "completed": self._completed,
                "dropped": self._dropped,
                "errors": self._errors,
            }

    def record(self, kind: str, *, timestamp: float | None = None, **fields) -> None:
        if not self.enabled:
            return
        copied = {key: _scalar(value) for key, value in fields.items() if key in _EVENT_FIELDS}
        copied["timestamp"] = time.time() if timestamp is None else _scalar(timestamp)
        self._submit("record", (_scalar(kind),), copied)

    def record_candidates(self, lock_id: str, rows, *, timestamp=None) -> None:
        if not self.enabled:
            return
        if rows is None:
            return
        copied = []
        for row in islice(rows, 64):
            if not isinstance(row, dict):
                continue
            candidate = {key: _scalar(value) for key, value in row.items() if key in _CANDIDATE_FIELDS}
            candidate["features"] = _vector(row.get("features"))
            copied.append(candidate)
        self._submit("record_candidates", (_scalar(lock_id), tuple(copied)), {
            "timestamp": time.time() if timestamp is None else _scalar(timestamp),
        })

    def record_transition(
        self, *, features, label: int, outcome: str = "", rule_rejected: bool = False,
        duration: float = 0.0, model_score: float | None = None, timestamp: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        self._submit("record_transition", (), {
            "features": _vector(features),
            "label": _scalar(label),
            "outcome": _scalar(outcome),
            "rule_rejected": _scalar(rule_rejected),
            "duration": _scalar(duration),
            "model_score": _scalar(model_score),
            "timestamp": time.time() if timestamp is None else _scalar(timestamp),
        })

    def _submit(self, method: str, args: tuple, kwargs: dict) -> None:
        with self._condition:
            if self._closed:
                return
            if len(self._pending) >= self.max_pending:
                self._dropped += 1
                return
            self._accepted += 1
            self._pending.append(_TelemetryWrite(self._accepted, method, args, kwargs))
            self._condition.notify()

    def flush(self, timeout: float = 0.1) -> bool:
        """Wait at most timeout for calls already accepted at entry."""
        with self._condition:
            target = self._accepted
            return self._condition.wait_for(lambda: self._completed >= target, timeout=max(0.0, timeout))

    def close(self, timeout: float = 0.1) -> bool:
        """Drain accepted calls, bounded by timeout; never close the store."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._worker.join(max(0.0, timeout))
        return not self._worker.is_alive()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or bool(self._pending))
                if not self._pending:
                    return
                write = self._pending.popleft()
                self._inflight = True
            try:
                getattr(self._store, write.method)(*write.args, **write.kwargs)
            except Exception:
                with self._condition:
                    self._errors += 1
            finally:
                with self._condition:
                    self._inflight = False
                    self._completed = write.sequence
                    self._condition.notify_all()

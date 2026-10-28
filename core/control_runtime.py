"""Bounded actor for continuous input; no Qt event delivery is required."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import threading
import time

from core.control_engine import ControlSnapshot, DispatchOutcome, HandObservation


@dataclass(frozen=True)
class RuntimeMetrics:
    submitted: int = 0
    processed: int = 0
    dropped: int = 0
    feedback_dropped: int = 0
    last_step_ms: float = 0.0
    max_step_ms: float = 0.0
    frame_age_ms: float = 0.0


@dataclass(frozen=True)
class RuntimeView:
    snapshot: ControlSnapshot
    frame: object
    outcomes: tuple[DispatchOutcome, ...]
    metrics: RuntimeMetrics
    power_mode: str = "normal"


class ControlRuntime:
    """One owner for decision state, one pending observation, one preview.

    Replacing a pending observation prioritizes the present over latency from a
    backlog. Discrete action feedback has a separate bounded buffer so a later
    move does not immediately erase a click before the GUI next paints.
    ``stop`` revokes dispatch synchronously before waiting for the worker.
    Instances cannot restart; construct a new engine at the stopped boundary.
    """

    def __init__(self, engine, *, clock=time.monotonic):
        self._engine = engine
        self._guard = engine.action_coordinator.input_guard
        self._clock = clock
        self._condition = threading.Condition()
        self._thread = None
        self._accepting = False
        self._stopping = False
        self._pending = None
        self._latest = None
        self._outcomes = deque(maxlen=64)
        self._metrics = RuntimeMetrics()
        self._no_hand_frames = 0
        self._power_mode = "normal"

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def power_mode(self):
        with self._condition:
            return self._power_mode

    @property
    def metrics(self):
        with self._condition:
            return self._metrics

    def start(self):
        with self._condition:
            if self._thread is not None or self._stopping:
                raise RuntimeError("ControlRuntime instances cannot restart")
            self._guard.start()
            self._accepting = True
            self._thread = threading.Thread(target=self._run, name="gesture-control", daemon=True)
            self._thread.start()

    def submit(self, observation: HandObservation, frame=None):
        with self._condition:
            if not self._accepting:
                return False
            self._metrics = replace(
                self._metrics,
                submitted=self._metrics.submitted + 1,
                dropped=self._metrics.dropped + (self._pending is not None),
            )
            self._pending = (observation, frame)
            self._condition.notify()
            return True

    def take_latest(self):
        with self._condition:
            if self._latest is None:
                return None
            snapshot, frame = self._latest
            self._latest = None
            outcomes = tuple(self._outcomes)
            self._outcomes.clear()
            return RuntimeView(snapshot, frame, outcomes, self._metrics, self._power_mode)

    def _publish(self, snapshot, frame):
        with self._condition:
            if self._stopping:
                return
            self._latest = (snapshot, frame)
            for outcome in snapshot.outcomes:
                # Continuous feedback is represented by snapshot.pointer_state.
                # Retain only discrete outcomes/errors in the event mailbox.
                if outcome.result.executed and outcome.request.action in {"move_cursor", "drag", "none"}:
                    continue
                if len(self._outcomes) == self._outcomes.maxlen:
                    self._metrics = replace(self._metrics, feedback_dropped=self._metrics.feedback_dropped + 1)
                self._outcomes.append(outcome)

    def _reset_snapshot(self, error):
        self._engine._outcomes = list(self._engine.reset())
        return self._engine._snapshot(self._clock(), error=error)

    def _run(self):
        try:
            while True:
                with self._condition:
                    if self._pending is None and not self._stopping:
                        self._condition.wait(timeout=0.025)
                    if self._stopping:
                        break
                    pending, self._pending = self._pending, None
                if pending is None:
                    if self._guard.consume_interruption():
                        self._publish(self._reset_snapshot("input_interrupted"), None)
                    continue
                observation, frame = pending
                started = self._clock()
                snapshot = self._engine.step(observation)
                elapsed = max(0.0, (self._clock() - started) * 1000.0)
                with self._condition:
                    self._no_hand_frames = 0 if snapshot.hand_present else self._no_hand_frames + 1
                    self._power_mode = ("sleep" if self._no_hand_frames > 150 else
                                        "low" if self._no_hand_frames > 30 else "normal")
                    self._metrics = replace(
                        self._metrics, processed=self._metrics.processed + 1,
                        last_step_ms=elapsed, max_step_ms=max(self._metrics.max_step_ms, elapsed),
                        frame_age_ms=max(0.0, (self._clock() - observation.timestamp) * 1000.0),
                    )
                self._publish(snapshot, frame)
        except Exception:
            # Diagnostics are stable codes; exceptions can contain AX content.
            self._guard.suspend()
            try:
                self._publish(self._reset_snapshot("control_failed"), None)
            except Exception:
                pass
        finally:
            with self._condition:
                self._accepting = False
                self._pending = None
            self._guard.suspend()
            try:
                self._engine.reset()
            finally:
                self._guard.close()

    def stop(self, timeout=0.1):
        with self._condition:
            self._accepting = False
            self._stopping = True
            self._pending = None
            self._latest = None
            self._outcomes.clear()
            self._condition.notify_all()
        self._guard.suspend()
        if self._thread is None:
            self._guard.close()
            return True
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, timeout))
        return not self.is_running

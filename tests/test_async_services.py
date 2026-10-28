from dataclasses import FrozenInstanceError
import threading
import time

import pytest

from core.async_services import AsyncContextProvider, AsyncTelemetry
from platform_services.contracts import UIContext
from platform_services.policy import ContextPolicy


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class BlockingContext:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.threads = []
        self.context = UIContext("clickable", target_id="button", bounds=(0, 0, 20, 20))
        self.policy = ContextPolicy.from_config({"control_gestures": {"clickable": ["point"]}})
        self.fail = False

    def _lookup(self, kind, x, y, radius=None):
        self.calls.append((kind, x, y, radius))
        self.threads.append(threading.current_thread())
        self.entered.set()
        self.release.wait()
        if self.fail:
            raise RuntimeError("native lookup unavailable")
        return self.context

    def get_context(self, x=None, y=None):
        return self._lookup("context", x, y)

    def probe_targets(self, x, y, radius=120):
        return [self._lookup("probe", x, y, radius)]


def wait_completed(service, count=1):
    # Completion notifications make these concurrency tests independent of the
    # scheduler's precise timing and avoid arbitrary sleeps.
    with service._condition:
        assert service._condition.wait_for(lambda: service._completed >= count, timeout=2)


def test_context_producer_never_waits_for_native_lookup_and_queue_is_latest_only():
    native = BlockingContext()
    service = AsyncContextProvider(native)
    try:
        assert service.get_context(0, 0).category == "generic"
        assert native.entered.wait(1)
        returned = threading.Event()

        def produce():
            for index in range(1000):
                assert service.get_context(index, index).category == "generic"
                assert service.probe_targets(index, index, 120) == ()
            returned.set()

        producer = threading.Thread(target=produce)
        producer.start()
        assert returned.wait(1), "input producer stalled behind the native lookup"
        producer.join(1)
        assert service.pending_count == 2
        assert service.statistics["inflight"] == 1
        assert service.dropped_requests >= 1996
        assert native.calls == [("context", 0, 0, None)]
        native.release.set()
        wait_completed(service, 3)
        assert native.calls == [
            ("context", 0, 0, None),
            ("probe", 999, 999, 120),
            ("context", 999, 999, None),
        ]
        assert all(thread is not threading.main_thread() for thread in native.threads)
    finally:
        native.release.set()
        assert service.close(1)


def test_context_age_includes_native_lookup_duration():
    native, clock = BlockingContext(), Clock()
    service = AsyncContextProvider(native, clock=clock, max_age=0.12)
    try:
        service.get_context(10, 10)
        assert native.entered.wait(1)
        clock.now += 0.2
        native.release.set()
        wait_completed(service)
        assert service.get_context(10, 10).source == "async_unavailable"
    finally:
        native.release.set()
        service.close(1)


def test_context_respects_position_radius_policy_and_immutable_snapshot():
    native, clock = BlockingContext(), Clock()
    mutable_bounds = [0, 0, 20, 20]
    native.context = UIContext("clickable", target_id="button", bounds=mutable_bounds)
    native.release.set()
    service = AsyncContextProvider(native, clock=clock, max_distance=12)
    try:
        service.get_context(10, 10)
        wait_completed(service)
        native.release.clear()
        assert service.policy is native.policy
        context = service.get_context(10, 10)
        mutable_bounds[2] = 100
        assert context.bounds == (0, 0, 20, 20)
        with pytest.raises(FrozenInstanceError):
            context.category = "generic"
        assert service.get_context(22, 10).target_id == "button"
        assert service.get_context(23, 10).target_id == ""
        assert not service.is_gesture_allowed("pinch", 10, 10)
        assert service.is_gesture_allowed("point", 10, 10)
        assert not service.is_action_allowed("drag", 10, 10)
        assert service.is_action_allowed("left_click", 10, 10)
        assert not service.is_action_allowed("left_click", 23, 10)
        assert not service.is_action_allowed("left_click")
        service.probe_targets(10, 10, 50)
        native.release.set()
        wait_completed(service, 3)
        native.release.clear()
        targets = service.probe_targets(10, 10, 50)
        assert isinstance(targets, tuple)
        assert len(targets) == 1
        assert service.probe_targets(10, 10, 51) == ()
    finally:
        native.release.set()
        service.close(1)


def test_context_invalidation_cannot_be_undone_by_inflight_native_result():
    native = BlockingContext()
    service = AsyncContextProvider(native)
    try:
        service.get_context(0, 0)
        assert native.entered.wait(1)
        service.probe_targets(0, 0)
        service.invalidate()
        assert service.pending_count == 0
        native.release.set()
        wait_completed(service)
        assert service._snapshots == {}
        assert service.get_context(0, 0).target_id == ""
    finally:
        native.release.set()
        service.close(1)


def test_context_close_is_bounded_and_late_results_are_discarded():
    native = BlockingContext()
    service = AsyncContextProvider(native)
    try:
        service.get_context(0, 0)
        assert native.entered.wait(1)
        started = time.monotonic()
        assert not service.close(timeout=0.02)
        assert time.monotonic() - started < 0.5
        assert service._worker.daemon
        native.release.set()
        assert service.close(1)
        assert service._snapshots == {}
        assert service.get_context(0, 0).target_id == ""
        assert service.probe_targets(0, 0) == ()
        assert not service.is_action_allowed("left_click", 0, 0)
        assert service.pending_count == 0
    finally:
        native.release.set()
        service.close(1)


def test_context_native_failures_are_closed_and_worker_can_recover():
    native = BlockingContext()
    native.release.set()
    native.fail = True
    service = AsyncContextProvider(native)
    try:
        assert not service.is_action_allowed("left_click", 0, 0)
        wait_completed(service)
        assert service.errors == 1
        native.fail = False
        service.get_context(0, 0)
        wait_completed(service, 2)
        assert service.get_context(0, 0).target_id == "button"
    finally:
        native.release.set()
        service.close(1)


def test_context_provider_without_optional_probe_and_explicit_policy():
    class MinimalProvider:
        def get_context(self, x=None, y=None):
            return UIContext("generic")

    policy = ContextPolicy.default()
    service = AsyncContextProvider(MinimalProvider(), policy=policy)
    try:
        assert service.policy is policy
        assert service.probe_targets(0, 0) == ()
        wait_completed(service)
        assert service.probe_targets(0, 0) == ()
        assert service.errors == 0
    finally:
        service.close(1)


def test_disabled_context_policy_does_not_require_or_schedule_native_lookup():
    native = BlockingContext()
    native.policy = ContextPolicy.from_config({"enabled": False})
    service = AsyncContextProvider(native)
    try:
        assert service.policy is native.policy
        assert service.is_gesture_allowed("dynamic_shortcut")
        assert service.is_action_allowed("scroll_up", 0, 0)
        assert service.pending_count == 0
        assert native.calls == []
        # Turning off filtering cannot fabricate identity for a contextual
        # request: callers still receive the unavailable context snapshot.
        assert service.get_context(0, 0).target_id == ""
        assert native.entered.wait(1)
        assert service.is_action_allowed("left_click", 0, 0)
        assert not service.close(0.01)
        assert not service.is_gesture_allowed("dynamic_shortcut")
        assert not service.is_action_allowed("left_click", 0, 0)
    finally:
        native.release.set()
        service.close(1)


@pytest.mark.parametrize("context", [
    UIContext("generic", source="accessibility_unavailable"),
    UIContext("clickable", is_enabled=False),
])
def test_context_failure_fallback_and_disabled_target_cannot_authorize(context):
    native = BlockingContext()
    native.context = context
    native.release.set()
    service = AsyncContextProvider(native)
    try:
        service.get_context(0, 0)
        wait_completed(service)
        assert not service.is_gesture_allowed("point", 0, 0)
        assert not service.is_action_allowed("left_click", 0, 0)
    finally:
        service.close(1)


class BlockingStore:
    def __init__(self):
        self.enabled = True
        self.path = "/diagnostics/test.sqlite"
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.threads = []
        self.closed = False
        self.fail = False

    def _write(self, method, args, kwargs):
        self.entered.set()
        self.release.wait()
        self.threads.append(threading.current_thread())
        if self.fail:
            raise RuntimeError("disk unavailable")
        self.calls.append((method, args, kwargs))

    def record(self, *args, **kwargs):
        self._write("record", args, kwargs)

    def record_candidates(self, *args, **kwargs):
        self._write("record_candidates", args, kwargs)

    def record_transition(self, *args, **kwargs):
        self._write("record_transition", args, kwargs)

    def close(self):
        self.closed = True


def test_telemetry_producer_never_waits_for_store_and_queue_stays_bounded():
    store = BlockingStore()
    service = AsyncTelemetry(store, max_pending=4)
    try:
        service.record("first")
        assert store.entered.wait(1)
        returned = threading.Event()

        def produce():
            for index in range(1000):
                service.record("action", x=index)
            returned.set()

        producer = threading.Thread(target=produce)
        producer.start()
        assert returned.wait(1), "input producer stalled behind a telemetry write"
        producer.join(1)
        assert service.pending_count == 4
        assert service.statistics["inflight"] == 1
        assert service.dropped_records == 996
        assert not service.flush(0.01)
        store.release.set()
        assert service.flush(1)
        assert [call[2].get("x") for call in store.calls] == [None, 0, 1, 2, 3]
        assert len(set(store.threads)) == 1
        assert store.threads[0] is not threading.main_thread()
    finally:
        store.release.set()
        assert service.close(1)
        assert not store.closed


def test_telemetry_copies_only_bounded_diagnostic_payloads_and_captures_enqueue_time():
    store = BlockingStore()
    service = AsyncTelemetry(store)
    try:
        service.record("barrier")
        assert store.entered.wait(1)
        features = [1.0, 2.0]
        rows = [{"role": "button", "features": features, "x": 42, "frame": object()}]
        service.record_candidates("lock", rows, timestamp=123.0)
        service.record_transition(features=features, label=1, outcome="click")
        service.record("action", x=10, frame=object(), landmarks=object())
        submitted_before = time.time()
        features[0] = 99.0
        rows[0]["x"] = 99
        store.release.set()
        assert service.flush(1)
        candidates = store.calls[1]
        assert candidates[1][1][0] == {"role": "button", "features": (1.0, 2.0), "x": 42}
        assert candidates[2]["timestamp"] == 123.0
        transition = store.calls[2][2]
        assert transition["features"] == (1.0, 2.0)
        assert transition["timestamp"] <= submitted_before
        assert set(store.calls[3][2]) == {"x", "timestamp"}
    finally:
        store.release.set()
        service.close(1)


def test_telemetry_bounds_each_candidate_batch_and_feature_vector():
    store = BlockingStore()
    store.release.set()
    service = AsyncTelemetry(store)
    try:
        service.record_candidates("lock", [
            {"features": list(range(100)), "frame": object()} for _ in range(100)
        ])
        assert service.flush(1)
        rows = store.calls[0][1][1]
        assert len(rows) == 64
        assert all(len(row["features"]) == 64 for row in rows)
        assert all("frame" not in row for row in rows)
    finally:
        service.close(1)


def test_telemetry_close_is_bounded_and_does_not_own_store():
    store = BlockingStore()
    service = AsyncTelemetry(store)
    try:
        service.record("first")
        assert store.entered.wait(1)
        service.record("second")
        started = time.monotonic()
        assert not service.close(0.02)
        assert time.monotonic() - started < 0.5
        assert not store.closed
        assert service._worker.daemon
        service.record("after_close")
        assert service.pending_count == 1
        store.release.set()
        assert service.close(1)
        assert [call[1][0] for call in store.calls] == ["first", "second"]
        assert not store.closed
    finally:
        store.release.set()
        service.close(1)


def test_telemetry_proxies_opt_in_and_recovers_from_write_failure():
    store = BlockingStore()
    store.enabled = False
    store.release.set()
    service = AsyncTelemetry(store)
    try:
        assert not service.enabled
        assert service.path == store.path
        service.record("disabled")
        assert service.statistics["accepted"] == 0
        store.enabled = True
        assert service.enabled
        store.fail = True
        service.record("failed")
        assert service.flush(1)
        assert service.errors == 1
        store.fail = False
        service.record("recovered")
        assert service.flush(1)
        assert [call[1][0] for call in store.calls] == ["recovered"]
    finally:
        store.release.set()
        service.close(1)


def test_telemetry_writes_existing_store_without_closing_it(tmp_path):
    from core.telemetry import TelemetryStore
    from core.transition_features import FEATURE_COUNT

    store = TelemetryStore(str(tmp_path / "diagnostics.sqlite"), enabled=True)
    service = AsyncTelemetry(store)
    try:
        service.record("action", action="left_click", executed=True)
        service.record_candidates("lock", [{"features": [0.0] * 8, "chosen_raw": True}])
        service.record_transition(features=[0.0] * FEATURE_COUNT, label=1)
        assert service.close(2)
        assert service.errors == 0
        assert store.enabled
        assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1
        assert store._connection.execute("SELECT count(*) FROM candidates").fetchone()[0] == 1
        assert store._connection.execute("SELECT count(*) FROM transitions").fetchone()[0] == 1
    finally:
        service.close(1)
        store.close()

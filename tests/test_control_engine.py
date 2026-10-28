"""Headless replays reach actual coordinator/native-adapter boundaries.

These tests require neither QApplication nor camera access. Only the external
clock, accessibility provider and OS event sink are simulated.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import subprocess
import sys
import threading

import pytest

from core.action_coordinator import GestureActionCoordinator
from core.action_state_machine import ActionState
from core.control_engine import ControlEngine, HandObservation
from core.control_session import SessionState
from core.pointer_mapping import ScreenBounds
from platform_services.contracts import (
    ActionResult, AuthorizationState, PermissionSnapshot, PlatformCapabilities,
    PlatformServices, UIContext,
)
from platform_services.macos.input_controller import MacOSInputController
from platform_services.policy import ContextPolicy
from utils.config_manager import DEFAULT_CONFIG


class Clock:
    now = 10.0

    def __call__(self):
        return self.now


def test_pointer_filter_history_preserves_bound_clock_service(replay):
    class LockedClock:
        def __init__(self):
            self.lock = threading.Lock()

        def now(self):
            with self.lock:
                return replay.clock.now

    service = LockedClock()
    clock = service.now
    replay.engine = ControlEngine(
        replay.config, replay.engine.screen_bounds, replay.coordinator,
        cursor_position=lambda: (300, 200), clock=clock,
    )
    replay.hold("point", 0.6)
    replay.hold("pinch", 0.2)
    replay.hold("point", 0.4)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1
    assert replay.engine.tracker._clock is clock
    assert replay.engine.smoother._clock is clock
    assert replay.engine.smoother.filter_x._clock is clock
    assert replay.engine.smoother.filter_y._clock is clock


class Native:
    def __init__(self):
        self.mouse, self.scrolls, self.hotkeys = [], [], []
        self.fail_click = False

    def post_mouse(self, kind, x, y, button, click_count=1):
        if self.fail_click and kind == "left_down":
            raise RuntimeError("synthetic input failure")
        self.mouse.append((kind, x, y, button, click_count))

    def post_scroll(self, vertical, horizontal):
        self.scrolls.append((vertical, horizontal))

    def post_hotkey(self, hotkey):
        self.hotkeys.append(hotkey)


class Context:
    def __init__(self):
        self.target_id = "document-a"
        self.policy = ContextPolicy.default()
        self.queries = []

    def get_context(self, x=None, y=None):
        inside = x is not None and y is not None and 0 <= x < 1920 and 0 <= y < 450
        self.queries.append((x, y))
        return UIContext("scrollable" if inside else "generic", "AXScrollArea",
                         "fake", self.target_id if inside else "")

    def is_gesture_allowed(self, gesture, x=None, y=None):
        return self.policy.is_gesture_allowed(self.get_context(x, y), gesture)

    def is_action_allowed(self, action, x=None, y=None):
        return self.policy.is_action_allowed(self.get_context(x, y), action)


class Telemetry:
    enabled = True

    def __init__(self):
        self.actions, self.transitions = [], []

    def record(self, event, **fields):
        self.actions.append((event, fields))

    def record_transition(self, **fields):
        self.transitions.append(fields)

    def record_candidates(self, *args):
        pass


def pose(name, dx=0.0):
    if name is None:
        return None
    points = [(320.0, 240.0, 0.0)] * 21
    values = {
        0: (320, 340), 9: (320, 240), 5: (250, 220), 6: (248, 180),
        7: (247, 150), 8: (246, 120),
        4: (250, 124) if name == "pinch" else (300, 300),
        10: (320, 210), 11: (322, 250), 12: (324, 275),
        13: (385, 225), 14: (387, 260), 15: (389, 282), 16: (391, 298),
        17: (435, 240), 18: (437, 270), 19: (439, 288), 20: (441, 302),
    }
    if name == "open_hand":
        values.update({12: (320, 90), 16: (391, 110), 20: (441, 145)})
    if name == "thumb_down":
        values.update({8: (270, 285), 2: (235, 280), 4: (235, 400)})
    for index, (x, y) in values.items():
        points[index] = (float(x), float(y), 0.0)
    return [(x + dx, y, z) for x, y, z in points]


class Replay:
    def __init__(self, config, clock, native, context, telemetry, coordinator, engine):
        self.config, self.clock, self.native, self.context = config, clock, native, context
        self.telemetry, self.coordinator, self.engine = telemetry, coordinator, engine
        self.fps = 30
        self.snapshots = []

    def send(self, name, dx=0.0, age=0.0):
        self.clock.now += 1.0 / self.fps
        at = self.clock.now
        self.clock.now += age
        snapshot = self.engine.step(HandObservation(at, pose(name, dx), (640, 480)))
        self.snapshots.append(snapshot)
        return snapshot

    def hold(self, name, seconds, dx=0.0, travel=0.0):
        count = max(1, round(seconds * self.fps))
        for index in range(count):
            self.send(name, dx + travel * index / max(1, count - 1))

    def events(self, kind):
        return [event for event in self.native.mouse if event[0] == kind]

    def start_drag(self):
        self.hold("point", 0.6)
        self.hold("pinch", 0.9, travel=100)
        assert len(self.events("left_down")) == 1
        assert len(self.events("left_dragged")) >= 5
        assert not self.events("left_up")


@pytest.fixture
def replay(tmp_path):
    config = deepcopy(DEFAULT_CONFIG)
    config["control_session"]["mode"] = "always"
    config["pointer_assist"]["enabled"] = False
    config["_config_path"] = str(tmp_path / "settings.json")
    clock, native, context, telemetry = Clock(), Native(), Context(), Telemetry()
    controller = MacOSInputController(native, clock=clock)
    permissions = PermissionSnapshot(AuthorizationState.GRANTED, AuthorizationState.GRANTED)
    services = PlatformServices(
        capabilities=PlatformCapabilities("macos", "fake", controller.supported_actions,
                                          permissions=permissions),
        input_controller=controller, context_provider=context,
        permission_provider=SimpleNamespace(snapshot=lambda: permissions),
    )
    coordinator = GestureActionCoordinator(services)
    coordinator.input_guard._clock = clock
    coordinator.input_guard.start(threaded=False)
    engine = ControlEngine(config, ScreenBounds(0, 0, 1920, 1080), coordinator,
                           cursor_position=lambda: (300, 200), clock=clock, telemetry=telemetry)
    yield Replay(config, clock, native, context, telemetry, coordinator, engine)
    coordinator.close()


def test_engine_import_does_not_load_qt_or_gui():
    result = subprocess.run([sys.executable, "-c", (
        "import sys; import core.control_engine; "
        "assert not any(n.startswith(('PySide6', 'gui.')) for n in sys.modules)"
    )], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_observation_and_config_are_detached_from_producer_mutations(replay):
    points = pose("point")
    observation = HandObservation(replay.clock(), points, (640, 480))
    points[8] = (0, 0, 0)
    assert observation.landmarks[8] != points[8]
    with pytest.raises(FrozenInstanceError):
        observation.timestamp = 12
    replay.config["control_session"]["mode"] = "gesture"
    replay.hold("point", 0.5)
    assert replay.snapshots[-1].session_state is SessionState.POINTER


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_short_pinch_has_one_complete_click_and_truthful_snapshot(replay, fps):
    replay.fps = fps
    replay.hold("point", 0.6)
    replay.hold("pinch", 0.2)
    replay.hold("point", 0.4)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1
    assert not replay.events("left_dragged")
    clicks = [outcome for snap in replay.snapshots for outcome in snap.outcomes
              if outcome.request.action == "left_click"]
    assert len(clicks) == 1 and clicks[0].result.executed
    assert replay.telemetry.transitions[-1]["outcome"] == "acted"
    assert replay.telemetry.transitions[-1]["label"] == 1


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("release_pose", ["point", "open_hand"])
def test_drag_keeps_real_motion_and_releases_without_click(replay, fps, release_pose):
    replay.fps = fps
    replay.start_drag()
    moves = replay.events("left_dragged")
    assert moves[-1][1] > moves[0][1] + 50
    replay.hold(release_pose, 0.4, dx=100)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1
    assert replay.engine.action_machine.state is ActionState.MOVING
    assert not replay.native.hotkeys


def test_scroll_latches_aim_and_target_change_revokes_dwell(replay):
    config = deepcopy(replay.config)
    config["pointer_scroll"] = {"enabled": False}
    replay.engine = ControlEngine(
        config, replay.engine.screen_bounds, replay.coordinator,
        cursor_position=lambda: (300, 200), clock=replay.clock,
    )
    replay.hold("point", 0.7)
    anchor = replay.events("move")[-1][1:3]
    replay.context.queries.clear()
    replay.hold("thumb_down", 1.0)
    assert 3 <= len(replay.native.scrolls) <= 10
    assert all(query == pytest.approx(anchor, abs=1) for query in replay.context.queries)
    count = len(replay.native.scrolls)
    replay.context.target_id = "document-b"
    replay.hold("thumb_down", 0.6)
    assert len(replay.native.scrolls) == count
    replay.hold("point", 0.7)
    replay.hold("thumb_down", 0.7)
    assert len(replay.native.scrolls) >= count + 2


@pytest.mark.parametrize("failure", ["lost", "stale", "malformed", "reordered"])
def test_invalid_observation_releases_drag_before_any_more_motion(replay, failure):
    replay.start_drag()
    count = len(replay.native.mouse)
    if failure == "lost":
        snapshot = replay.send(None)
    elif failure == "stale":
        snapshot = replay.send("pinch", dx=150, age=0.4)
    else:
        replay.clock.now += 0.03
        at = replay.clock.now if failure == "malformed" else replay.engine._last_frame_time
        landmarks = [(0, 0, 0)] if failure == "malformed" else pose("pinch", 150)
        snapshot = replay.engine.step(HandObservation(at, landmarks, (640, 480)))
    assert [event[0] for event in replay.native.mouse[count:]] == ["left_up"]
    assert snapshot.pointer_state is ActionState.MOVING
    assert not snapshot.hand_present
    assert any(o.request.action == "drag_end" and o.result.executed for o in snapshot.outcomes)


def test_watchdog_silence_release_then_reacquisition_never_resumes_old_drag(replay):
    replay.start_drag()
    replay.clock.now += 0.4
    assert replay.coordinator.input_guard.check_timeout().executed
    replay.hold("point", 0.5, dx=100)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1
    assert replay.engine.action_machine.state is ActionState.MOVING


def test_failed_native_click_is_not_a_positive_training_label(replay):
    replay.native.fail_click = True
    replay.hold("point", 0.6)
    replay.hold("pinch", 0.2)
    replay.hold("point", 1.2)
    outcomes = [o for s in replay.snapshots for o in s.outcomes if o.request.action == "left_click"]
    assert len(outcomes) == 1 and not outcomes[0].result.executed
    assert not any(row["outcome"] == "acted" for row in replay.telemetry.transitions)
    assert not any(row["label"] == 1 for row in replay.telemetry.transitions)


def test_relative_reacquisition_anchors_to_actual_cursor(replay):
    from core.pointer_mapping import RelativeMapper
    replay.engine.pointer_mapper = RelativeMapper(gain=1.4)
    current = [300, 200]
    replay.engine.cursor_position = lambda: tuple(current)
    replay.hold("point", 0.4)
    assert replay.events("move")[-1][1:3] == (300, 200)
    replay.send(None)
    current[:] = [800, 500]
    replay.hold("point", 0.4, dx=120)
    assert replay.events("move")[-1][1:3] == (800, 500)


def test_persisted_optional_settings_are_restored(replay):
    from core.static_gesture_template import StaticGestureMatcher
    config = deepcopy(replay.config)
    config["gesture_combos"] = [{"gesture1": "peace", "gesture2": "rock", "action": "custom_hotkey", "hotkey": "cmd+c"}]
    config["action_mode"]["move_threshold"] = 19
    config["pointer_mapping"] = {"mode": "relative", "gain": 1.7}
    config["pinch_calibration"] = {"enter_ratio": 0.27, "exit_ratio": 0.41}
    config["control_session"]["custom_static_templates"] = [{
        "template_id": "mine", "name": "mine", "feature_vector": [0.0] * 63, "threshold": 0.2,
    }]
    config["control_session"]["activation_template_id"] = "mine"
    engine = ControlEngine(config, replay.engine.screen_bounds, replay.coordinator,
                           cursor_position=lambda: (0, 0), clock=replay.clock)
    assert engine.combo_detector.combos == config["gesture_combos"]
    assert engine.action_machine.move_threshold == 19
    assert engine.pointer_mapper.gain == 1.7
    assert engine.classifier.pinch_enter_ratio == 0.27
    assert engine.control_session.activation_template.template_id == "mine"
    assert isinstance(engine.static_gesture_matcher, StaticGestureMatcher)


def test_dynamic_completed_takes_rearm_without_losing_cooldown(replay):
    from core.dynamic_gesture_template import DynamicGestureMatcher
    frames = [pose("open_hand", dx=index * 50) for index in range(8)]
    sample = DynamicGestureMatcher().prepare_recording(frames)
    assert sample is not None
    config = deepcopy(replay.config)
    config["dynamic_gestures"]["enabled"] = True
    config["dynamic_gestures"]["templates"] = [{
        "template_id": "swipe", "name": "Swipe", "action": "custom_hotkey",
        "samples": [sample], "threshold": 0.18, "cooldown_seconds": 1.5,
        "min_motion_energy": 0.01, "hotkey": "cmd+c",
    }]
    engine = ControlEngine(config, replay.engine.screen_bounds, replay.coordinator,
                           cursor_position=lambda: (0, 0), clock=replay.clock)
    engine.control_session.state = SessionState.POINTER

    def observe(gesture, landmarks):
        replay.clock.now += 1 / 30
        replay.coordinator.input_guard.observe_frame(replay.clock())
        return engine.observe_completed_dynamic_shortcut(
            landmarks, (500, 250), gesture=gesture, allowed=True,
            hand_present=True, now=replay.clock(),
        )

    def take():
        for _ in range(3):
            observe("none", frames[0])
        for frame in frames:
            observe("open_hand", frame)
        observe("none", frames[-1])
        return observe("none", frames[-1])[1]

    assert take()
    assert not take(), "A new neutral boundary must not bypass cooldown"
    replay.clock.now += 1.5
    replay.coordinator.input_guard.observe_frame(replay.clock())
    assert take(), "Neutral between completed takes must rearm the matcher"
    assert replay.native.hotkeys == ["cmd+c", "cmd+c"]


def test_assist_is_warmed_while_pointing_and_never_loads_models_in_step(replay, monkeypatch):
    from core.assist.ranker import LinearRanker
    from core.transition_model import TransitionModel
    config = deepcopy(replay.config)
    config["pointer_assist"]["enabled"] = True
    calls = []
    replay.context.probe_targets = lambda x, y, radius: calls.append((x, y, radius)) or ()
    engine = ControlEngine(config, replay.engine.screen_bounds, replay.coordinator,
                           cursor_position=lambda: (0, 0), clock=replay.clock)

    def unexpected_load(*args, **kwargs):
        raise AssertionError("model file I/O leaked into the per-frame control transaction")

    monkeypatch.setattr(TransitionModel, "load", unexpected_load)
    monkeypatch.setattr(LinearRanker, "load", unexpected_load)
    replay.engine = engine
    replay.hold("point", 0.5)
    assert calls
    assert replay.events("move")


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_core_scroll_works_without_accessibility_and_stops_on_raw_release(replay, fps):
    replay.fps = fps

    def no_accessibility(*args, **kwargs):
        raise AssertionError("Wheel control must not depend on an accessibility target")

    replay.context.get_context = no_accessibility
    replay.context.is_gesture_allowed = no_accessibility
    replay.context.is_action_allowed = no_accessibility
    replay.hold("point", 0.7)
    aim = replay.events("move")[-1][1:3]
    replay.hold("thumb_down", 1.0)
    assert 3 <= len(replay.native.scrolls) <= 10
    scrolls = [outcome for snap in replay.snapshots for outcome in snap.outcomes
               if outcome.request.action == "scroll_down"]
    assert all(outcome.result.executed and outcome.request.core_pointer for outcome in scrolls)
    assert all((outcome.request.x, outcome.request.y) == pytest.approx(aim, abs=1)
               for outcome in scrolls)
    count = len(replay.native.scrolls)
    replay.send("point")
    assert len(replay.native.scrolls) == count
    replay.hold("point", 0.4)
    assert len(replay.native.scrolls) == count


def test_core_scroll_requires_point_dwell_and_loses_it_on_hand_loss(replay):
    replay.hold("thumb_down", 0.8)
    assert not replay.native.scrolls
    replay.hold("point", 0.7)
    replay.hold("thumb_down", 0.7)
    assert replay.native.scrolls
    count = len(replay.native.scrolls)
    replay.send(None)
    replay.hold("thumb_down", 0.8)
    assert len(replay.native.scrolls) == count


@pytest.mark.parametrize("lane", ["combo", "dynamic"])
def test_optional_one_shot_warms_cold_context_before_commit(replay, lane):
    from dataclasses import replace
    from core.dynamic_gesture_template import DynamicGestureMatcher

    class ColdContext:
        """The first request schedules work; later reads expose cached policy."""
        queries = 0
        authorizations = 0

        def get_context(self, *args):
            self.queries += 1
            if self.queries < 2:
                return UIContext("generic", source="async_unavailable", is_enabled=False)
            return UIContext("generic", source="cached", target_id="same-target")

        def is_gesture_allowed(self, *args):
            self.authorizations += 1
            return self.queries >= 2

        def is_action_allowed(self, *args):
            return self.queries >= 2

    context = ColdContext()
    replay.coordinator.services = replace(replay.coordinator.services, context_provider=context)
    config = deepcopy(replay.config)
    frames = [pose("open_hand", dx=index * 50) for index in range(8)]
    if lane == "combo":
        config["gesture_combos"] = [{
            "gesture1": "open_hand", "gesture2": "peace",
            "action": "custom_hotkey", "hotkey": "cmd+c",
        }]
    else:
        sample = DynamicGestureMatcher().prepare_recording(frames)
        config["dynamic_gestures"]["enabled"] = True
        config["dynamic_gestures"]["templates"] = [{
            "template_id": "swipe", "name": "Swipe", "action": "custom_hotkey",
            "samples": [sample], "threshold": 0.18, "cooldown_seconds": 0.75,
            "min_motion_energy": 0.01, "hotkey": "cmd+c",
        }]
    engine = ControlEngine(config, replay.engine.screen_bounds, replay.coordinator,
                           cursor_position=lambda: (300, 200), clock=replay.clock)
    label = ["none"]
    engine.classifier.classify = lambda *args, **kwargs: label[0]
    engine.classifier.get_pinch_info = lambda *args, **kwargs: {
        "is_pinching": False, "is_approaching": False,
    }

    def send(gesture, landmarks):
        replay.clock.now += 1 / 30
        label[0] = gesture
        engine.classifier.last_raw_gesture = gesture
        return engine.step(HandObservation(replay.clock(), landmarks, (640, 480)))

    for _ in range(4):
        send("none", frames[0])
    for frame in frames:
        send("open_hand", frame if lane == "dynamic" else frames[0])
    assert context.queries >= 2
    assert not context.authorizations, "Warming itself must never dispatch input"
    if lane == "combo":
        final = send("peace", frames[0])
    else:
        send("none", frames[-1])
        final = send("none", frames[-1])
    assert replay.native.hotkeys == ["cmd+c"]
    assert any(o.request.action == "custom_hotkey" and o.result.executed for o in final.outcomes)


@pytest.mark.parametrize("boundary", ["neutral", "hand_loss"])
def test_optional_click_rearms_after_neutral_or_tracking_loss(replay, boundary):
    label = ["peace"]

    def classify(landmarks, **kwargs):
        gesture = label[0] if landmarks else "none"
        replay.engine.classifier.last_raw_gesture = gesture
        return gesture

    replay.engine.classifier.classify = classify
    replay.engine.classifier.get_pinch_info = lambda *args, **kwargs: {
        "is_pinching": False, "is_approaching": False,
    }
    replay.hold("point", 0.6)
    assert len(replay.events("right_down")) == 1
    if boundary == "hand_loss":
        replay.send(None)
    else:
        label[0] = "none"
        replay.hold("point", 0.15)
    label[0] = "peace"
    replay.hold("point", 0.6)
    assert len(replay.events("right_down")) == len(replay.events("right_up")) == 2


def test_snapshot_carries_preview_lock_geometry_without_exposing_mapper(replay):
    replay.hold("point", 0.6)
    replay.hold("pinch", 0.2)
    locked = [snapshot for snapshot in replay.snapshots if snapshot.locked_position is not None]
    assert locked
    snapshot = locked[-1]
    assert snapshot.preview_locked_position == replay.engine.pointer_mapper.unmap(
        snapshot.locked_position, (640, 480), replay.engine.screen_bounds,
    )
    assert snapshot.preview_locked_position != snapshot.locked_position
    replay.send(None)
    assert replay.snapshots[-1].preview_locked_position is None

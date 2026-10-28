"""Joint click/aim inference, replayed to a recording macOS native sink.

Ground truth is independent of the inferred lock: an identically primed control
replay follows the same palm trajectory with the index in its pre-pinch pose.
Its native cursor position on the first closure-evidence frame is the target.
Candidate movement has a second oracle: the identical curling fingertip replay
with pinch admission disabled, preserving the real pointer filters and sink.
Only time, display geometry, accessibility and the OS event sink are simulated.
"""
from copy import deepcopy
from math import hypot, sqrt
from types import SimpleNamespace

import pytest

from core.action_coordinator import GestureActionCoordinator
from core.action_state_machine import ActionState
from core.control_engine import ControlEngine, HandObservation
from core.pinch_intent import PinchEvidence
from core.pointer_mapping import ScreenBounds
from platform_services.contracts import (
    AuthorizationState, PermissionSnapshot, PlatformCapabilities, PlatformServices,
)
from platform_services.macos.input_controller import MacOSInputController
from tests.test_control_engine import Clock, Context, Native, pose
from utils.config_manager import DEFAULT_CONFIG


def hand(closure=0.0, *, dx=0.0, dy=0.0, curl=30.0, fist=0.0):
    """Translate the complete scaffold; bend only the index and closing thumb.

    The open index/ thumb gap is 93 camera pixels (> the point gate), and the
    closed gap is 7px. Index bending displaces its tip by ``curl`` camera pixels;
    wrist and all four MCPs retain their relative geometry throughout.
    """
    points = pose("point")
    bend = curl / sqrt(2)
    points[4] = (330 + (252 + bend - 330) * closure,
                 160 + (124 + bend - 160) * closure, 0.0)
    points[8] = (246 + bend * closure, 120 + bend * closure, 0.0)
    for index in (12, 16, 20):
        x, y, _ = points[index]
        points[index] = (x + (320 - x) * fist, y + (325 - y) * fist, 0.0)
    return [(x + dx, y + dy, z) for x, y, z in points]


class Pipeline:
    def __init__(self, tmp_path, fps, *, mode="absolute", origin=(0, 0)):
        self.fps = fps
        self.clock = Clock()
        self.native = Native()
        controller = MacOSInputController(self.native, clock=self.clock)
        permissions = PermissionSnapshot(AuthorizationState.GRANTED, AuthorizationState.GRANTED)
        services = PlatformServices(
            capabilities=PlatformCapabilities("macos", "fake", controller.supported_actions,
                                              permissions=permissions),
            input_controller=controller, context_provider=Context(),
            permission_provider=SimpleNamespace(snapshot=lambda: permissions),
        )
        self.coordinator = GestureActionCoordinator(services)
        self.coordinator.input_guard._clock = self.clock
        self.coordinator.input_guard.start(threaded=False)
        config = deepcopy(DEFAULT_CONFIG)
        config["control_session"]["mode"] = "always"
        config["pointer_assist"]["enabled"] = False
        config["pointer_mapping"] = {"mode": mode, "gain": 1.4}
        config["_config_path"] = str(tmp_path / "joint-pinch-settings.json")
        self.engine = ControlEngine(
            config, ScreenBounds(*origin, 1920, 1080), self.coordinator,
            cursor_position=lambda: (800 + origin[0], 400 + origin[1]), clock=self.clock,
        )
        self.snapshots = []

    def send(self, closure=0.0, *, missing=False, age=0.0, gap=0.0,
             frame_size=(640, 480), coordinate_scale=1.0, **geometry):
        self.clock.now += 1 / self.fps + gap
        at = self.clock.now
        self.clock.now += age
        landmarks = None if missing else [
            (x * coordinate_scale, y * coordinate_scale, z * coordinate_scale)
            for x, y, z in hand(closure, **geometry)
        ]
        snapshot = self.engine.step(HandObservation(at, landmarks, frame_size))
        self.snapshots.append(snapshot)
        return snapshot

    def hold(self, seconds, closure=0.0, **geometry):
        for _ in range(max(1, round(seconds * self.fps))):
            self.send(closure, **geometry)

    def events(self, kind):
        return [event for event in self.native.mouse if event[0] == kind]

    def prime(self, *, speed=36.0, offset=0.0):
        for index in range(round(0.6 * self.fps)):
            self.send(dx=offset + speed * (index - round(0.6 * self.fps)) / self.fps)


@pytest.fixture
def pipeline_factory(tmp_path):
    pipelines = []

    def create(fps=30, **kwargs):
        pipeline = Pipeline(tmp_path, fps, **kwargs)
        pipelines.append(pipeline)
        return pipeline

    yield create
    for pipeline in pipelines:
        pipeline.coordinator.close()


def closure_frames(fps, style):
    if style == "sudden":
        return [1.0] * max(2, round(0.2 * fps))
    count = max(2, round(0.15 * fps))
    return [0.25 + 0.75 * index / (count - 1) for index in range(count)] + [1.0] * max(2, round(0.1 * fps))


def pointer_only_baseline(pipeline_factory, fps, mode):
    """Follow the actual fingertip with only pinch admission disabled.

    Owning the pointer lane keeps delayed classifier labels from taking over.
    Tracking, relative/absolute mapping, smoothing and native dispatch remain
    real, so this replay also detects contaminated visible filter history.
    """
    replay = pipeline_factory(fps, mode=mode)
    replay.engine.pinch_intent.update = lambda *args, **kwargs: PinchEvidence(
        phase="idle", owns_pointer=True,
    )
    return replay


def assert_native_pointer_frame(actual, baseline, closure, *, closed_cancellation=False, **geometry):
    before = len(actual.events("move"))
    baseline_before = len(baseline.events("move"))
    snapshot = actual.send(closure, **geometry)
    baseline.send(closure, **geometry)
    assert len(baseline.events("move")) == baseline_before + 1
    if closed_cancellation and snapshot.pinch_phase == "cancelled":
        assert len(actual.events("move")) == before
    else:
        assert len(actual.events("move")) == before + 1
        assert actual.events("move")[-1][1:3] == baseline.events("move")[-1][1:3]
    assert snapshot.locked_position is None
    assert snapshot.preview_locked_position is None
    assert actual.engine.action_machine.state in {ActionState.MOVING, ActionState.LOCKING}
    assert not actual.events("left_down")
    assert not actual.events("left_up")
    return snapshot


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_candidate_tracks_raw_pointer_until_confirmation_then_clicks_onset(pipeline_factory, fps, mode):
    actual = pipeline_factory(fps, mode=mode)
    baseline = pointer_only_baseline(pipeline_factory, fps, mode)
    onset = pipeline_factory(fps, mode=mode)
    for replay in (actual, baseline, onset):
        replay.prime(speed=72)
    onset.send()
    expected = onset.events("move")[-1][1:3]

    target = None
    candidate_count = max(2, round(0.15 * fps))
    for index in range(candidate_count):
        snapshot = assert_native_pointer_frame(
            actual, baseline, 0.4 if index == 0 else 0.45, dx=72 * index / fps,
        )
        assert snapshot.pinch_phase == "candidate"
        if target is None:
            target = actual.engine._joint_target
            assert target is not None
        assert actual.engine._joint_target == target
    candidate_end = actual.events("move")[-1][1:3]
    assert hypot(candidate_end[0] - expected[0], candidate_end[1] - expected[1]) > 10

    # Physical closure qualifies only after the still-moving candidate lead-in.
    # It must lock the hidden onset, not the latest visible fingertip position.
    dx = 72 * candidate_count / fps
    actual.hold(0.15, 1.0, dx=dx)
    confirmed = [item for item in actual.snapshots if item.pinch_phase == "confirmed"]
    assert confirmed
    assert all(item.locked_position is not None for item in confirmed)
    assert actual.engine._joint_target == target
    assert not actual.events("left_down")
    actual.hold(0.35, dx=dx)
    assert len(actual.events("left_down")) == len(actual.events("left_up")) == 1
    click = actual.events("left_down")[0][1:3]
    assert hypot(click[0] - expected[0], click[1] - expected[1]) <= 4, (expected, click)
    assert hypot(click[0] - candidate_end[0], click[1] - candidate_end[1]) > 10
    assert not actual.events("left_dragged")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_false_candidate_timeout_and_opening_preserve_visible_pointer_history(pipeline_factory, fps, mode):
    actual = pipeline_factory(fps, mode=mode)
    baseline = pointer_only_baseline(pipeline_factory, fps, mode)
    for replay in (actual, baseline):
        replay.prime(speed=72)

    phases = set()
    count = round(0.4 * fps)
    for index in range(count):
        snapshot = assert_native_pointer_frame(
            actual, baseline, 0.4 if index == 0 else 0.45,
            closed_cancellation=True, dx=72 * index / fps,
        )
        phases.add(snapshot.pinch_phase)
    assert {"candidate", "cancelled"} <= phases
    assert actual.snapshots[-1].pinch_reason == "candidate_timeout"

    for index in range(round(0.35 * fps)):
        assert_native_pointer_frame(actual, baseline, 0.0, dx=72 * (count + index) / fps)
    assert actual.snapshots[-1].pinch_phase == "idle"
    assert not actual.events("left_dragged")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_gradual_unconfirmed_closure_and_opening_never_interrupt_raw_pointer(pipeline_factory, fps, mode):
    actual = pipeline_factory(fps, mode=mode)
    baseline = pointer_only_baseline(pipeline_factory, fps, mode)
    for replay in (actual, baseline):
        replay.prime(speed=72)

    # Small curls change the visible filters before admission. Starting the
    # hidden replay later must leave every one of those raw samples intact.
    lead_in = [0.025, 0.05, 0.10]
    for index, closure in enumerate(lead_in):
        snapshot = assert_native_pointer_frame(actual, baseline, closure, dx=72 * index / fps)
        assert snapshot.pinch_phase == "idle"
    snapshot = assert_native_pointer_frame(actual, baseline, 0.4, dx=72 * len(lead_in) / fps)
    assert snapshot.pinch_phase == "candidate"
    evidence = actual.engine._joint_evidence
    assert evidence.new_episode
    assert len(evidence.corrections) >= 3
    assert evidence.reference_at < evidence.corrections[-2][0]

    # The hand opens before physical closure. Keep checking every native frame
    # through the unconfirmed-release cancellation and subsequent idle rearm.
    phases = [snapshot.pinch_phase]
    cancelled = []
    for index in range(round(0.35 * fps)):
        snapshot = assert_native_pointer_frame(
            actual, baseline, 0.0, dx=72 * (len(lead_in) + 1 + index) / fps,
        )
        phases.append(snapshot.pinch_phase)
        if snapshot.pinch_phase == "cancelled":
            cancelled.append(snapshot)
    assert cancelled
    assert all(item.pinch_reason == "unconfirmed_release" for item in cancelled)
    assert phases.index("candidate") < phases.index("cancelled") < phases.index("idle")
    assert phases[-1] == "idle"
    assert not actual.events("left_dragged")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_cancelled_episode_can_move_on_first_open_without_rearming_click(pipeline_factory, fps, mode):
    replay = pipeline_factory(fps, mode=mode)
    replay.prime(speed=0)
    replay.hold(0.4, 0.45)
    assert replay.snapshots[-1].pinch_phase == "cancelled"
    before = len(replay.events("move"))
    snapshot = replay.send(dx=2)
    assert snapshot.pinch_phase == "cancelled"
    assert snapshot.locked_position is None
    assert len(replay.events("move")) == before + 1
    # One genuine open frame permits safe movement, but a quick reclosure has
    # not supplied the separate open qualification needed for another click.
    replay.hold(0.2, 1.0, dx=2)
    replay.hold(0.3, dx=2)
    assert not replay.events("left_down")
    assert not replay.events("left_up")
    replay.hold(0.2, 1.0, dx=2)
    replay.hold(0.3, dx=2)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["absolute", "relative"])
@pytest.mark.parametrize("boundary", ["gap", "stale", "lost", "jump"])
def test_discontinuous_opening_cannot_use_cancelled_movement_permission(pipeline_factory, fps, mode, boundary):
    replay = pipeline_factory(fps, mode=mode)
    replay.prime(speed=0)
    replay.hold(0.4, 0.45)
    assert replay.snapshots[-1].pinch_phase == "cancelled"
    arguments = {"gap": {"gap": 0.4}, "stale": {"age": 0.4},
                 "lost": {"missing": True}, "jump": {"dx": 190}}
    before = len(replay.native.mouse)
    snapshot = replay.send(**arguments[boundary])
    assert snapshot.locked_position is None
    assert replay.native.mouse[before:] == []
    assert not replay.events("left_down")
    assert not replay.events("left_up")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("style", ["sudden", "gradual"])
@pytest.mark.parametrize("mode,offset", [
    ("absolute", 0.0), ("absolute", -235.0), ("absolute", 380.0), ("relative", 0.0),
])
def test_moving_closure_clicks_counterfactual_onset_without_curl_bias(pipeline_factory, fps, style, mode, offset):
    # Establish the expected native location before running the closure replay.
    baseline = pipeline_factory(fps, mode=mode)
    baseline.prime(offset=offset)
    baseline.send(dx=offset)
    expected = baseline.events("move")[-1][1:3]
    actual = pipeline_factory(fps, mode=mode)
    actual.prime(offset=offset)
    for index, closure in enumerate(closure_frames(fps, style)):
        actual.send(closure, dx=offset + 36 * index / fps)
        assert not actual.events("left_down"), "Closure evidence alone must not post a native down"
    end_dx = offset + 36 * (len(closure_frames(fps, style)) - 1) / fps
    actual.hold(0.35, dx=end_dx)
    assert len(actual.events("left_down")) == len(actual.events("left_up")) == 1
    assert not actual.events("left_dragged")
    click = actual.events("left_down")[0][1:3]
    assert hypot(click[0] - expected[0], click[1] - expected[1]) <= 4, (expected, click)


@pytest.mark.parametrize("curl", [20.0, 30.0, 40.0])
def test_stationary_index_curl_does_not_bias_target(pipeline_factory, curl):
    baseline = pipeline_factory()
    baseline.prime(speed=0)
    baseline.send()
    expected = baseline.events("move")[-1][1:3]
    actual = pipeline_factory()
    actual.prime(speed=0)
    actual.hold(0.2, 1.0, curl=curl)
    actual.hold(0.35)
    assert len(actual.events("left_down")) == len(actual.events("left_up")) == 1
    click = actual.events("left_down")[0][1:3]
    assert hypot(click[0] - expected[0], click[1] - expected[1]) <= 4, (expected, click)


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_translation_alone_is_legitimate_mouse_motion(pipeline_factory, fps):
    replay = pipeline_factory(fps)
    replay.prime(speed=0)
    start = replay.events("move")[-1][1]
    for index in range(round(0.6 * fps)):
        replay.send(dx=60 * (index + 1) / fps)
    assert replay.events("move")[-1][1] > start + 60
    assert not replay.events("left_down")


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_candidate_without_closure_never_posts_down(pipeline_factory, fps):
    replay = pipeline_factory(fps)
    replay.prime()
    replay.hold(0.3, 0.45)
    replay.hold(0.4)
    assert not replay.events("left_down")


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("boundary", ["spike", "lost", "stale", "gap", "jump", "fist"])
def test_ambiguous_or_discontinuous_episode_cannot_click(pipeline_factory, fps, boundary):
    replay = pipeline_factory(fps)
    replay.prime(speed=0)
    if boundary == "spike":
        replay.send(1.0)
    elif boundary == "lost":
        replay.send(missing=True)
        replay.hold(0.25, 1.0)
    elif boundary in {"stale", "gap"}:
        replay.hold(0.1, 0.4)
        replay.send(1.0, **({"age": 0.4} if boundary == "stale" else {"gap": 0.4}))
        replay.hold(0.2, 1.0)
    elif boundary == "jump":
        # Thumb/index close at the same moment the palm teleports: no continuous
        # physical trajectory supports linking this shape to the prior aim.
        replay.hold(0.2, 1.0, dx=190)
    else:
        for index in range(max(3, round(0.2 * fps))):
            amount = (index + 1) / max(3, round(0.2 * fps))
            replay.send(amount, fist=amount)
        replay.hold(0.2, 1.0, fist=1.0)
    replay.hold(0.4)
    assert not replay.events("left_down"), boundary
    assert not replay.events("left_up"), boundary
    # Rejecting a suspect episode must still permit a fresh deliberate click
    # after a genuine opening, without restarting the application.
    replay.hold(0.2, 1.0)
    replay.hold(0.3)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_held_index_bending_alone_cannot_become_drag(pipeline_factory, fps):
    replay = pipeline_factory(fps)
    replay.prime(speed=0)
    replay.hold(0.5, 1.0)
    # Both fingers stay closed as the tip bends another 10px; the palm is still.
    for index in range(round(0.3 * fps)):
        curl = 30 + 10 * (index + 1) / round(0.3 * fps)
        replay.send(1.0, curl=curl)
    assert not replay.events("left_down")
    assert not replay.events("left_dragged")
    replay.hold(0.4)
    assert not replay.events("left_down"), "An overlong stationary hold is not a short click"


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_whole_hand_translation_starts_and_continues_drag_then_opens_once(pipeline_factory, fps):
    replay = pipeline_factory(fps)
    replay.prime(speed=0)
    replay.hold(0.15, 1.0)
    for index in range(round(0.7 * fps)):
        replay.send(1.0, dx=90 * (index + 1) / round(0.7 * fps))
    assert len(replay.events("left_down")) == 1
    assert not replay.events("left_up")
    drags = replay.events("left_dragged")
    assert len(drags) >= 4 and drags[-1][1] > drags[0][1] + 40
    replay.hold(0.4, dx=90)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1
    assert replay.engine.action_machine.state is ActionState.MOVING


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_rearmed_short_pinches_preserve_native_double_click(pipeline_factory, fps):
    replay = pipeline_factory(fps)
    replay.prime(speed=0)
    for _ in range(2):
        replay.hold(0.16, 1.0)
        replay.hold(0.14)
    replay.hold(0.3)
    assert [event[4] for event in replay.events("left_down")] == [1, 2]
    assert [event[4] for event in replay.events("left_up")] == [1, 2]
    assert not replay.events("left_dragged")


@pytest.mark.parametrize("mode", ["absolute", "relative"])
@pytest.mark.parametrize("episode", ["candidate", "drag"])
def test_camera_geometry_change_discards_episode_and_releases_owed_drag(pipeline_factory, mode, episode):
    replay = pipeline_factory(mode=mode)
    replay.prime(speed=0)
    dx = 0.0
    if episode == "candidate":
        replay.send(0.4)
        assert replay.snapshots[-1].pinch_phase == "candidate"
        assert not replay.events("left_down")
    else:
        replay.hold(0.15, 1.0)
        for index in range(21):
            replay.send(1.0, dx=90 * (index + 1) / 21)
        dx = 90.0
        assert len(replay.events("left_down")) == 1
        assert replay.events("left_dragged")
        assert not replay.events("left_up")

    # Same normalized hand, but a camera changes from 640x480 to 832x624.
    # Every landmark, including the palm scaffold, scales coherently by 1.3.
    resized = {"frame_size": (832, 624), "coordinate_scale": 1.3, "dx": dx}
    before = len(replay.native.mouse)
    snapshot = replay.send(1.0, **resized)
    assert snapshot.error == "frame_geometry_changed"
    emitted = replay.native.mouse[before:]
    assert [event[0] for event in emitted] == (["left_up"] if episode == "drag" else [])
    down_count = 1 if episode == "drag" else 0
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == down_count

    # The discarded closed observation cannot establish a new press, nor can
    # subsequent closed frames reuse the old candidate or drag admission.
    replay.hold(0.5, 1.0, **resized)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == down_count
    assert replay.engine.action_machine.state is ActionState.MOVING
    replay.hold(0.4, **resized)
    replay.hold(0.2, 1.0, **resized)
    replay.hold(0.3, **resized)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == down_count + 1


@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_missing_clean_pointer_history_cancels_instead_of_guessing_click_position(pipeline_factory, mode):
    replay = pipeline_factory(mode=mode)
    replay.prime(speed=0)
    # Inject the reconstruction failure at its actual boundary. All perception,
    # admission, arbitration, mapping and native dispatch still run normally.
    replay.engine._pointer_history.clear()
    snapshot = replay.send(0.4)
    assert snapshot.pinch_phase == "cancelled"
    assert snapshot.pinch_reason == "pointer_history_unavailable"
    assert snapshot.error == ""
    replay.hold(0.2, 1.0)
    assert replay.snapshots[-1].pinch_phase == "cancelled"
    assert not replay.events("left_down")
    assert not replay.events("left_up")
    replay.hold(0.4)
    assert not replay.events("left_down")
    replay.hold(0.2, 1.0)
    replay.hold(0.3)
    assert len(replay.events("left_down")) == len(replay.events("left_up")) == 1

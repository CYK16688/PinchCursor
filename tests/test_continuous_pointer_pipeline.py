"""Landmark replays through the complete control lane, ending at fake OS input.

Only camera/native services, time, display geometry and rendering are replaced.
Classification, dynamics, session gating, arbitration, smoothing, state changes,
context policy, dispatch and the macOS controller run as they do for live frames.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from core.mediapipe_worker import LandmarkFrame
from core.pointer_mapping import ScreenBounds
from gui import main_window
from platform_services.contracts import (
    AuthorizationState,
    PermissionSnapshot,
    PlatformCapabilities,
    PlatformServices,
    UIContext,
)
from platform_services.macos.input_controller import MacOSInputController
from platform_services.null import NullHoldShortcutMonitor, UnavailableCameraService
from platform_services.policy import ContextPolicy
from tests.test_pinch_pointer_freeze import _pose
from utils.config_manager import ConfigManager


class ReplayClock:
    now = 10.0

    def __call__(self):
        return self.now


@dataclass(frozen=True)
class MouseEvent:
    kind: str
    x: float
    y: float
    button: str
    click_count: int
    at: float


class RecordingNative:
    def __init__(self, clock):
        self.clock = clock
        self.mouse = []
        self.scrolls = []
        self.hotkeys = []

    def post_mouse(self, kind, x, y, button, click_count=1):
        self.mouse.append(MouseEvent(kind, x, y, button, click_count, self.clock()))

    def post_scroll(self, vertical, horizontal):
        self.scrolls.append((vertical, horizontal, self.clock()))

    def post_hotkey(self, hotkey):
        self.hotkeys.append(hotkey)


class MutableContext:
    def __init__(self):
        self.target_id = "document-a"
        self.policy = ContextPolicy.default()
        self.queries = []

    def get_context(self, x=None, y=None):
        # Pointing starts near y=270, but curling the index for thumb-down
        # places its tip beyond y=600. That pose change must not move the aimed
        # pointer or make the scroll probe leave this target.
        inside = x is not None and y is not None and 0 <= x < 1920 and 0 <= y < 450
        category = "scrollable" if inside else "generic"
        target_id = self.target_id if inside else ""
        self.queries.append((x, y, category, target_id))
        return UIContext(
            category=category,
            native_role="AXScrollArea" if inside else "AXGroup",
            source="fake-ax",
            target_id=target_id,
        )

    def is_gesture_allowed(self, gesture, x=None, y=None):
        return self.policy.is_gesture_allowed(self.get_context(x, y), gesture)

    def is_action_allowed(self, action, x=None, y=None):
        return self.policy.is_action_allowed(self.get_context(x, y), action)


def landmarks_for(pose, dx=0.0):
    if pose is None:
        return None
    landmarks = _pose(pose == "pinch")
    if pose == "open_hand":
        landmarks[12] = (320.0, 90.0, 0.0)
        landmarks[16] = (391.0, 110.0, 0.0)
        landmarks[20] = (441.0, 145.0, 0.0)
    elif pose == "thumb_down":
        landmarks[8] = (270.0, 285.0, 0.0)
        landmarks[2] = (235.0, 280.0, 0.0)
        landmarks[4] = (235.0, 400.0, 0.0)
    return [(x + dx, y, z) for x, y, z in landmarks]


class Replay:
    def __init__(self, window, clock, native, context):
        self.window = window
        self.clock = clock
        self.native = native
        self.context = context
        self.fps = 30
        self.frame = SimpleNamespace(shape=(480, 640, 3))

    def send(self, pose, *, dx=0.0, age=0.0):
        self.clock.now += 1.0 / self.fps
        timestamp_ms = round(self.clock.now * 1000)
        self.clock.now = timestamp_ms / 1000.0 + age
        self.window.process_frame(LandmarkFrame(
            frame=self.frame,
            landmarks=landmarks_for(pose, dx),
            timestamp_ms=timestamp_ms,
        ))

    def hold(self, pose, seconds, *, dx=0.0, travel=0.0):
        frames = max(1, round(seconds * self.fps))
        for index in range(frames):
            self.send(pose, dx=dx + travel * index / max(1, frames - 1))

    def events(self, kind):
        return [event for event in self.native.mouse if event.kind == kind]

    def start_drag(self):
        self.hold("point", 0.6)
        self.hold("pinch", 0.9, travel=100)
        assert self.events("left_down"), "A physical held pinch must start the drag before release"
        assert len(self.events("left_dragged")) >= 5
        assert not self.events("left_up")


@pytest.fixture
def replay(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    clock = ReplayClock()
    native = RecordingNative(clock)
    controller = MacOSInputController(native, clock=clock)
    context = MutableContext()
    permissions = PermissionSnapshot(
        camera=AuthorizationState.GRANTED,
        accessibility=AuthorizationState.GRANTED,
        input_monitoring=AuthorizationState.GRANTED,
    )
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos", architecture="fake",
            supported_actions=controller.supported_actions,
            permissions=permissions,
        ),
        input_controller=controller,
        context_provider=context,
        permission_provider=SimpleNamespace(snapshot=lambda: permissions),
        camera_service=UnavailableCameraService(),
        hold_shortcut_monitor=NullHoldShortcutMonitor(),
    )
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("control_session", "mode", "always")
    config.set("pointer_assist", "enabled", False)
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
    monkeypatch.setattr(main_window.MainWindow, "_create_platform_services_from_config", lambda self: services)
    monkeypatch.setattr(main_window.MainWindow, "_compute_screen_bounds", staticmethod(lambda: ScreenBounds(0, 0, 1920, 1080)))
    # Prevent creation of a native HUD panel; all platform interaction belongs
    # to the fake service bundle above, before any widgets are constructed.
    monkeypatch.setattr(main_window.platform, "system", lambda: "test")
    monkeypatch.setattr(main_window.time, "monotonic", clock)
    window = main_window.MainWindow()
    for method in ("_render_hud", "display_frame"):
        monkeypatch.setattr(window, method, lambda *args, **kwargs: None)
    for method in ("_draw_landmarks", "_draw_edge_hint", "_draw_aiming_indicator"):
        monkeypatch.setattr(window, method, lambda frame, *args, **kwargs: frame)
    window.is_running = True
    guard = window.action_coordinator.input_guard
    guard._clock = clock
    guard.start(threaded=False)
    yield Replay(window, clock, native, context)
    window.close()
    app.processEvents()


@pytest.mark.parametrize(("fps", "pinch_seconds"), [(15, 0.2), (30, 0.16), (60, 0.16)])
def test_short_pinch_emits_exactly_one_complete_click(replay, fps, pinch_seconds):
    replay.fps = fps
    replay.hold("point", 0.6)
    replay.hold("pinch", pinch_seconds)
    replay.hold("point", 0.4)

    assert len(replay.events("left_down")) == 1
    assert len(replay.events("left_up")) == 1
    assert not replay.events("left_dragged")
    assert replay.events("left_down")[0].click_count == 1
    assert replay.native.hotkeys == []
    assert replay.native.scrolls == []


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_two_short_pinches_emit_two_clicks_with_double_click_state(replay, fps):
    replay.fps = fps
    replay.hold("point", 0.6)
    replay.hold("pinch", 0.2)
    replay.hold("point", 0.14)
    replay.hold("pinch", 0.2)
    replay.hold("point", 0.4)

    assert [event.click_count for event in replay.events("left_down")] == [1, 2]
    assert [event.click_count for event in replay.events("left_up")] == [1, 2]
    assert not replay.events("left_dragged")


@pytest.mark.parametrize("release_pose", ["point", "open_hand"])
@pytest.mark.parametrize("fps", [15, 30, 60])
def test_held_pinch_moves_native_drag_and_releases_with_no_extra_click(replay, release_pose, fps):
    replay.fps = fps
    replay.start_drag()
    dragged = replay.events("left_dragged")
    assert dragged[-1].x > dragged[0].x + 50

    replay.hold(release_pose, 0.4, dx=100)

    assert len(replay.events("left_down")) == 1
    assert len(replay.events("left_up")) == 1
    assert replay.window.action_machine.state is ActionState.MOVING
    assert replay.native.scrolls == []
    assert replay.native.hotkeys == []


def test_point_dwell_then_thumb_holds_continuous_scroll_and_point_stops_it(replay):
    replay.hold("point", 0.7)
    replay.hold("thumb_down", 1.0)

    assert 3 <= len(replay.native.scrolls) <= 10
    assert all(vertical < 0 and horizontal == 0 for vertical, horizontal, _ in replay.native.scrolls)
    point_started = replay.clock.now
    replay.hold("point", 0.4)
    count = len(replay.native.scrolls)
    replay.hold("point", 0.4)
    assert len(replay.native.scrolls) == count
    assert all(at <= point_started + 0.25 for _, _, at in replay.native.scrolls)
    assert not replay.events("left_down")


def test_thumb_pose_change_keeps_aim_and_context_on_scroll_target(replay):
    # Exercise the optional target-identity lane separately from core wheel input.
    replay.window.config.set("pointer_scroll", "enabled", False)
    replay.hold("point", 0.7)
    aim = replay.events("move")[-1]
    assert aim.y < 450
    before_thumb = len(replay.native.mouse)
    replay.context.queries.clear()

    replay.hold("thumb_down", 1.0)

    assert len(replay.native.scrolls) >= 3
    assert replay.context.queries
    assert all(category == "scrollable" for _, _, category, _ in replay.context.queries)
    assert all(
        (x, y) == pytest.approx((aim.x, aim.y), abs=1)
        for x, y, _, _ in replay.context.queries
    )
    assert all(
        (event.x, event.y) == pytest.approx((aim.x, aim.y), abs=1)
        for event in replay.native.mouse[before_thumb:]
        if event.kind == "move"
    )

    replay.hold("point", 0.5, dx=80)
    assert replay.events("move")[-1].x > aim.x + 100
    assert replay.events("move")[-1].y == pytest.approx(aim.y, abs=2)


def test_thumb_without_prior_point_never_scrolls(replay):
    replay.hold("thumb_down", 1.0)
    assert replay.native.scrolls == []
    assert not replay.events("left_down")


def test_scroll_target_change_stops_until_new_target_is_pointed_at(replay):
    replay.window.config.set("pointer_scroll", "enabled", False)
    replay.hold("point", 0.7)
    replay.hold("thumb_down", 0.7)
    before_change = len(replay.native.scrolls)
    assert before_change >= 2
    anchor_queries = replay.context.queries[-1][:2]
    replay.context.queries.clear()

    replay.context.target_id = "document-b"
    replay.hold("thumb_down", 0.6)
    assert len(replay.native.scrolls) == before_change
    assert replay.context.queries
    assert all(
        (x, y) == pytest.approx(anchor_queries, abs=1) and target == "document-b"
        for x, y, _, target in replay.context.queries
    )

    replay.hold("point", 0.7)
    replay.hold("thumb_down", 0.7)
    assert len(replay.native.scrolls) >= before_change + 2


def test_tracking_loss_releases_drag_once_and_does_not_use_predicted_position(replay):
    replay.start_drag()
    before_loss = len(replay.native.mouse)

    replay.send(None)
    replay.hold(None, 0.4)

    assert [event.kind for event in replay.native.mouse[before_loss:]] == ["left_up"]
    replay.hold("point", 0.4, dx=100)
    assert len(replay.events("left_down")) == 1
    assert len(replay.events("left_up")) == 1


def test_tracking_loss_clears_scroll_target_even_if_same_thumb_returns(replay):
    replay.hold("point", 0.7)
    replay.hold("thumb_down", 0.7)
    before_loss = len(replay.native.scrolls)
    assert before_loss >= 2

    replay.send(None)
    replay.hold("thumb_down", 0.7)
    assert len(replay.native.scrolls) == before_loss


def test_stale_frame_releases_drag_without_replaying_its_motion(replay):
    replay.start_drag()
    before_stale = len(replay.native.mouse)

    replay.send("pinch", dx=150, age=0.4)

    assert [event.kind for event in replay.native.mouse[before_stale:]] == ["left_up"]
    assert replay.window.action_machine.state is ActionState.MOVING
    replay.hold("point", 0.4, dx=150)
    assert len(replay.events("left_down")) == 1


def test_camera_silence_releases_drag_without_another_frame_or_gui_callback(replay):
    replay.start_drag()
    before_timeout = len(replay.native.mouse)

    replay.clock.now += 0.4
    guard = replay.window.action_coordinator.input_guard
    assert guard.check_timeout().executed
    guard.check_timeout()

    assert [event.kind for event in replay.native.mouse[before_timeout:]] == ["left_up"]
    replay.hold("point", 0.4, dx=100)
    assert replay.window.action_machine.state is ActionState.MOVING
    assert len(replay.events("left_down")) == 1

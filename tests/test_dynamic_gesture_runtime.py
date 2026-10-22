import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from core.control_session import SessionState
from core.dynamic_gesture_template import DynamicGestureTemplate
from gui import main_window
from platform_services.contracts import ActionResult


def _template(action="scroll_up", hotkey=""):
    return DynamicGestureTemplate(
        template_id="recorded-swipe",
        name="Recorded swipe",
        action=action,
        samples=(((0.0,) * 63, (0.1,) * 63),),
        threshold=0.18,
        cooldown_seconds=0.75,
        min_motion_energy=0.05,
    )


class MatchingRuntime:
    def __init__(self, template):
        self.template = template
        self.calls = []

    def ingest(self, frames, *, active, now, context_category=""):
        # Context filtering is part of the runtime contract; this fake keeps the
        # same signature so the window can pass it unconditionally.
        self.calls.append((frames, active, now, context_category))
        return self.template


def test_recorded_dynamic_shortcut_dispatches_the_bound_semantic_action():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    dispatched = []
    try:
        template = _template("custom_hotkey", "cmd+shift+p")
        window.dynamic_runtime_matcher = MatchingRuntime(template)
        window.config.set("dynamic_gestures", "enabled", True)
        window.config.set("dynamic_gestures", "templates", [{
            "template_id": template.template_id,
            "name": template.name,
            "action": template.action,
            "hotkey": "cmd+shift+p",
            "samples": [[list(frame) for frame in sample] for sample in template.samples],
            "threshold": template.threshold,
            "cooldown_seconds": template.cooldown_seconds,
            "min_motion_energy": template.min_motion_energy,
        }])
        window.control_session.state = SessionState.POINTER
        window.action_machine.state = ActionState.MOVING
        window.dynamic_landmark_frames.extend(([(0.0, 0.0, 0.0)] * 21,) * 2)
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        committed = []
        window.intent_arbiter.mark_shortcut_committed = lambda: committed.append(True)

        assert window._dispatch_completed_dynamic_shortcut(
            tuple(window.dynamic_landmark_frames), (100, 200), now=5.0
        ) is True
        assert dispatched[0].action == "custom_hotkey"
        assert dispatched[0].hotkey == "cmd+shift+p"
        assert dispatched[0].gesture == "dynamic_shortcut"
        assert committed == [True]
    finally:
        window.close()


def test_recorded_dynamic_shortcut_is_disabled_by_default_even_with_a_runtime_matcher():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    dispatched = []
    try:
        window.dynamic_runtime_matcher = MatchingRuntime(_template())
        window.control_session.state = SessionState.POINTER
        window.action_machine.state = ActionState.MOVING
        window.dynamic_landmark_frames.extend(([(0.0, 0.0, 0.0)] * 21,) * 2)
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)

        assert window._dispatch_completed_dynamic_shortcut(
            tuple(window.dynamic_landmark_frames), (100, 200), now=5.0
        ) is False
        assert dispatched == []
    finally:
        window.close()


def test_recorded_dynamic_shortcut_never_runs_before_activation_or_during_drag():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    dispatched = []
    try:
        matcher = MatchingRuntime(_template())
        window.dynamic_runtime_matcher = matcher
        window.dynamic_landmark_frames.extend(([(0.0, 0.0, 0.0)] * 21,) * 2)
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)

        window.control_session.state = SessionState.INACTIVE
        window.action_machine.state = ActionState.MOVING
        assert window._dispatch_completed_dynamic_shortcut(
            tuple(window.dynamic_landmark_frames), (100, 200), now=5.0
        ) is False

        window.control_session.state = SessionState.POINTER
        window.action_machine.state = ActionState.DRAGGING
        assert window._dispatch_completed_dynamic_shortcut(
            tuple(window.dynamic_landmark_frames), (100, 200), now=6.0
        ) is False

        assert matcher.calls == []
        assert dispatched == []
    finally:
        window.close()


def test_pinch_frame_never_enters_dynamic_shortcut_matching(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    matcher = MatchingRuntime(_template())
    dispatched = []
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.dynamic_runtime_matcher = matcher
        window.config.set("dynamic_gestures", "enabled", True)
        window._update_power_mode = lambda _landmarks, **_kwargs: None
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), True)
        window._check_edge_lost = lambda _landmarks, _now: None
        window.classifier.classify = lambda _landmarks, **_kwargs: "pinch"
        window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: {
            "distance": 20, "velocity": -10, "is_approaching": True
        }
        window._refresh_control_session_status = lambda **_kwargs: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        frame = type("Frame", (), {"shape": (480, 640, 3)})()
        landmark_frame = type("LandmarkFrame", (), {
            "frame": frame, "landmarks": [(0.0, 0.0, 0.0)] * 21
        })()

        window.process_frame(landmark_frame)

        assert matcher.calls == []
        assert dispatched == []
    finally:
        window.close()


def test_live_dynamic_lane_does_not_claim_a_motion_without_a_saved_runtime_template(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    gestures = iter(("none", "none", "none", "open_hand", "peace"))
    dispatched = []
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.control_session.update = lambda **_kwargs: None
        window.config.set("dynamic_gestures", "enabled", True)
        window.config.set("context_aware", "enabled", False)
        # No saved runtime matcher means the dynamic lane must not own this
        # sequence; disable the default open-hand static binding so the test
        # isolates the succeeding peace static action.
        window.config.set("gestures", "open_hand", {
            "enabled": False, "action": "none", "hotkey": ""
        })
        window.gesture_grace_period = 0
        window._update_power_mode = lambda _landmarks, **_kwargs: None
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), True)
        window._check_edge_lost = lambda _landmarks, _now: None
        window.classifier.classify = lambda _landmarks, **_kwargs: next(gestures)
        window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: {
            "distance": 100, "velocity": 0, "is_approaching": False
        }
        window._refresh_control_session_status = lambda **_kwargs: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        frame = type("Frame", (), {"shape": (480, 640, 3)})()
        landmark_frame = type("LandmarkFrame", (), {
            "frame": frame, "landmarks": [(0.0, 0.0, 0.0)] * 21
        })()

        for _ in range(5):
            window.process_frame(landmark_frame)

        assert window.dynamic_intent_lifecycle.state.value == "neutral"
        assert [request.action for request in dispatched] == ["right_click"]
    finally:
        window.close()


def test_dynamic_recording_owns_the_frame_and_suppresses_static_actions_and_combos(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    gestures = iter(("none", "none", "none", "open_hand", "peace"))
    dispatched = []
    combo_updates = []
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.control_session.update = lambda **_kwargs: None
        window.config.set("dynamic_gestures", "enabled", True)
        window.dynamic_runtime_matcher = MatchingRuntime(_template("scroll_down"))
        window.config.set("gestures", "peace", {
            "enabled": True, "action": "right_click", "hotkey": ""
        })
        window.gesture_grace_period = 0
        window._update_power_mode = lambda _landmarks, **_kwargs: None
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), True)
        window._check_edge_lost = lambda _landmarks, _now: None
        window.classifier.classify = lambda _landmarks, **_kwargs: next(gestures)
        window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: {
            "distance": 100, "velocity": 0, "is_approaching": False
        }
        window._refresh_control_session_status = lambda **_kwargs: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None
        window.combo_detector.update = lambda gesture, **_kwargs: combo_updates.append(gesture)
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        frame = type("Frame", (), {"shape": (480, 640, 3)})()
        landmark_frame = type("LandmarkFrame", (), {
            "frame": frame, "landmarks": [(0.0, 0.0, 0.0)] * 21
        })()

        for _ in range(5):
            window.process_frame(landmark_frame)

        assert dispatched == []
        assert combo_updates == []
    finally:
        window.close()


def test_live_dynamic_shortcut_matches_only_after_a_complete_neutral_delimited_motion(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    matcher = MatchingRuntime(_template("scroll_down"))
    dispatched = []
    gestures = iter(("none", "none", "none", "open_hand", "peace", "none", "none", "peace"))
    try:
        window.is_running = True
        window.control_session.state = SessionState.POINTER
        window.control_session.update = lambda **_kwargs: None
        window.dynamic_runtime_matcher = matcher
        window.config.set("dynamic_gestures", "enabled", True)
        window._update_power_mode = lambda _landmarks, **_kwargs: None
        window.tracker.update = lambda _landmarks, _shape, **_kwargs: ((100, 100), True)
        window._check_edge_lost = lambda _landmarks, _now: None
        window.classifier.classify = lambda _landmarks, **_kwargs: next(gestures)
        window.classifier.get_pinch_info = lambda _landmarks, **_kwargs: {
            "distance": 100, "velocity": 0, "is_approaching": False
        }
        window._refresh_control_session_status = lambda **_kwargs: None
        window._get_status_text = lambda _detected: "test"
        window._render_hud = lambda **_kwargs: None
        window._draw_landmarks = lambda frame, _landmarks: frame
        window._draw_edge_hint = lambda frame, **_kwargs: frame
        window.display_frame = lambda _frame: None
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        frame = type("Frame", (), {"shape": (480, 640, 3)})()
        landmark_frame = type("LandmarkFrame", (), {
            "frame": frame, "landmarks": [(0.0, 0.0, 0.0)] * 21
        })()

        for _ in range(6):
            window.process_frame(landmark_frame)
        assert matcher.calls == []
        assert dispatched == []

        window.process_frame(landmark_frame)
        assert len(matcher.calls) == 1
        assert [request.action for request in dispatched] == ["scroll_down"]

        window.process_frame(landmark_frame)
        assert len(matcher.calls) == 1
        assert [request.action for request in dispatched] == ["scroll_down"]
    finally:
        window.close()


def test_legacy_single_frame_dynamic_observer_cannot_bypass_neutral_delimited_lifecycle():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    dispatched = []
    try:
        window.dynamic_runtime_matcher = MatchingRuntime(_template("scroll_down"))
        window.config.set("dynamic_gestures", "enabled", True)
        window.control_session.state = SessionState.POINTER
        window.action_machine.state = ActionState.MOVING
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)

        assert window.observe_recorded_dynamic_shortcut(
            [(0.0, 0.0, 0.0)] * 21, (100, 200), now=5.0
        ) is False
        assert not window.dynamic_landmark_frames
        assert dispatched == []
    finally:
        window.close()

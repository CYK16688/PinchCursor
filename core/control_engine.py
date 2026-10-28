"""Single-owner, GUI-independent continuous gesture control.

The runtime delivers immutable, fresh observations to ``step``. All gesture
history and decision state live here; rendering consumes snapshots and never
participates in dispatch. Context and telemetry are injected nonblocking ports.
Native input is exclusively owned by the coordinator and its watchdog.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from numbers import Real
import os
import time

from core.action_state_machine import ActionState, ActionStateMachine, PinchActionEvidence
from core.assist.features import build_features
from core.assist.ranker import LinearRanker
from core.assist.target_model import Target, TargetModel
from core.combo_detector import ComboDetector
from core.contextual_intent import ContextualIntentController
from core.control_session import ActivationMode, ControlSession, SessionState
from core.dynamic_gesture_template import DynamicGestureMatcher, DynamicGestureTemplate
from core.dynamic_intent_lifecycle import DynamicIntentLifecycle, DynamicIntentState
from core.gesture_classifier import GestureClassifier
from core.hand_dynamics import HandDynamics
from core.input_guard import frame_is_fresh
from core.intent_arbiter import IntentArbiter, IntentDecision, IntentOwner
from core.pinch_intent import PinchEvidence, PinchIntentObserver
from core.performance import preset_for
from core.pointer_mapping import AbsoluteMapper, RelativeMapper, ScreenBounds
from core.scroll_intent import ScrollIntentController
from core.static_gesture_template import StaticGestureMatcher, StaticGestureTemplate
from core.transition_episodes import PinchEpisodeTracker
from core.transition_model import TransitionModel
from platform_services.contracts import ActionRequest, ActionResult
from utils.smoothing import (
    CURSOR_SMOOTHING_BETA, DEFAULT_DEAD_ZONE, CursorSmoother, mincutoff_for_smoothing,
)
from utils.tracker import TargetTracker


@dataclass(frozen=True)
class HandObservation:
    timestamp: float
    landmarks: tuple | list | None
    frame_size: tuple[int, int]
    shortcut_held: bool = False

    def __post_init__(self):
        # Copy mutable detector output before crossing a thread boundary. Invalid
        # shapes remain inspectable so step can release input rather than raise.
        if isinstance(self.landmarks, (list, tuple)):
            object.__setattr__(self, "landmarks", tuple(
                tuple(point) if isinstance(point, (list, tuple)) else point
                for point in self.landmarks
            ))
        if isinstance(self.frame_size, (list, tuple)):
            object.__setattr__(self, "frame_size", tuple(self.frame_size))


@dataclass(frozen=True)
class DispatchOutcome:
    request: ActionRequest
    result: ActionResult


@dataclass(frozen=True)
class ControlSnapshot:
    timestamp: float
    gesture: str
    raw_gesture: str
    session_state: SessionState
    pointer_state: ActionState
    hand_present: bool
    anchor: tuple[float, float] | None
    locked_position: tuple[float, float] | None
    outcomes: tuple[DispatchOutcome, ...] = ()
    error: str = ""
    preview_locked_position: tuple[int, int] | None = None
    pinch_phase: str = "idle"
    pinch_reason: str = ""


def _point_inside(x, y, bounds):
    bx, by, bw, bh = bounds
    return bx <= x <= bx + bw and by <= y <= by + bh


class ControlEngine:
    """A synchronous control transaction; callers must serialize all mutations.

    ``config`` is copied once and model files are read only during construction.
    Replace the engine at a stopped boundary to apply changed settings. The
    caller owns watchdog startup and the lifetimes of context/telemetry ports.
    """

    def __init__(self, config: dict, bounds: ScreenBounds, coordinator, *,
                 cursor_position, clock=time.monotonic, telemetry=None):
        self.config = deepcopy(config)
        self.clock = clock
        self.cursor_position = cursor_position
        self.screen_bounds = bounds
        self.screen_w, self.screen_h = bounds.width, bounds.height
        self.action_coordinator = coordinator
        self.platform_services = coordinator.services
        self.telemetry = telemetry
        self.classifier = GestureClassifier()
        self.tracker = TargetTracker(clock=clock)
        self.action_machine = ActionStateMachine(clock=clock)
        self.action_machine.set_screen_size(bounds.width, bounds.height)
        self.intent_arbiter = IntentArbiter()
        self.pinch_intent = PinchIntentObserver()
        self._pointer_history = deque(maxlen=64)
        self._joint_motion_history = deque(maxlen=64)
        self._joint_evidence = None
        self._joint_target = self._joint_motion_anchor = None
        self._joint_mapping_failed = False
        self._joint_pointer_state = None
        self._joint_landmarks = None
        self._current_motion_pos = None
        self.contextual_intent_controller = ContextualIntentController()
        scroll = self.config.get("pointer_scroll") or {}
        self.pointer_scroll_enabled = scroll.get("enabled", True) is True
        self.scroll_intent_controller = ScrollIntentController(
            dwell_seconds=scroll.get("dwell_seconds", 0.3),
            repeat_seconds=scroll.get("repeat_seconds", 0.12),
            enter_seconds=scroll.get("enter_seconds", 0.08),
        )
        self.combo_detector = ComboDetector(clock=clock)
        self.combo_detector.set_combos(self.config.get("gesture_combos") or [])
        self.pinch_episodes = PinchEpisodeTracker(clock=clock)
        self.transition_model = None
        self._last_frame_time = float("-inf")
        self._last_frame_size = None
        self._hand_present_last_frame = False
        self.hud_anchor = None
        self._locked_position = None
        self._outcomes = []
        self.last_stable_gesture = "none"
        self.last_gesture_change_time = None
        self.last_executed_gesture = "none"
        self.last_executed_action = "none"
        self.gesture_grace_period = 0.2
        self._configure_pointer()
        self._refresh_control_session_from_config()
        self._refresh_dynamic_shortcuts_from_config()
        self._reset_gesture_observation_state()

    def _get_gesture(self, gesture):
        return (self.config.get("gestures") or {}).get(gesture) or {}

    def _get_gesture_action(self, gesture):
        record = self._get_gesture(gesture)
        return record.get("action", "none") if record.get("enabled", True) else "none"

    def _configure_pointer(self):
        self.preset = preset_for((self.config.get("performance") or {}).get("mode"))
        sensitivity = self.config.get("global_sensitivity") or {}
        self.smoother = CursorSmoother(
            mincutoff=mincutoff_for_smoothing(sensitivity.get("smoothing"),
                                           default=self.preset.smoothing_mincutoff),
            beta=CURSOR_SMOOTHING_BETA,
            dead_zone=sensitivity.get("dead_zone", DEFAULT_DEAD_ZONE),
            clock=self.clock,
        )
        calibration = self.config.get("pinch_calibration") or {}
        try:
            self.classifier.set_pinch_calibration(
                float(calibration["enter_ratio"]), float(calibration["exit_ratio"])
            )
        except (KeyError, TypeError, ValueError):
            self.classifier.pinch_threshold = self._get_gesture("pinch").get("threshold", 35)
        self.classifier.hold_threshold = self._get_gesture("pinch_hold").get("hold_time", 0.3)
        stabilization = self.config.get("stabilization") or {}
        for key, default in (("confirm_threshold", 3), ("min_switch_interval", 0.15),
                             ("exit_threshold", 4), ("cooldown_time", 0.2)):
            setattr(self.classifier, key, stabilization.get(key, default))
        self.hand_dynamics = HandDynamics(enter_ratio=self.classifier.pinch_enter_ratio,
                                          exit_ratio=self.classifier.pinch_exit_ratio)
        action = self.config.get("action_mode") or {}
        for key, default in (("dwell_threshold", 0.3), ("move_threshold", 8),
                             ("drag_threshold", 0.3)):
            setattr(self.action_machine, key, action.get(key, default))
        self.action_machine.set_zone_rules(self.config.get("zone_rules") or [])
        mapping = self.config.get("pointer_mapping") or {}
        try:
            self.pointer_mapper = (RelativeMapper(mapping.get("gain", 2.0))
                                   if mapping.get("mode") == "relative" else AbsoluteMapper())
        except (TypeError, ValueError):
            self.pointer_mapper = AbsoluteMapper()
        self._refresh_pointer_assist()
        self._refresh_transition_model()

    def _map_pointer(self, pos, frame_size):
        if self._pointer_anchor_pending and isinstance(self.pointer_mapper, RelativeMapper):
            self.pointer_mapper.begin(pos, frame_size, self.screen_bounds,
                                      cursor=self.cursor_position())
            self.smoother.reset()
        self._pointer_anchor_pending = False
        return self.pointer_mapper.map(pos, frame_size, self.screen_bounds)

    def reset(self):
        """Release native input and discard candidates at a control boundary."""
        result = self.action_coordinator.stop()
        outcome = DispatchOutcome(ActionRequest("drag_end", core_pointer=True), result)
        self.action_machine.reset()
        self.control_session.reset()
        self._reset_gesture_observation_state()
        self.tracker.reset()
        self.smoother.reset()
        self.classifier.reset_stabilization()
        self.hand_dynamics.reset()
        self.pointer_mapper.reset()
        self.pinch_episodes.reset()
        self._hand_present_last_frame = False
        self._locked_position = None
        self._last_frame_size = None
        self.hud_anchor = None
        self.last_stable_gesture = "none"
        self.last_gesture_change_time = None
        self.last_executed_gesture = "none"
        self.last_executed_action = "none"
        return (outcome,)

    def _snapshot(self, now, gesture="none", hand_present=False, error=""):
        preview_locked_position = None
        if self._locked_position is not None and self._last_frame_size is not None:
            try:
                preview_locked_position = self.pointer_mapper.unmap(
                    self._locked_position, self._last_frame_size, self.screen_bounds,
                )
            except Exception:
                pass  # Preview geometry cannot change native input semantics.
        return ControlSnapshot(
            timestamp=now, gesture=gesture,
            raw_gesture=getattr(self.classifier, "last_raw_gesture", "none"),
            session_state=self.control_session.state,
            pointer_state=self.action_machine.state,
            hand_present=hand_present, anchor=self.hud_anchor,
            locked_position=self._locked_position, outcomes=tuple(self._outcomes), error=error,
            preview_locked_position=preview_locked_position,
            pinch_phase=("cancelled" if self._joint_mapping_failed else
                         self._joint_evidence.phase if self._joint_evidence is not None else "idle"),
            pinch_reason=("pointer_history_unavailable" if self._joint_mapping_failed else
                          self._joint_evidence.reason if self._joint_evidence is not None else ""),
        )

    def step(self, observation: HandObservation) -> ControlSnapshot:
        """Consume one fresh frame through perception, arbitration and dispatch."""
        self._outcomes = []
        self._current_motion_pos = None
        now = observation.timestamp
        if not frame_is_fresh(now, self.clock()) or now <= self._last_frame_time:
            self._outcomes.extend(self.reset())
            return self._snapshot(self.clock(), error="invalid_frame_time")
        self._last_frame_time = now
        valid, landmarks = self._validate_landmarks(observation.landmarks)
        size = observation.frame_size
        if (not valid or not isinstance(size, (list, tuple)) or len(size) != 2
                or any(not isinstance(v, Real) or isinstance(v, bool)
                       or not isfinite(v) or v <= 0 for v in size)):
            self._outcomes.extend(self.reset())
            return self._snapshot(now, error="invalid_observation")
        if self._last_frame_size is not None and tuple(size) != self._last_frame_size:
            self._outcomes.extend(self.reset())
            return self._snapshot(now, error="frame_geometry_changed")
        guard = self.action_coordinator.input_guard
        if guard.observe_frame(now):
            self._outcomes.extend(self.reset())
            guard.observe_frame(now)
        self._last_frame_size = tuple(size)
        frame_shape = (size[1], size[0], 3)
        pos, detected = self.tracker.update(landmarks, frame_shape, timestamp=now)
        if not detected:
            self._outcomes.append(DispatchOutcome(
                ActionRequest("drag_end", core_pointer=True), self.action_coordinator.stop()
            ))
            self._reset_gesture_observation_state()
            self.action_machine.reset()
            self.tracker.reset()
            self.smoother.reset()
            self.classifier.reset_stabilization()
            self.hand_dynamics.reset()
            self.pinch_episodes.reset()
            self._locked_position = None
            self.hud_anchor = None
        hand_present = bool(landmarks) and detected
        if hand_present and not self._hand_present_last_frame:
            self._pointer_anchor_pending = True
        self._hand_present_last_frame = hand_present
        classified = self.classifier.classify(landmarks, timestamp=now)
        assessment = self.hand_dynamics.update(landmarks, now) if landmarks else None
        gesture = self._apply_dynamics(classified, assessment)
        allowed_before = self.control_session.allows_pointer_actions()
        self.control_session.update(
            gesture=gesture, has_hand=hand_present,
            shortcut_held=observation.shortcut_held, now=now, landmarks=landmarks,
        )
        if not allowed_before and self.control_session.allows_pointer_actions():
            self._pointer_anchor_pending = True
        if allowed_before and not self.control_session.allows_pointer_actions():
            if detected:
                self._outcomes.append(DispatchOutcome(
                    ActionRequest("drag_end", core_pointer=True), self.action_coordinator.stop()
                ))
            self.action_machine.reset()
            self.hand_dynamics.reset()
            self._reset_gesture_observation_state()
            self.pinch_episodes.reset()
            self._locked_position = None
        pinch_info = self.classifier.get_pinch_info(landmarks, timestamp=now)
        decision = self.intent_arbiter.update(
            gesture=gesture, pinch_info=pinch_info, pointer_state=self.action_machine.state,
            hand_present=hand_present, now=now,
        )
        # The observer owns both physical admission and the intended pointing
        # trajectory. Its candidate/cancel states reserve the pointer lane;
        # neither stale labels nor raw approach heuristics can override it.
        raw = getattr(self.classifier, "last_raw_gesture", gesture)
        self._joint_evidence = self.pinch_intent.update(
            landmarks, now=now,
            raw_pinching=bool(pinch_info and pinch_info.get("is_pinching")),
            pointing=raw == "point",
            competing_pose=raw in {"thumb_up", "thumb_down", "peace", "open_hand"},
            transition=bool(assessment and assessment.transition),
            pinch_confidence=assessment.pinch_confidence if assessment is not None else 0.0,
            enabled=hand_present and self.control_session.allows_pointer_actions(),
        )
        # Telemetry follows the same physical episode as dispatch. Stabilized
        # labels can otherwise close the log before a debounced release click.
        episode_gesture = ("pinch" if self._joint_evidence.phase in {"candidate", "confirmed"}
                           else "point" if self._joint_evidence.phase == "released" else "cancel")
        if episode_gesture == "pinch":
            self._observe_pinch_episode(episode_gesture, assessment, now)
        self._joint_landmarks = landmarks
        if self._joint_evidence.owns_pointer or self._joint_evidence.movement_allowed:
            decision = IntentDecision(IntentOwner.POINTER, "point", True, False, False)
            self._clear_dynamic_shortcut_observation()
            self.contextual_intent_controller.reset()
            self.scroll_intent_controller.reset()
        if not self._joint_evidence.owns_pointer:
            self._joint_target = self._joint_motion_anchor = None
            self._joint_mapping_failed = False
            self._joint_pointer_state = None
            self._joint_motion_history.clear()
        if pos is not None and detected:
            dynamic = self.config.get("dynamic_gestures") or {}
            anchor = self._map_pointer(pos, size) or (0, 0)
            if ((decision.allow_combo or decision.allow_dynamic)
                    and (self.config.get("context_aware") or {}).get("enabled", True)):
                # A one-shot combo or completed take must not be the first
                # asynchronous policy request. Warm the bounded context port
                # while observing its optional lane; unavailable results still
                # cannot authorize a command at the coordinator boundary.
                try:
                    self._cached_context(*anchor)
                except Exception:
                    pass
            observed, matched = self.observe_completed_dynamic_shortcut(
                landmarks, anchor, gesture=gesture, hand_present=hand_present, now=now,
                allowed=bool(decision.allow_dynamic and dynamic.get("enabled", False)
                             and self.dynamic_runtime_matcher is not None),
            )
            if not (matched or observed.recording or observed.completed_frames is not None
                    or observed.owns_frame):
                self.execute_action(gesture, pos, frame_shape, pinch_info,
                                    target_detected=detected, intent_decision=decision, timestamp=now,
                                    joint_evidence=self._joint_evidence)
        else:
            self.contextual_intent_controller.reset()
        if episode_gesture != "pinch":
            self._observe_pinch_episode(episode_gesture, assessment, now)
        if detected and self._current_motion_pos is not None:
            # Only a small, causal history of numeric filter state is retained.
            # No camera pixels are stored by the intent observer or this replay.
            self._pointer_history.append((now, *self._copy_pointer_state(
                self.tracker, self.smoother, self.pointer_mapper), self._current_motion_pos))
            while self._pointer_history and now - self._pointer_history[0][0] > 0.25:
                self._pointer_history.popleft()
        return self._snapshot(now, gesture, hand_present)

    def _dispatch(self, request, now, context=None):
        result = self.action_coordinator.dispatch(request)
        outcome = DispatchOutcome(request, result)
        self._outcomes.append(outcome)
        if result.executed:
            self._note_episode_action(request.action, now)
            if request.action in {"move_cursor", "drag", "drag_start", "left_click", "right_click"}:
                self._last_cursor_pos = (request.x, request.y)
        try:
            self._record_telemetry_action(
                action=request.action, executed=result.executed, gesture=request.gesture,
                context=context, x=request.x, y=request.y,
                latency_ms=max(0.0, (self.clock() - now) * 1000.0),
            )
        except Exception:
            pass  # Diagnostic failure must never strand native input.
        return result

    def _cached_context(self, x, y):
        # The broker owns freshness and position-bucket validation. A second
        # cache here could extend stale target evidence past its allowed age.
        return self.platform_services.context_provider.get_context(x, y)

    @staticmethod
    def _validate_landmarks(landmarks):
        """Return ``(valid, landmarks)`` for the strict 21-point runtime contract."""
        if landmarks is None:
            return True, None
        if not isinstance(landmarks, (list, tuple)):
            return False, None
        if not landmarks:
            return True, None
        if len(landmarks) != 21:
            return False, None
        for point in landmarks:
            if not isinstance(point, (list, tuple)) or len(point) != 3:
                return False, None
            if any(
                not isinstance(value, Real) or isinstance(value, bool) or not isfinite(value)
                for value in point
            ):
                return False, None
        return True, landmarks

    def _freeze_pointer_for_pinch(self, screen_x, screen_y, pinch_info):
        """Hold the pointer where the fingers actually closed.

        The pinch label needs about four frames to stabilise. Letting the pointer
        keep following the hand through that window added measured drift that
        grew with hand speed — 2 px at a slow pace, 20 px at 300 px/s, 40 px at
        600 px/s — which then had to be absorbed by snapping, and the click still
        landed away from where the pinch began. Freezing on the raw pinch frame
        makes the pointer and the click agree exactly.
        """
        if pinch_info and pinch_info.get("is_pinching"):
            if self._pinch_freeze_pos is None:
                self._pinch_freeze_pos = (screen_x, screen_y)
        else:
            self._pinch_freeze_pos = None
        return self._pinch_freeze_pos or (screen_x, screen_y)

    def _apply_dynamics(self, gesture, assessment):
        """Downgrade a pinch the hand is only passing through.

        A fist closes through the pinch shape; without this the click fires on
        the way to an exit gesture. The guard only acts while the state machine
        is still moving, so an in-flight click or drag is never disturbed.
        """
        if assessment is None or gesture not in ("pinch", "pinch_hold"):
            return gesture
        if (self.config.get("temporal") or {}).get("transition_guard", True) is not True:
            return gesture
        if self.action_machine.state is not ActionState.MOVING:
            return gesture
        if assessment.transition:
            return "point"
        if gesture == "pinch" and assessment.pinch_confidence < 0.45:
            return "point"
        return gesture

    def _observe_pinch_episode(self, gesture, assessment, now):
        """Fold one frame into the episode tracker and store what resolved.

        Recording is gated on telemetry: with the log off there is nowhere for a
        row to go, and the tracker's buffer would only grow for nothing.
        """
        store = getattr(self, "telemetry", None)
        tracker = getattr(self, "pinch_episodes", None)
        if tracker is None or store is None or not getattr(store, "enabled", False):
            return
        try:
            records = tracker.observe(gesture=gesture, assessment=assessment, now=now)
        except Exception:  # noqa: BLE001 - evidence collection is never the control path
            return
        model = getattr(self, "transition_model", None)
        for record in records:
            try:
                score = model.probability(record.features) if model is not None else None
            except Exception:  # noqa: BLE001
                score = None
            try:
                store.record_transition(
                    features=record.features,
                    label=record.label,
                    outcome=record.outcome,
                    rule_rejected=record.rule_rejected,
                    duration=record.duration,
                    model_score=score,
                )
            except Exception:  # noqa: BLE001
                continue

    def _note_episode_action(self, action, now):
        """Tell the tracker that a click or drag was actually dispatched."""
        tracker = getattr(self, "pinch_episodes", None)
        if tracker is None:
            return
        try:
            tracker.note_action(action, now)
        except Exception:  # noqa: BLE001
            pass

    def _record_telemetry_action(self, *, action, executed, gesture, context, x, y, latency_ms):
        """Log one dispatcher outcome. Never affects control flow."""
        store = getattr(self, "telemetry", None)
        if store is None:
            return
        store.record(
            "action",
            action=action,
            executed=executed,
            gesture=gesture,
            category=getattr(context, "category", "") or "",
            role=getattr(context, "native_role", "") or "",
            x=x,
            y=y,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _effective_assist_values(assist) -> tuple[float, float]:
        """Configured assist values, overridden by a learned step when present.

        Reading through this one function keeps the model, the diagnostics page
        and the tuner's own next input from disagreeing about what is in force.
        """
        learned = assist.get("learned")
        learned = learned if isinstance(learned, dict) else {}
        # A learned step is anchored to the values it started from. When the
        # user edits the configured numbers, their choice wins and the stale
        # adaptation is ignored instead of quietly overriding it.
        if learned and (
            learned.get("base_max_snap_distance") != assist.get("max_snap_distance")
            or learned.get("base_min_confidence") != assist.get("min_confidence")
        ):
            learned = {}

        def pick(key, default):
            for source in (learned, assist):
                raw = source.get(key)
                if raw is None or isinstance(raw, bool):
                    continue
                try:
                    number = float(raw)
                except (TypeError, ValueError):
                    continue
                if number != number or number in (float("inf"), float("-inf")):
                    continue
                return number
            return default

        return pick("max_snap_distance", 24.0), pick("min_confidence", 0.55)

    @staticmethod
    def _restore_static_templates(template_dicts):
        """Convert valid persisted custom-trigger dictionaries into runtime templates."""
        if not isinstance(template_dicts, list):
            return {}

        templates = {}
        for template_dict in template_dicts:
            if not isinstance(template_dict, dict):
                continue
            try:
                feature_vector = tuple(template_dict["feature_vector"])
                raw_threshold = template_dict.get("threshold", 0.18)
            except (KeyError, TypeError):
                continue
            if (
                len(feature_vector) != 63
                or not isinstance(raw_threshold, Real)
                or isinstance(raw_threshold, bool)
                or not all(
                    isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)
                    for value in feature_vector
                )
                or not isfinite(raw_threshold)
                or raw_threshold <= 0
            ):
                continue
            template = StaticGestureTemplate(
                template_id=str(template_dict.get("template_id", "")),
                name=str(template_dict.get("name", "")),
                feature_vector=tuple(float(value) for value in feature_vector),
                threshold=float(raw_threshold),
            )
            if template.template_id:
                templates[template.template_id] = template
        return templates

    def _restore_dynamic_templates(self, template_dicts):
        """Convert persisted, normalized dynamic shortcut records into runtime templates."""
        templates = []
        if not isinstance(template_dicts, list):
            return templates
        for item in template_dicts:
            if not isinstance(item, dict):
                continue
            try:
                samples = tuple(
                    tuple(tuple(frame) for frame in sample)
                    for sample in item["samples"]
                )
                templates.append(DynamicGestureTemplate(
                    template_id=item["template_id"],
                    name=item["name"],
                    action=item["action"],
                    samples=samples,
                    threshold=item["threshold"],
                    cooldown_seconds=item["cooldown_seconds"],
                    min_motion_energy=item["min_motion_energy"],
                    context_category=str(item.get("context_category", "")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return templates

    def _clear_dynamic_shortcut_observation(self):
        """Discard partial motion when its continuous hand tracking breaks."""
        lifecycle = getattr(self, "dynamic_intent_lifecycle", None)
        if lifecycle is not None:
            lifecycle.reset()
        frames = getattr(self, "dynamic_landmark_frames", None)
        if frames is not None:
            frames.clear()
        matcher = getattr(self, "dynamic_runtime_matcher", None)
        if matcher is not None and hasattr(matcher, "reset"):
            matcher.reset()

    def _reset_gesture_observation_state(self):
        """Clear optional command candidates at a safety boundary."""
        self.pinch_intent.reset()
        self._pointer_history.clear()
        self._joint_motion_history.clear()
        self._joint_evidence = None
        self._joint_target = self._joint_motion_anchor = None
        self._joint_mapping_failed = False
        self._joint_pointer_state = None
        self._joint_landmarks = None
        self._current_motion_pos = None
        self.contextual_intent_controller.reset()
        self.scroll_intent_controller.reset()
        self._clear_dynamic_shortcut_observation()
        combo_detector = getattr(self, "combo_detector", None)
        if combo_detector is not None:
            combo_detector.reset()
        arbiter = getattr(self, "intent_arbiter", None)
        if arbiter is not None:
            arbiter.reset()
        self._pinch_freeze_pos = None
        self._scroll_anchor = None
        self._context_cache = None
        self._pointer_anchor_pending = True
        self._last_cursor_pos = None
        self.last_stable_gesture = "none"
        self.last_gesture_change_time = None
        self.last_executed_gesture = "none"
        self.last_executed_action = "none"

    def observe_completed_dynamic_shortcut(
        self,
        landmarks,
        anchor,
        *,
        gesture,
        allowed: bool,
        hand_present: bool,
        now: float,
    ):
        """Match one complete, arbitrated dynamic gesture — never a live frame.

        The lifecycle is the sole owner of dynamic action boundaries. DTW sees
        a sample only after a neutral-delimited recording completes; the raw
        per-frame buffer remains available solely for compatibility helpers and
        focused tests.
        """
        observation = self.dynamic_intent_lifecycle.observe(
            gesture,
            landmarks,
            allowed=allowed,
            hand_present=hand_present,
            now=now,
        )
        if observation.completed_frames is None:
            if (allowed and hand_present and landmarks and gesture == "none"
                    and observation.state is DynamicIntentState.ARMED
                    and self.dynamic_runtime_matcher is not None):
                # DTW receives completed takes only. The lifecycle's observed
                # neutral boundary rearms the one-shot gate and keeps cooldown.
                rearm = getattr(self.dynamic_runtime_matcher, "rearm", None)
                if rearm is not None:
                    rearm()
            return observation, False
        completed_frames = observation.completed_frames
        self.dynamic_landmark_frames.clear()
        self.dynamic_landmark_frames.extend(completed_frames)
        matched = self._dispatch_completed_dynamic_shortcut(
            completed_frames, anchor, now=now
        )
        # Completed samples must never spill into the next recording, including
        # when DTW rejects them. The live frame path only matches at this
        # lifecycle boundary, not against a rolling cross-action window.
        self.dynamic_landmark_frames.clear()
        return observation, matched

    def _refresh_dynamic_shortcuts_from_config(self):
        """Restore user-recorded motion shortcuts after a successful Settings save."""
        self._clear_dynamic_shortcut_observation()
        dynamic = self.config.get("dynamic_gestures") or {}
        defaults = dynamic.get("defaults") or {}
        self.dynamic_intent_lifecycle = DynamicIntentLifecycle(
            neutral_rearm_frames=defaults.get("neutral_rearm_frames", 3),
            end_neutral_frames=defaults.get("end_neutral_frames", 2),
            max_recording_frames=defaults.get("max_recording_frames", 180),
            max_duration_seconds=defaults.get("max_duration_seconds", 3.0),
        )
        self.dynamic_landmark_frames = deque(
            maxlen=self.dynamic_intent_lifecycle.max_recording_frames
        )
        self.dynamic_templates = []
        self.dynamic_runtime_matcher = None
        if not dynamic.get("enabled", True):
            return
        self.dynamic_templates = self._restore_dynamic_templates(dynamic.get("templates") or [])
        if self.dynamic_templates:
            matcher = DynamicGestureMatcher()
            self.dynamic_runtime_matcher = matcher.create_runtime_matcher(self.dynamic_templates)

    def _refresh_pointer_assist(self):
        """Rebuild the aiming assist and attach it to the lock transition.

        Assist runs only when a target locks, never while the pointer moves, so
        the deterministic pointer lane keeps full authority over every frame.
        """
        assist = self.config.get("pointer_assist") or {}
        distance, confidence = self._effective_assist_values(assist)
        try:
            model = TargetModel(
                max_snap_distance=distance,
                min_confidence=confidence,
                search_radius=float(assist.get("search_radius", 120.0)),
            )
        except (TypeError, ValueError):
            model = TargetModel()
        if assist.get("enabled", True) is not True:
            self.target_model = None
            self.ranker = None
            self.assist_mode = "bayesian"
            self.action_machine.snap_provider = None
            return
        self.target_model = model
        self.assist_mode = assist.get("mode", "bayesian")
        model_path = assist.get("model_path") or os.path.join(
            os.path.dirname(os.path.abspath(self.config.get("_config_path", "settings.json"))), "target_ranker.json"
        )
        self.ranker = (
            LinearRanker.load(model_path) if self.assist_mode in ("shadow", "ranker") else None
        )
        if self.assist_mode in ("shadow", "ranker") and self.ranker is None:
            # A missing or invalid model must not silently disable clicking;
            # fall back to the deterministic policy.
            self.assist_mode = "bayesian"
        self.action_machine.snap_provider = self._snap_cursor_position

    def _refresh_transition_model(self):
        """Load the shadow boundary if one exists; it never decides anything.

        The model only contributes a score to each recorded episode. Promotion
        to acting on it is a separate, reversible step, and it needs held-out
        evidence that the model beats the rule first.
        """
        temporal = self.config.get("temporal") or {}
        path = temporal.get("transition_model") or os.path.join(
            os.path.dirname(os.path.abspath(self.config.get("_config_path", "settings.json"))),
            "transition_model.json",
        )
        try:
            self.transition_model = TransitionModel.load(path)
        except Exception:  # noqa: BLE001 - a bad model file is not a startup failure
            self.transition_model = None

    def _snap_cursor_position(self, pos):
        """Return the assisted lock position for one raw pointer position."""
        model = getattr(self, "target_model", None)
        if model is None or pos is None:
            return None
        probe = getattr(self.platform_services.context_provider, "probe_targets", None)
        if probe is None:
            return None
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, IndexError, ValueError):
            return None
        # Probing matters only inside the distance the cursor may actually
        # travel, so the pattern covers that disc instead of a wide annulus
        # whose candidates could never be snapped to.
        radius = int(max(24.0, min(60.0, model.max_snap_distance)))
        try:
            contexts = probe(x, y, radius)
        except Exception:  # noqa: BLE001 - assist must never break the click lane
            return None
        targets = []
        for context in contexts:
            bounds = getattr(context, "bounds", None)
            if bounds is None:
                continue
            targets.append(
                Target(
                    target_id=f"{context.native_role}:{bounds}",
                    bounds=bounds,
                    role=context.native_role,
                    enabled=getattr(context, "is_enabled", True),
                )
            )
        decision = model.choose(x, y, targets)

        # Posteriors are shared by logging, the learned ranker, and the
        # deterministic choice, so no two consumers disagree about the numbers.
        posteriors = {target.target_id: value for target, value in model.posteriors(x, y, targets)}

        store = getattr(self, "telemetry", None)
        if store is not None and targets:
            self._record_candidates(store, x, y, targets, posteriors, decision)

        ranker = getattr(self, "ranker", None)
        if ranker is not None and targets:
            ranker_decision = None
            try:
                ranker_decision = ranker.choose(
                (x, y),
                (self.screen_bounds.x, self.screen_bounds.y,
                 self.screen_bounds.width, self.screen_bounds.height),
                targets,
                posteriors,
                    min_confidence=model.min_confidence,
                    max_snap_distance=model.max_snap_distance,
                )
            except Exception:  # noqa: BLE001 - a model must never break the click lane
                ranker_decision = None
            if self.assist_mode == "shadow" and store is not None:
                store.record(
                    "shadow",
                    action=(ranker_decision.target_id if ranker_decision else "")[:64],
                    confidence=(ranker_decision.confidence if ranker_decision else 0.0),
                    category=("agrees" if ranker_decision and decision
                              and ranker_decision.target_id == decision.target_id else "differs"),
                )
            elif self.assist_mode == "ranker" and ranker_decision is not None:
                decision = ranker_decision

        if decision is None:
            return None
        if store is not None:
            chosen = next((t for t in targets if t.target_id == decision.target_id), None)
            categories = {
                f"{c.native_role}:{c.bounds}": c.category for c in contexts if c.bounds
            }
            store.record(
                "assist",
                category=categories.get(decision.target_id, ""),
                role=chosen.role if chosen is not None else "",
                confidence=decision.confidence,
                snap_distance=((decision.x - x) ** 2 + (decision.y - y) ** 2) ** 0.5,
                x=decision.x,
                y=decision.y,
            )
        return (decision.x, decision.y)

    def _record_candidates(self, store, x, y, targets, posteriors, decision):
        """Log every candidate with the features the ranker would consume."""
        screen = (self.screen_bounds.x, self.screen_bounds.y,
                  self.screen_bounds.width, self.screen_bounds.height)
        rows = build_features((x, y), screen, targets, posteriors)
        chosen_bayes = decision.target_id if decision is not None else ""
        raw_hits = [t for t in targets if _point_inside(x, y, t.bounds)]
        chosen_raw = raw_hits[0].target_id if len(raw_hits) == 1 else ""
        payload = []
        for target, row in zip(targets, rows):
            bx, by, bw, bh = target.bounds
            centre_x, centre_y = bx + bw / 2.0, by + bh / 2.0
            payload.append({
                "role": target.role,
                "x": bx, "y": by, "w": bw, "h": bh,
                "dist": ((x - centre_x) ** 2 + (y - centre_y) ** 2) ** 0.5,
                "inside": target.target_id in {t.target_id for t in raw_hits},
                "bayes": posteriors.get(target.target_id, 0.0),
                "features": row,
                "chosen_bayes": target.target_id == chosen_bayes,
                "chosen_raw": target.target_id == chosen_raw,
            })
        store.record_candidates(f"{int(self.clock() * 1000)}-{x}-{y}", payload)

    def _refresh_control_session_from_config(self, session_cfg=None):
        """Rebuild the live control gate from the currently saved session settings."""
        session_cfg = session_cfg if session_cfg is not None else (self.config.get("control_session") or {})
        self.static_gesture_matcher = StaticGestureMatcher()
        self.custom_static_templates = self._restore_static_templates(
            session_cfg.get("custom_static_templates") or []
        )
        self.control_session = ControlSession(
            mode=ActivationMode(session_cfg.get("mode", "gesture")),
            activation_gesture=session_cfg.get("activation_gesture", "open_hand"),
            exit_gesture=session_cfg.get("exit_gesture", "fist"),
            stability_seconds=session_cfg.get("stability_seconds", 0.3),
            no_hand_timeout_seconds=session_cfg.get("no_hand_timeout_seconds", 2.0),
            activation_template=self.custom_static_templates.get(
                session_cfg.get("activation_template_id", "")
            ),
            exit_template=self.custom_static_templates.get(
                session_cfg.get("exit_template_id", "")
            ),
            matcher=self.static_gesture_matcher,
        )

    def _dispatch_completed_dynamic_shortcut(self, completed_frames, anchor, *, now):
        dynamic = self.config.get("dynamic_gestures") or {}
        if (self.dynamic_runtime_matcher is None or not dynamic.get("enabled", False)
                or not self.control_session.allows_pointer_actions()
                or self.action_machine.state is not ActionState.MOVING):
            return False
        category = ""
        if any(template.context_category for template in self.dynamic_templates):
            try:
                category = self._cached_context(*anchor).category
            except Exception:
                pass
        template = self.dynamic_runtime_matcher.ingest(
            tuple(completed_frames), active=True, now=now, context_category=category,
        )
        if template is None:
            return False
        record = next((item for item in dynamic.get("templates", [])
                       if item.get("template_id") == template.template_id), {})
        x, y = self.screen_bounds.clamp(*anchor)
        result = self._dispatch(ActionRequest(
            action=template.action, x=x, y=y, hotkey=record.get("hotkey", ""),
            gesture="dynamic_shortcut",
        ), now)
        if result.executed:
            self.intent_arbiter.mark_shortcut_committed()
        return result.executed

    @staticmethod
    def _copy_pointer_state(tracker, smoother, mapper):
        # Only filter state is forked. Clock services must retain identity,
        # including clocks held by the nested one-euro filters.
        memo = {}
        for component in (tracker, smoother, getattr(smoother, "filter_x", None),
                          getattr(smoother, "filter_y", None)):
            clock = getattr(component, "_clock", None)
            if clock is not None:
                memo[id(clock)] = clock
        return deepcopy((tracker, smoother, mapper), memo)

    def _reconstruct_pinch_pointer(self, evidence, frame_shape):
        """Replay a bounded clean trajectory from the last trusted open pose.

        Replay runs on a separate numeric branch: it must never rewind the
        visible pointer's tracker, mapper or filter. The branch removes curl
        from the target and drag channel without replaying native events.
        """
        reference = next((item for item in reversed(self._pointer_history)
                          if item[0] == evidence.reference_at), None)
        if reference is None:
            self._joint_mapping_failed = True
            return None
        at, tracker, smoother, mapper, motion = reference
        tracker, smoother, mapper = self._copy_pointer_state(tracker, smoother, mapper)
        self._joint_motion_history.clear()
        self._joint_motion_history.append((at, motion))
        target = motion if at == evidence.target_at else None
        for sample_at, camera_pos in evidence.corrections:
            if sample_at <= at:
                continue
            tracked, _ = tracker.update(self._joint_landmarks, frame_shape,
                                        timestamp=sample_at, position=camera_pos)
            mapped = mapper.map(tracked, (frame_shape[1], frame_shape[0]), self.screen_bounds)
            if mapped is None:
                self._joint_mapping_failed = True
                return None
            motion = self.screen_bounds.clamp_float(*smoother.smooth(*mapped, timestamp=sample_at))
            self._joint_motion_history.append((sample_at, motion))
            if sample_at == evidence.target_at:
                target = motion
        if target is None:
            self._joint_mapping_failed = True
            return None
        self._joint_pointer_state = (tracker, smoother, mapper)
        self._joint_target = target
        self._joint_motion_anchor = None
        return motion

    def _advance_pinch_pointer(self, evidence, frame_shape, now):
        """Advance only the hidden palm-transported motion branch."""
        if self._joint_mapping_failed:
            return None
        if evidence.new_episode:
            return self._reconstruct_pinch_pointer(evidence, frame_shape)
        if self._joint_pointer_state is None or evidence.motion_position is None:
            self._joint_mapping_failed = True
            return None
        tracker, smoother, mapper = self._joint_pointer_state
        tracked, detected = tracker.update(
            self._joint_landmarks, frame_shape, timestamp=now,
            position=evidence.motion_position,
        )
        mapped = mapper.map(tracked, (frame_shape[1], frame_shape[0]), self.screen_bounds) if detected else None
        if mapped is None:
            self._joint_mapping_failed = True
            return None
        return self.screen_bounds.clamp_float(*smoother.smooth(*mapped, timestamp=now))

    def _pinch_action_evidence(self, evidence, now, motion):
        if evidence is None:
            return None
        if evidence.phase in {"candidate", "confirmed", "released"} and motion is not None:
            self._joint_motion_history.append((now, motion))
            if evidence.closed_at is not None:
                # Gradual closing can include real palm travel. Only movement
                # since physical closure counts towards starting a drag.
                anchor = next((point for at, point in self._joint_motion_history
                               if at == evidence.closed_at), None)
                if anchor is not None:
                    self._joint_motion_anchor = anchor
                elif self._joint_motion_anchor is None:
                    self._joint_mapping_failed = True
        phase = "cancelled" if self._joint_mapping_failed else evidence.phase
        return PinchActionEvidence(phase, self._joint_target, self._joint_motion_anchor,
                                   evidence.closed_at, evidence.opened_at, evidence.new_episode,
                                   evidence.movement_allowed)

    def execute_action(self, gesture, pos, frame_shape, pinch_info=None,
                       target_detected=True, intent_decision: IntentDecision | None = None,
                       timestamp=None, joint_evidence: PinchEvidence | None = None
                       ) -> tuple[DispatchOutcome, ...]:
        """Dispatch already-arbitrated evidence; useful for deterministic replay.

        Runtime observations always enter through step. This lower-level helper
        requires a live session and freshness lease just like the live path.
        """
        initial = len(self._outcomes)
        now = self.clock() if timestamp is None else timestamp
        self._locked_position = None
        if not self.control_session.allows_pointer_actions():
            self.action_machine.reset()
            self.contextual_intent_controller.reset()
            return ()
        # Neutral and disabled bindings still end the prior one-shot gesture.
        # Observe transitions before any no-op/optional-lane early return.
        if gesture != self.last_stable_gesture:
            self.last_gesture_change_time = now
            self.last_stable_gesture = gesture
            self.last_executed_gesture = self.last_executed_action = "none"
        h, w = frame_shape[:2]
        self._last_frame_size = (w, h)
        raw = getattr(self.classifier, "last_raw_gesture", gesture)
        joint_owns = joint_evidence is not None and joint_evidence.owns_pointer
        scroll_pose = not joint_owns and (
            gesture in {"thumb_up", "thumb_down"} or raw in {"thumb_up", "thumb_down"})
        if self._scroll_anchor is not None and (
                not scroll_pose or self.action_machine.state is not ActionState.MOVING):
            self._scroll_anchor = None
            self.smoother.reset()
            self._pointer_anchor_pending = True
        # The visible branch keeps its uninterrupted raw pointing history.
        # Candidate admission may reconstruct a target, but cannot install that
        # older filter state into this branch or lock the native cursor.
        mapped = self._map_pointer(pos, (w, h))
        if mapped is None:
            return ()
        x, y = self.smoother.smooth(*mapped, timestamp=now)
        x, y = self.screen_bounds.clamp_float(x, y)
        self._current_motion_pos = (x, y)
        joint_motion = (x, y)
        if joint_owns and joint_evidence.phase in {"candidate", "confirmed", "released"}:
            joint_motion = self._advance_pinch_pointer(joint_evidence, frame_shape, now)
        elif joint_evidence is not None and joint_evidence.phase == "cancelled":
            self._joint_pointer_state = None
        action_evidence = self._pinch_action_evidence(joint_evidence, now, joint_motion)
        if (joint_evidence is not None and joint_evidence.phase in {"confirmed", "released"}
                and not self._joint_mapping_failed and self._joint_pointer_state is not None):
            # Once confirmed, discard closure-induced filter drift. Subsequent
            # open references (including rapid double clicks) must inherit the
            # clean motion, not the curled fingertip's filter tail. Copy so the
            # next raw observation cannot mutate the hidden branch in place.
            self.tracker, self.smoother, self.pointer_mapper = self._copy_pointer_state(
                *self._joint_pointer_state,
            )
            x, y = joint_motion
            self._current_motion_pos = joint_motion
        if self.action_machine.state is ActionState.MOVING and scroll_pose:
            if self._scroll_anchor is None:
                self._scroll_anchor = self._last_cursor_pos or (x, y)
        if self._scroll_anchor is not None:
            x, y = self._scroll_anchor
        self.hud_anchor = (x, y)
        # Warm the bounded broker while pointing. A lock transition then scores
        # its fresh cached targets without starting a native lookup inline.
        probe = getattr(self.platform_services.context_provider, "probe_targets", None)
        if self.target_model is not None and probe is not None:
            try:
                radius = int(max(24.0, min(60.0, self.target_model.max_snap_distance)))
                probe_pos = (self._joint_target if joint_owns and not self._joint_mapping_failed
                             and self._joint_target is not None else (x, y))
                probe(int(probe_pos[0]), int(probe_pos[1]), radius)
            except Exception:
                pass
        speed = (self.config.get("global_sensitivity") or {}).get("scroll_speed", 50)
        hotkey = self._get_gesture(gesture).get("hotkey", "")
        pointer_events = {"point", "pinch", "pinch_hold", "release", "cancel"}
        pointer_gesture = gesture
        allow_combo = allow_optional = allow_contextual = True
        if intent_decision is not None:
            pointer_gesture = (intent_decision.effective_pointer_gesture
                               if intent_decision.allow_pointer else None)
            allow_combo = allow_optional = intent_decision.allow_combo
            allow_contextual = intent_decision.allow_contextual or intent_decision.allow_combo
        if self.pointer_scroll_enabled:
            scroll_allowed = not joint_owns and self.action_machine.state is ActionState.MOVING and (
                intent_decision is None or intent_decision.allow_pointer
                or intent_decision.allow_contextual
            )
            scroll_intent = self.scroll_intent_controller.update(
                gesture=gesture, raw_gesture=raw, anchor=(x, y),
                allowed=scroll_allowed, now=now,
            )
            # A thumb pose has exclusive ownership through entry, repeat and
            # exit debounce. A raw release stops wheel events immediately.
            if scroll_pose and scroll_allowed:
                self.combo_detector.reset()
                self._pinch_freeze_pos = None
                if scroll_intent is not None:
                    exec_x, exec_y = self.screen_bounds.clamp(*scroll_intent.anchor)
                    self._dispatch(ActionRequest(
                        action=scroll_intent.action, x=exec_x, y=exec_y,
                        scroll_amount=speed, gesture=gesture, core_pointer=True,
                    ), now)
                return tuple(self._outcomes[initial:])
        if not allow_combo:
            self.combo_detector.reset()
        elif gesture not in pointer_events and gesture != "none":
            combo = self.combo_detector.update(gesture, timestamp=now)
            if combo:
                exec_x, exec_y = self.screen_bounds.clamp(x, y)
                result = self._dispatch(ActionRequest(
                    action=combo["action"], x=exec_x, y=exec_y, scroll_amount=speed,
                    hotkey=combo.get("hotkey", "") or hotkey, gesture=gesture,
                ), now)
                if result.executed and intent_decision is not None:
                    self.intent_arbiter.mark_shortcut_committed()
                return tuple(self._outcomes[initial:])
        pointer_pos = ((x, y) if joint_evidence is not None
                       else self._freeze_pointer_for_pinch(x, y, pinch_info))
        if pointer_gesture in pointer_events:
            result = self.action_machine.update(
                pointer_gesture, pointer_pos, pinch_info, timestamp=now,
                motion_pos=joint_motion if joint_motion is not None else (x, y),
                pinch_evidence=action_evidence,
            )
            action = result['action']
            exec_x, exec_y = result['pos'] or (x, y)
            if result.get('is_locked') or self.action_machine.state is ActionState.CLICKING:
                self._locked_position = (exec_x, exec_y)
            dispatch_gesture = pointer_gesture
        else:
            action = self._get_gesture_action(gesture) if allow_optional else "none"
            exec_x, exec_y = x, y
            dispatch_gesture = gesture
        context, target_id = None, ""
        context_cfg = self.config.get("context_aware") or {}
        if ((allow_contextual or (gesture == "point" and self.action_machine.state is ActionState.MOVING))
                and not self.pointer_scroll_enabled
                and target_detected and context_cfg.get("enabled", True)
                and context_cfg.get("intent_actions_enabled", True)):
            try:
                context = self._cached_context(x, y)
                intent = self.contextual_intent_controller.observe(context, gesture=gesture, now=now)
                if (allow_contextual and intent is not None and gesture not in pointer_events
                        and not intent.requires_confirmation):
                    action, target_id = intent.action, context.target_id
            except Exception:
                context = None
                self.contextual_intent_controller.reset()
        if action in {None, "", "none"}:
            return ()
        continuous = {"move_cursor", "drag", "drag_start", "drag_end",
                      "scroll_up", "scroll_down", "scroll_left", "scroll_right"}
        one_shot = action not in continuous and dispatch_gesture not in pointer_events
        if one_shot:
            if (self.last_gesture_change_time is not None
                    and now - self.last_gesture_change_time < self.gesture_grace_period):
                return ()
            if gesture == self.last_executed_gesture and action == self.last_executed_action:
                return ()
        else:
            self.last_executed_gesture = self.last_executed_action = "none"
        exec_x, exec_y = self.screen_bounds.clamp(exec_x, exec_y)
        result = self._dispatch(ActionRequest(
            action=action, x=exec_x, y=exec_y, scroll_amount=speed, hotkey=hotkey,
            gesture=dispatch_gesture, core_pointer=dispatch_gesture in pointer_events,
            contextual=bool(target_id), expected_target_id=target_id,
        ), now, context)
        # A blocked attempt is evidence of failure, never a successful one-shot.
        if one_shot and result.executed:
            self.last_executed_gesture, self.last_executed_action = gesture, action
        return tuple(self._outcomes[initial:])

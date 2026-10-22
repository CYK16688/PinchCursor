"""主窗口 - PySide6 GUI"""

import cv2
import os
import platform
import time
from collections import deque
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QApplication, QPushButton, QLabel, QFrame, QSizePolicy, QStackedLayout
)
from PySide6.QtCore import QSize, Qt, QTimer, QRect, QRectF
from PySide6.QtGui import QCursor, QImage, QPixmap, QPainter

from core.base_detector import BaseHandDetector
from core.detector_factory import create_detector
from core.gesture_classifier import GestureClassifier
from core.action_coordinator import GestureActionCoordinator
from core.action_state_machine import ActionState, ActionStateMachine
from core.assist.features import build_features
from core.adaptive_tuning import tune_snapping
from core.transition_episodes import PinchEpisodeTracker
from core.transition_model import TransitionModel
from core.assist.ranker import LinearRanker
from core.assist.target_model import Target, TargetModel
from core.hand_dynamics import HandDynamics
from core.performance import preset_for
from core.pointer_mapping import AbsoluteMapper, RelativeMapper, ScreenBounds
from core.telemetry import TelemetryStore, default_path
from core.combo_detector import ComboDetector
from core.intent_arbiter import IntentArbiter, IntentDecision

from core.control_session import ActivationMode, ControlSession, SessionState
from core.mediapipe_worker import LandmarkFrame, MediaPipeVideoWorker
from core.static_gesture_template import StaticGestureMatcher, StaticGestureTemplate
from core.dynamic_gesture_template import DynamicGestureMatcher, DynamicGestureTemplate
from core.dynamic_intent_lifecycle import DynamicIntentLifecycle
from core.contextual_intent import ContextualIntentController
from platform_services.camera_selection import open_configured_camera
from platform_services.contracts import ActionRequest
from platform_services.factory import create_platform_services
from platform_services.policy import ContextPolicy
from utils.camera_utils import open_camera
from utils.smoothing import CursorSmoother
from utils.tracker import TargetTracker
from utils.config_manager import ConfigManager
from gui import icons
from gui.theme import DARK_THEME, use_styled_background
from gui.overlay import GestureOverlay
from gui.summary_row import SummaryRow
from gui.hud_state import HudController, HudState
from gui.i18n import set_locale, tr


@dataclass(frozen=True)
class ControlButtonModel:
    label: str
    intent: str
    semantic_state: str


@dataclass(frozen=True)
class ControlSessionStatusModel:
    label: str
    semantic_state: str


def control_button_model(is_running, permissions, camera_promptable=True):
    if is_running:
        return ControlButtonModel(tr("main.stop"), "stop", "danger")
    if permissions.camera.value != "granted":
        # A denied camera can only be fixed in system settings, and a
        # not-determined one only by a prompt the platform can actually raise.
        # Windows has no such prompt, so offering "Grant camera access" there
        # would be a button that cannot do what it says.
        if permissions.camera.value == "denied" or camera_promptable:
            return ControlButtonModel(tr("main.grant_camera"), "request_camera", "warning")
    if permissions.accessibility.value != "granted":
        return ControlButtonModel(tr("main.grant_accessibility"), "request_accessibility", "warning")
    return ControlButtonModel(tr("main.start"), "start", "ready")


def _point_inside(x, y, bounds):
    """True when a screen point falls inside a target rectangle."""
    bx, by, bw, bh = bounds
    return bx <= x <= bx + bw and by <= y <= by + bh


def control_session_status_model(is_running, state, activation_gesture, ready=True):
    """Return user-facing guidance for the session gate before input dispatch.

    ``ready`` is false when a permission still blocks starting. Saying "Ready"
    next to a denial is the one contradiction this screen must not carry.
    """
    if not is_running:
        if not ready:
            return ControlSessionStatusModel(tr("main.needs_permission"), "waiting")
        return ControlSessionStatusModel(tr("main.ready"), "idle")
    if state is SessionState.POINTER:
        return ControlSessionStatusModel(tr("session.active"), "active")
    if state is SessionState.ARMED:
        return ControlSessionStatusModel(tr("session.armed"), "armed")
    if activation_gesture == "open_hand":
        return ControlSessionStatusModel(tr("session.wait_open_hand"), "waiting")
    gesture_labels = {
        "point": "gesture.point",
        "pinch": "gesture.pinch",
        "pinch_hold": "gesture.pinch_hold",
        "peace": "gesture.peace",
        "thumb_up": "gesture.thumb_up",
        "thumb_down": "gesture.thumb_down",
        "open_hand": "gesture.open_hand",
        "fist": "gesture.fist",
        "ok": "gesture.ok",
        "rock": "gesture.rock",
        "three": "gesture.three",
        "ilove_you": "gesture.ilove_you",
    }
    return ControlSessionStatusModel(
        tr("session.wait_gesture", gesture=tr(gesture_labels.get(activation_gesture, "gesture.unavailable"))),
        "waiting",
    )


class MainWindow(QMainWindow):
    """主窗口"""

    _GESTURE_LABEL_KEYS = {
        "point": "gesture.point",
        "pinch": "gesture.pinch",
        "pinch_hold": "gesture.pinch_hold",
        "peace": "gesture.peace",
        "thumb_up": "gesture.thumb_up",
        "thumb_down": "gesture.thumb_down",
        "open_hand": "gesture.open_hand",
        "fist": "gesture.fist",
        "ok": "gesture.ok",
        "rock": "gesture.rock",
        "three": "gesture.three",
        "ilove_you": "gesture.ilove_you",
    }
    _POWER_STATUS_KEYS = {
        "deep_sleep": "main.status.deep_sleep_ir",
        "sleep": "main.status.sleep",
        "low": "main.status.low_power",
    }
    _ACTION_ERROR_KEYS = {
        "accessibility_permission_required": "main.control_unavailable",
        "missing_hotkey": "main.control_unavailable",
        "invalid_hotkey": "main.control_unavailable",
        "unsupported_action": "main.control_unavailable",
        "context_target_unavailable": "main.control_unavailable",
        "context_target_changed": "main.control_unavailable",
        "gesture_blocked": "main.control_unavailable",
        "action_blocked": "main.control_unavailable",
        "missing_coordinates": "main.control_unavailable",
        "drag_not_started": "main.control_unavailable",
        "no_action": "main.control_unavailable",
    }
    _STATUS_OVERRIDE_KEYS = {
        "main.selected_camera_unavailable": "main.selected_camera_unavailable",
        "main.camera_permission_denied": "main.camera_permission_denied",
        "main.camera_open_failed": "main.camera_open_failed",
        "main.hold_shortcut_unavailable": "main.hold_shortcut_unavailable",
        "main.starting_camera": "main.starting_camera",
    }

    @classmethod
    def _gesture_status_label(cls, gesture_id):
        return tr(cls._GESTURE_LABEL_KEYS.get(gesture_id, "gesture.unavailable"))

    @classmethod
    def _status_override_label(cls, key):
        return tr(cls._STATUS_OVERRIDE_KEYS.get(key, "main.control_unavailable"))

    def __init__(self):
        super().__init__()
        # Without this the window never paints the stylesheet canvas and the
        # light Fusion palette shows through every gap between cards.
        use_styled_background(self)
        self.config = ConfigManager()
        # Presentation locale is restored before any user-visible widgets are created.
        set_locale(self.config.get("ui", "language"))
        self.init_components()
        self.init_ui()
        self.init_camera()

    def _cache_cameras(self):
        """在启动时缓存摄像头列表，避免后续检测冲突"""
        from gui.settings_dialog import SettingsDialog
        from utils.camera_utils import detect_cameras
        if SettingsDialog._cached_cameras is None:
            SettingsDialog._cached_cameras = detect_cameras()

    def init_components(self):
        """初始化核心组件"""
        det_conf = self.config.get("detection", "confidence")
        track_conf = self.config.get("detection", "tracking_confidence")
        detector_type = self.config.get("detection", "detector_type") or "mediapipe"

        self.detector_type = detector_type
        self.detection_confidence = det_conf
        self.tracking_confidence = track_conf
        self.detector = None
        self.video_worker = None
        self.classifier = GestureClassifier()
        self.platform_services = self._create_platform_services_from_config()
        self.action_coordinator = GestureActionCoordinator(self.platform_services)
        self.target_model = None
        self.ranker = None
        self.assist_mode = "bayesian"
        self.telemetry = None
        # Turn each pinch into one labelled episode, when telemetry is on.
        self.pinch_episodes = PinchEpisodeTracker()
        # Every display is addressable, not just the primary one: the union is
        # what both mapping strategies clamp against.
        self.screen_bounds = self._compute_screen_bounds()
        self.screen_w, self.screen_h = self.screen_bounds.width, self.screen_bounds.height
        self.pointer_mapper = AbsoluteMapper()
        self._pointer_anchor_pending = True

        self.smoother = CursorSmoother()

        self.tracker = TargetTracker()

        # 上下文感知由当前平台服务处理；共享默认规则定义在
        # platform_services.policy，避免在 macOS 导入 Windows API。

        # 初始化动作状态机
        self.preset = preset_for("standard")
        self.action_machine = ActionStateMachine()
        self._refresh_runtime_configuration()
        self.intent_arbiter = IntentArbiter()
        self.dynamic_intent_lifecycle = DynamicIntentLifecycle()
        self.contextual_intent_controller = ContextualIntentController()

        self._hold_shortcut_error_key = ""
        # Stable presentation keys keep actionable failures visible across normal
        # console refreshes without exposing worker or camera diagnostics.
        self._status_override_key = ""
        session_cfg = self.config.get("control_session") or {}
        self._refresh_control_session_from_config(session_cfg)
        self._refresh_dynamic_shortcuts_from_config()

        # 初始化组合检测器
        self.combo_detector = ComboDetector()
        combos = self.config.get("gesture_combos") or []
        self.combo_detector.set_combos(combos)


        self.is_running = False

        # Pointer-adjacent feedback HUD.
        self.overlay = GestureOverlay()
        if platform.system() == "Darwin":
            try:
                from platform_services.macos.native import MacOSNativeFacade

                self.overlay.enable_macos_global_panel(MacOSNativeFacade())
            except Exception:
                # Preserve portable Qt HUD behavior if native panel setup is unavailable.
                pass
        feedback = self.config.get("feedback") or {}
        self.hud = HudController(mode=feedback.get("mode", "standard"))
        self.overlay.set_feedback_preferences(
            opacity=feedback.get("opacity", 0.92),
            scale=feedback.get("scale", 1.0),
        )
        self.hud_anchor = None
        self.hud_timer = QTimer(self)
        self.hud_timer.setInterval(50)
        self.hud_timer.timeout.connect(self._render_hud)
        self.hud_timer.start()

        # 一次性动作防重复执行
        self.last_executed_action = "none"
        self.last_executed_gesture = "none"

        # 手势过渡稳定期 - 防止手势形成过程中的中间状态触发动作
        self.last_gesture_change_time = None  # 上次手势变化时间
        self.last_stable_gesture = "none"     # 上一个稳定手势
        self.gesture_grace_period = 0.2       # 手势变化后的等待时间(秒)

        # 节能模式参数
        self.no_hand_frames = 0  # 连续无手帧数
        self.power_mode = "normal"  # normal, low, sleep, deep_sleep
        self.NORMAL_INTERVAL = 16  # ~60fps
        self.LOW_INTERVAL = 66     # ~15fps
        self.SLEEP_INTERVAL = 200  # ~5fps
        self.DEEP_SLEEP_INTERVAL = 500  # ~2fps (仅红外检测)
        self.LOW_THRESHOLD = 30    # 30帧无手进入低功耗
        self.SLEEP_THRESHOLD = 150 # 150帧无手进入休眠
        self.DEEP_SLEEP_THRESHOLD = 300  # 300帧无手进入深度休眠

        # 红外人体检测器
        self.ir_detector = None

        # 边缘丢失提示
        self.edge_lost_time = None  # 边缘丢失时间
        self.edge_lost_position = None  # 丢失的具体位置
        self.edge_lost_direction = (0, 0)  # 丢失方向
        self.was_hand_detected = False  # 上一帧是否检测到手
        self.EDGE_HINT_DURATION = 1.5  # 提示显示时长(秒)

    def _refresh_runtime_configuration(self):
        """Apply saved runtime policy to the live deterministic control lane."""
        detection = self.config.get("detection") or {}
        self.detector_type = "mediapipe"
        self.detection_confidence = detection.get("confidence", 0.7)
        self.tracking_confidence = detection.get("tracking_confidence", 0.5)

        self.preset = preset_for((self.config.get("performance") or {}).get("mode"))
        self.PREVIEW_FPS = self.preset.preview_fps
        if self.preset.is_performance:
            # The profile is the authority on its own numbers; the standard
            # profile leaves the user's configured values alone.
            self.detection_confidence = self.preset.detection_confidence
            self.tracking_confidence = self.preset.tracking_confidence

        sensitivity = self.config.get("global_sensitivity") or {}
        self.smoother = CursorSmoother(
            mincutoff=self.preset.smoothing_mincutoff,
            beta=sensitivity.get("smoothing", 0.005),
        )

        pinch_cfg = self.config.get_gesture("pinch")
        # A calibration (ratios of pinch distance to palm scale) survives
        # resolution and camera-distance changes; the legacy pixel threshold
        # only does at the resolution it was tuned for.
        calibration = self.config.get("pinch_calibration") or {}
        calibrated = False
        if isinstance(calibration, dict) and "enter_ratio" in calibration:
            try:
                self.classifier.set_pinch_calibration(
                    float(calibration["enter_ratio"]),
                    float(calibration["exit_ratio"]),
                )
                calibrated = True
            except (KeyError, TypeError, ValueError):
                calibrated = False
        if not calibrated:
            self.classifier.pinch_threshold = pinch_cfg.get("threshold", 35)
        hold_cfg = self.config.get_gesture("pinch_hold")
        self.classifier.hold_threshold = hold_cfg.get("hold_time", 0.3)
        stabilization = self.config.get("stabilization") or {}
        self.classifier.confirm_threshold = stabilization.get("confirm_threshold", 3)
        self.classifier.min_switch_interval = stabilization.get("min_switch_interval", 0.15)
        self.classifier.exit_threshold = stabilization.get("exit_threshold", 4)
        self.classifier.cooldown_time = stabilization.get("cooldown_time", 0.2)

        self.hand_dynamics = HandDynamics(
            enter_ratio=self.classifier.pinch_enter_ratio,
            exit_ratio=self.classifier.pinch_exit_ratio,
        )

        action_cfg = self.config.get("action_mode") or {}
        self.action_machine.dwell_threshold = action_cfg.get("dwell_threshold", 0.3)
        self.action_machine.move_threshold = action_cfg.get("move_threshold", 8)
        self.action_machine.drag_threshold = action_cfg.get("drag_threshold", 0.3)
        self.action_machine.set_zone_rules(self.config.get("zone_rules") or [])
        self._refresh_pointer_mapping()
        self._refresh_pointer_assist()
        self._refresh_telemetry()
        self._apply_adaptive_tuning()
        self._refresh_transition_model()

    @staticmethod
    def _compute_screen_bounds() -> ScreenBounds:
        """Return the union of every attached display, in screen points."""
        union = QRect()
        for screen in QApplication.screens():
            union = union.united(screen.geometry())
        if union.isNull():
            union = QApplication.primaryScreen().geometry()
        return ScreenBounds(union.x(), union.y(), union.width(), union.height())

    def _refresh_pointer_mapping(self):
        """Rebuild the hand-to-screen strategy from configuration."""
        mapping = self.config.get("pointer_mapping") or {}
        mode = mapping.get("mode", "absolute")
        try:
            gain = float(mapping.get("gain", 2.0))
            mapper = RelativeMapper(gain) if mode == "relative" else AbsoluteMapper()
        except (TypeError, ValueError):
            mapper = AbsoluteMapper()
        self.screen_bounds = self._compute_screen_bounds()
        self.screen_w, self.screen_h = self.screen_bounds.width, self.screen_bounds.height
        self.pointer_mapper = mapper
        self._pointer_anchor_pending = True

    def _map_pointer(self, pos, frame_size):
        """Map one hand position to screen points, anchoring relative mode."""
        pending = getattr(self, "_pointer_anchor_pending", False)
        if pending and isinstance(self.pointer_mapper, RelativeMapper):
            # Anchor on the cursor this app last drove, not on a native
            # round-trip that may still be a frame behind.
            cursor = getattr(self, "_last_cursor_pos", None) or (QCursor.pos().x(), QCursor.pos().y())
            self.pointer_mapper.begin(pos, frame_size, self.screen_bounds, cursor=cursor)
        self._pointer_anchor_pending = False
        mapped = self.pointer_mapper.map(pos, frame_size, self.screen_bounds)
        if mapped is not None:
            self._last_cursor_pos = mapped
        return mapped

    def _refresh_telemetry(self):
        """Rebuild the local event log; disabled means it never opens a file."""
        telemetry_cfg = self.config.get("telemetry") or {}
        enabled = telemetry_cfg.get("enabled", False) is True
        path = telemetry_cfg.get("path") or default_path(self.config.config_path)
        if self.telemetry is not None and getattr(self.telemetry, "path", None) == path:
            self.telemetry.set_enabled(enabled)
            return
        if self.telemetry is not None:
            self.telemetry.close()
        self.telemetry = TelemetryStore(path, enabled=enabled)

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

    def _cached_context(self, x, y):
        """Return the AX context, reusing the last hit for a few frames.

        An accessibility hit test costs ~2 ms, which is a meaningful share of a
        33 ms frame. Context only gates optional commands, so a short-lived,
        position-bucketed cache is enough; the cache is dropped as soon as the
        pointer moves more than a bucket.
        """
        cache = getattr(self, "_context_cache", None)
        if cache is not None:
            cached_x, cached_y, cached_at, cached = cache
            if (
                abs(x - cached_x) <= 16
                and abs(y - cached_y) <= 16
                and time.monotonic() - cached_at <= 0.12
            ):
                return cached
        context = self.platform_services.context_provider.get_context(x, y)
        self._context_cache = (x, y, time.monotonic(), context)
        return context

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
            os.path.dirname(os.path.abspath(self.config.config_path)), "target_ranker.json"
        )
        self.ranker = (
            LinearRanker.load(model_path) if self.assist_mode in ("shadow", "ranker") else None
        )
        if self.assist_mode in ("shadow", "ranker") and self.ranker is None:
            # A missing or invalid model must not silently disable clicking;
            # fall back to the deterministic policy.
            self.assist_mode = "bayesian"
        self.action_machine.snap_provider = self._snap_cursor_position

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

    def _apply_adaptive_tuning(self):
        """Move the aim assist one bounded step from local click outcomes.

        Runs once per launch, and only when telemetry is on and the assist is
        enabled: without recorded outcomes there is no evidence, and adapting on
        no evidence is how a product starts guessing. The decision is persisted
        so the same summary cannot ratchet the values on every restart.
        """
        import time

        store = getattr(self, "telemetry", None)
        if store is None or not getattr(store, "enabled", False):
            return None
        assist = self.config.get("pointer_assist") or {}
        if assist.get("enabled", True) is not True:
            return None
        try:
            summary = store.summary()
        except Exception:  # noqa: BLE001 - tuning must never block startup
            return None

        actions = summary.get("actions") or {}
        clicks = sum(
            int(actions.get(name, 0) or 0)
            for name in ("left_click", "right_click", "double_click")
        )
        learned = assist.get("learned")
        learned = learned if isinstance(learned, dict) else {}
        if (
            learned.get("base_max_snap_distance") == assist.get("max_snap_distance")
            and learned.get("base_min_confidence") == assist.get("min_confidence")
        ):
            # The summary is cumulative. Re-deciding on evidence that already
            # produced a decision would ratchet the same bad afternoon tighter
            # at every launch; only new clicks may move the values.
            try:
                last_clicks = int(learned.get("clicks") or 0)
            except (TypeError, ValueError):
                last_clicks = 0
            if clicks <= last_clicks:
                return None
        distance, confidence = self._effective_assist_values(assist)
        tuning = tune_snapping(
            max_snap_distance=distance,
            min_confidence=confidence,
            clicks=clicks,
            misses=summary.get("click_misses", 0),
            snaps=summary.get("snaps", 0),
            mean_snap_distance=summary.get("mean_snap_distance"),
        )

        if tuning.changed:
            payload = {
                "max_snap_distance": tuning.max_snap_distance,
                "min_confidence": tuning.min_confidence,
                "base_max_snap_distance": assist.get("max_snap_distance", 24.0),
                "base_min_confidence": assist.get("min_confidence", 0.55),
                "clicks": tuning.clicks,
                "misses": tuning.misses,
                "reason": tuning.reason,
                "updated_at": time.time(),
            }
            try:
                self.config.set("pointer_assist", "learned", payload)
                self.config.save()
            except OSError:
                # A read-only config directory is not a reason to fail a launch.
                return tuning
            self._refresh_pointer_assist()
        if tuning.clicks >= 40 or tuning.changed:
            try:
                store.record(
                    "tune",
                    action=tuning.reason,
                    confidence=tuning.min_confidence,
                    snap_distance=tuning.max_snap_distance,
                )
            except Exception:  # noqa: BLE001 - the log is not the control path
                pass
        return tuning

    def _refresh_transition_model(self):
        """Load the shadow boundary if one exists; it never decides anything.

        The model only contributes a score to each recorded episode. Promotion
        to acting on it is a separate, reversible step, and it needs held-out
        evidence that the model beats the rule first.
        """
        temporal = self.config.get("temporal") or {}
        path = temporal.get("transition_model") or os.path.join(
            os.path.dirname(os.path.abspath(self.config.config_path)),
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
        store.record_candidates(f"{int(time.monotonic() * 1000)}-{x}-{y}", payload)

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

    def _refresh_control_session_from_config(self, session_cfg=None):
        """Rebuild the live control gate from the currently saved session settings."""
        session_cfg = session_cfg if session_cfg is not None else (self.config.get("control_session") or {})
        monitor = getattr(self.platform_services, "hold_shortcut_monitor", None)
        if monitor is not None:
            monitor.stop()
            monitor.configure(session_cfg.get("hold_shortcut", ""))
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

    def _dispatch_completed_dynamic_shortcut(self, completed_frames, anchor, *, now):
        """Match and dispatch one lifecycle-completed optional semantic motion."""
        dynamic = self.config.get("dynamic_gestures") or {}
        if (
            self.dynamic_runtime_matcher is None
            or not dynamic.get("enabled", False)
            or not self.control_session.allows_pointer_actions()
            or self.action_machine.state.value in {"locking", "clicking", "dragging"}
        ):
            return False
        # Only pay for an accessibility lookup when a template is actually
        # bound to a context.
        context_category = ""
        if any(getattr(t, "context_category", "") for t in self.dynamic_templates):
            try:
                context_category = self.platform_services.context_provider.get_context(
                    anchor[0], anchor[1]
                ).category
            except Exception:  # noqa: BLE001 - an unbound motion still matches
                context_category = ""
        template = self.dynamic_runtime_matcher.ingest(
            tuple(completed_frames), active=True, now=now, context_category=context_category
        )
        if template is None:
            return False
        record = next(
            (item for item in dynamic.get("templates", []) if item.get("template_id") == template.template_id),
            {},
        )
        # A recorded motion is an optional global semantic shortcut, not an AX
        # target action. It remains session-gated and policy-gated by the
        # coordinator, but does not invent an accessibility identity boundary.
        result = self.action_coordinator.dispatch(ActionRequest(
            action=template.action,
            x=anchor[0],
            y=anchor[1],
            hotkey=record.get("hotkey", ""),
            gesture="dynamic_shortcut",
        ))
        self._update_hud_after_dispatch(template.action, result, anchor)
        if result.executed:
            self.intent_arbiter.mark_shortcut_committed()
        return result.executed

    def dispatch_recorded_dynamic_shortcut(self, anchor, *, now):
        """Deprecated compatibility entry point; raw recordings never dispatch."""
        del anchor, now
        return False

    def observe_recorded_dynamic_shortcut(self, landmarks, anchor, *, now):
        """Deprecated compatibility entry point; dynamic frames need a lifecycle boundary."""
        del landmarks, anchor, now
        return False

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
        self.contextual_intent_controller.reset()
        self._clear_dynamic_shortcut_observation()
        combo_detector = getattr(self, "combo_detector", None)
        if combo_detector is not None:
            combo_detector.reset()
        arbiter = getattr(self, "intent_arbiter", None)
        if arbiter is not None:
            arbiter.reset()

    def init_ui(self):
        """Initialize the Precision Desk operational console."""
        # 640px preview + session panel must fit without squeezing either at the
        # documented desktop minimum size.
        self.setMinimumSize(1200, 640)
        # Combo popup views are top-level native windows on macOS, so a window-
        # local stylesheet leaves their unselected rows to the system palette.
        # Install the single app theme instead so every interactive popup uses
        # the same readable dark surface as the console and Settings dialog.
        QApplication.instance().setStyleSheet(DARK_THEME)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.app_mark_label = QLabel()
        self.app_mark_label.setPixmap(icons.app_mark(30))
        self.app_mark_label.setFixedSize(30, 30)
        self.app_title_label = QLabel()
        self.app_title_label.setObjectName("appTitle")
        title_layout = QHBoxLayout()
        title_layout.setSpacing(10)
        title_layout.addWidget(self.app_mark_label)
        title_layout.addWidget(self.app_title_label)
        self.status_chip = QLabel()
        self.status_chip.setObjectName("statusChip")
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("quietButton")
        self.settings_btn.setIcon(icons.icon("gear", "#C6CBD5", 15))
        self.settings_btn.setIconSize(QSize(15, 15))
        self.settings_btn.clicked.connect(lambda _checked=False: self.open_settings())
        header.addLayout(title_layout)
        header.addStretch()
        header.addWidget(self.status_chip)
        header.addWidget(self.settings_btn)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(20)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(12)
        self.preview_title = QLabel()
        self.preview_title.setObjectName("eyebrow")
        preview_layout.addWidget(self.preview_title)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 400)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setObjectName("videoViewport")
        self.preview_stack = QStackedLayout()
        self.preview_stack.addWidget(self.video_label)
        self.preview_stack.addWidget(self._build_preview_placeholder())
        preview_holder = QWidget()
        preview_holder.setLayout(self.preview_stack)
        preview_layout.addWidget(preview_holder, 1)
        self.gesture_label = QLabel()
        self.gesture_label.setObjectName("previewStatus")
        preview_layout.addWidget(self.gesture_label)
        content.addWidget(preview_frame, 3)

        self.session_card = QFrame()
        self.session_card.setObjectName("sessionCard")
        session_layout = QVBoxLayout(self.session_card)
        session_layout.setContentsMargins(20, 18, 20, 18)
        session_layout.setSpacing(14)
        self.session_title = QLabel()
        self.session_title.setObjectName("eyebrow")
        session_layout.addWidget(self.session_title)
        self.status_indicator = QLabel()
        self.status_indicator.setObjectName("sessionState")
        session_layout.addWidget(self.status_indicator)

        self.activation_summary = QLabel()
        self.camera_summary = QLabel()
        self.summary_heading_labels = {}
        self.summary_rows = {}
        for key, name, value, section_id, glyph in (
            ("main.activation", "activation", self.activation_summary, "control", "bolt"),
            ("main.camera", "camera", self.camera_summary, "camera", "camera"),
        ):
            row, row_layout = self._build_summary_row(key, section_id, glyph)
            value.setObjectName("summaryValue")
            value.setWordWrap(True)
            row_layout.addWidget(value)
            self.summary_rows[name] = row
            session_layout.addWidget(row)

        # Permissions are two independent facts, and they only belong on this
        # screen when one of them is blocking. Two "granted" lines are noise for
        # an operator who just needs to press Start.
        self.permission_rows = {}
        self.permission_row, permission_layout = self._build_summary_row(
            "main.permissions", "permissions", "shield"
        )
        self.permission_row.setVisible(False)
        self.summary_rows["permissions"] = self.permission_row
        for permission_key in ("camera", "accessibility"):
            permission_line = QHBoxLayout()
            permission_line.setSpacing(8)
            dot = QLabel()
            dot.setObjectName("statusDot")
            name = QLabel()
            name.setObjectName("permissionName")
            value = QLabel()
            value.setObjectName("permissionValue")
            permission_line.addWidget(dot)
            permission_line.addWidget(name)
            permission_line.addStretch()
            permission_line.addWidget(value)
            permission_layout.addLayout(permission_line)
            self.permission_rows[permission_key] = (dot, name, value)
        session_layout.addWidget(self.permission_row)

        # The last-action answer only exists once something has run. Showing an
        # empty block at idle spends a fifth of the card on "nothing yet".
        self.last_action_block = QFrame()
        self.last_action_block.setObjectName("lastActionBlock")
        last_action_layout = QVBoxLayout(self.last_action_block)
        last_action_layout.setContentsMargins(0, 0, 0, 0)
        last_action_layout.setSpacing(12)
        divider = QFrame()
        divider.setObjectName("hairline")
        divider.setFrameShape(QFrame.NoFrame)
        last_action_layout.addWidget(divider)
        last_action_heading_row = QHBoxLayout()
        last_action_heading_row.setSpacing(6)
        last_action_heading_row.addWidget(self._heading_icon("history"))
        self.last_action_heading = QLabel()
        self.last_action_heading.setObjectName("summaryLabel")
        self._last_action_key = ""
        self.last_action_value = QLabel(tr("main.last_action.none"))
        self.last_action_value.setObjectName("lastActionValue")
        self.last_action_value.setWordWrap(True)
        last_action_heading_row.addWidget(self.last_action_heading)
        last_action_heading_row.addStretch()
        last_action_layout.addLayout(last_action_heading_row)
        last_action_layout.addWidget(self.last_action_value)
        self.last_action_block.setVisible(False)
        session_layout.addWidget(self.last_action_block)

        self.primary_control_button = QPushButton()
        self.primary_control_button.setObjectName("primaryControlButton")
        self.primary_control_button.setMinimumHeight(52)
        self.primary_control_button.clicked.connect(self._perform_primary_action)
        session_layout.addWidget(self.primary_control_button)
        right_column = QVBoxLayout()
        right_column.addWidget(self.session_card)
        right_column.addStretch()
        content.addLayout(right_column, 2)
        layout.addLayout(content, 1)
        self.retranslate_ui()

    def _build_summary_row(self, key, section_id, glyph):
        """One session fact, clickable anywhere to edit it in Settings."""
        row = SummaryRow()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 5, 0, 5)
        row_layout.setSpacing(6)
        heading_row = QHBoxLayout()
        heading_row.setSpacing(6)
        heading_row.addWidget(self._heading_icon(glyph))
        heading = QLabel()
        heading.setObjectName("summaryLabel")
        self.summary_heading_labels[key] = heading
        heading_row.addWidget(heading)
        heading_row.addStretch()
        chevron = QLabel()
        chevron.setPixmap(icons.pixmap("chevron_right", "#8B93A1", 13))
        chevron.setFixedSize(13, 13)
        heading_row.addWidget(chevron)
        row_layout.addLayout(heading_row)
        row.clicked.connect(lambda _=None, target=section_id: self.open_settings(target))
        return row, row_layout

    @staticmethod
    def _heading_icon(name: str) -> QLabel:
        """A muted glyph that identifies a summary block before its label is read."""
        label = QLabel()
        label.setPixmap(icons.pixmap(name, "#A8AFBC", 15))
        label.setFixedSize(15, 15)
        return label

    def _build_preview_placeholder(self):
        """Idle state for the camera well.

        A large black rectangle with one centred line reads as a broken preview.
        A dimmed hand glyph plus an explanation tells the operator what the area
        is for before any camera exists.
        """
        holder = QWidget()
        holder.setObjectName("previewPlaceholder")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addStretch()

        self.preview_placeholder_icon = QLabel()
        self.preview_placeholder_icon.setAlignment(Qt.AlignCenter)
        pixmap = self._placeholder_pixmap()
        if pixmap is not None:
            self.preview_placeholder_icon.setPixmap(pixmap)

        self.preview_placeholder_title = QLabel()
        self.preview_placeholder_title.setObjectName("placeholderTitle")
        self.preview_placeholder_title.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.preview_placeholder_icon)
        layout.addWidget(self.preview_placeholder_title)
        layout.addStretch()
        return holder

    @staticmethod
    def _placeholder_pixmap(size=72, color="#39404E"):
        """Render the idle hand glyph from the project's SVG icon set."""
        from gui.gesture_icons_svg import GestureIconsSVG

        renderer = GestureIconsSVG.get_renderer("open_hand", color)
        if renderer is None:
            return None
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        return pixmap

    def _set_preview_placeholder(self, visible):
        self.preview_stack.setCurrentIndex(1 if visible else 0)

    def retranslate_ui(self):
        """Refresh static presentation copy without rebuilding control runtime state."""
        self.setWindowTitle(tr("main.title"))
        self.app_title_label.setText(tr("main.title"))
        self.settings_btn.setText(tr("main.settings"))
        self.preview_title.setText(tr("main.live_camera"))
        self.preview_placeholder_title.setText(tr("main.preview_waiting"))
        if not self.video_label.pixmap():
            self.video_label.setText(tr("main.preview_waiting"))
        self.gesture_label.setText(
            tr("main.no_hand") if self.is_running else tr("main.preview_idle")
        )
        self.session_title.setText(tr("main.control_session"))
        for key, label in self.summary_heading_labels.items():
            label.setText(tr(key))
        for permission_key, name_key in (
            ("camera", "permission.name.camera"),
            ("accessibility", "permission.name.accessibility"),
        ):
            self.permission_rows[permission_key][1].setText(tr(name_key))
        self.last_action_heading.setText(tr("main.last_action"))
        self._refresh_last_action()
        self.overlay.retranslate_ui()
        self._refresh_permission_status()
        self._refresh_precision_console()

    def init_camera(self):
        """摄像头仅在用户显式启动控制后由 VIDEO worker 打开。"""
        self._position_overlay()

    def _start_video_worker(self):
        """Start capture/model initialization in the worker, never the UI thread."""
        if self.video_worker and self.video_worker.isRunning():
            return True
        self._last_worker_timestamp_ms = float("-inf")
        self._last_frame_time = float("-inf")
        camera_config = self.config.get("camera") or {}
        cam_id = camera_config.get("id", 0)
        if self.preset.is_performance:
            # The profile owns capture size: finer landmarks are the point.
            w, h = self.preset.camera_width, self.preset.camera_height
        else:
            w = camera_config.get("width", 640)
            h = camera_config.get("height", 480)
        self.video_worker = MediaPipeVideoWorker(
            camera_id=cam_id,
            width=w,
            height=h,
            detector_factory=lambda: create_detector(
                self.detector_type,
                self.detection_confidence,
                self.tracking_confidence,
                delegate=self.preset.delegate,
            ),
            capture_opener=lambda: open_configured_camera(
                camera_config,
                self.platform_services.camera_service,
                legacy_open=open_camera,
            ),
            parent=self,
        )
        self.video_worker.landmark_frame_ready.connect(self.process_frame)
        self.video_worker.worker_ready.connect(self._on_worker_ready)
        self.video_worker.worker_error.connect(self._on_worker_error)
        self.video_worker.start()
        return True

    def _on_worker_ready(self):
        """Update UI only after the worker owns an opened selected camera."""
        if not self.is_running:
            return
        self._status_override_key = ""
        self._refresh_precision_console()

    def _stop_video_worker(self):
        if self.video_worker:
            self.video_worker.stop()
            self.video_worker.wait(2000)
            self.video_worker.deleteLater()
            self.video_worker = None
        if self.detector:
            self.detector.release()
        self.detector = None
        self._last_worker_timestamp_ms = float("-inf")
        self._last_frame_time = float("-inf")

    def _on_worker_error(self, message):
        self.is_running = False
        self._stop_hold_shortcut_monitor()
        self.control_session.reset()
        self.action_machine.reset()
        self._reset_gesture_observation_state()
        self.action_coordinator.stop()
        self.hud.hide_persistent()
        self.overlay.hide_feedback()
        selected_device_id = (self.config.get("camera") or {}).get("device_id", "")
        # Worker diagnostics must not become arbitrary translated or persisted UI
        # content. The user sees a stable, repairable camera state instead.
        self._status_override_key = (
            "main.selected_camera_unavailable"
            if message == "Unable to open selected camera" and selected_device_id
            else "main.camera_open_failed"
        )
        self._refresh_precision_console()

    _PERMISSION_LABEL_KEYS = {
        "granted": "permission.granted",
        "denied": "permission.denied",
        "not_determined": "permission.not_determined",
        "unavailable": "permission.unavailable",
    }

    @classmethod
    def _permission_state_text(cls, state):
        value = getattr(state, "value", state)
        return tr(cls._PERMISSION_LABEL_KEYS.get(value, "permission.unavailable"))

    # AuthorizationState -> the dot/value semantics the theme defines.
    _PERMISSION_SEMANTICS = {
        "granted": ("granted", ""),
        "denied": ("denied", "denied"),
        "not_determined": ("pending", "pending"),
    }

    def _refresh_permission_status(self):
        permissions = self.platform_services.permission_provider.snapshot()
        blocked = False
        for key, state in (
            ("camera", permissions.camera),
            ("accessibility", permissions.accessibility),
        ):
            dot, _name, value = self.permission_rows[key]
            raw = getattr(state, "value", state)
            blocked = blocked or raw != "granted"
            dot_semantic, value_semantic = self._PERMISSION_SEMANTICS.get(raw, ("", ""))
            dot.setProperty("semantic", dot_semantic)
            value.setProperty("semantic", value_semantic)
            value.setText(self._permission_state_text(state))
            for widget in (dot, value):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        # Nothing to fix, nothing to show: the badge and the button already say
        # the app is ready.
        self.permission_row.setVisible(blocked)

    def _refresh_precision_console(self):
        permissions = self.platform_services.permission_provider.snapshot()
        # The camera well shows either live frames or the idle explanation —
        # never a stale black rectangle claiming a preview exists.
        self._set_preview_placeholder(not self.is_running)
        model = control_button_model(
            self.is_running,
            permissions,
            self.platform_services.capabilities.camera_permission_promptable,
        )
        self.primary_control_button.setText(model.label)
        glyph = {
            "start": "play",
            "stop": "stop",
            "request_camera": "shield",
            "request_accessibility": "shield",
        }.get(model.intent)
        if glyph is not None:
            self.primary_control_button.setIcon(icons.icon(glyph, "#FFFFFF", 16))
            self.primary_control_button.setIconSize(QSize(16, 16))
        self.primary_control_button.setProperty("semantic", model.semantic_state)
        self.primary_control_button.style().unpolish(self.primary_control_button)
        self.primary_control_button.style().polish(self.primary_control_button)
        # The chip reports state, never the primary action: repeating the button
        # label here made two controls on one screen claim to be the same thing.
        if self.is_running:
            chip_text, chip_semantic = tr("main.running"), "running"
        elif self._status_override_key or self._hold_shortcut_error_key:
            chip_text, chip_semantic = tr("main.control_unavailable"), "danger"
        elif self._start_blocked_by_permissions():
            chip_text, chip_semantic = tr("main.needs_permission"), "waiting"
        else:
            chip_text, chip_semantic = tr("main.ready"), ""
        self.status_chip.setText(chip_text)
        self.status_chip.setProperty("semantic", chip_semantic)
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)
        self.activation_summary.setText(self._activation_summary_text())
        devices = self.platform_services.camera_service.list_devices()
        selected_id = (self.config.get("camera") or {}).get("device_id", "")
        selected = next((device for device in devices if device.device_id == selected_id), None)
        self.camera_summary.setText(
            selected.display_name if selected else tr("main.select_camera_settings")
        )
        self._refresh_control_session_status()

    def _refresh_last_action(self):
        """Show the last deliberate action, or a quiet empty state.

        This is the main-window answer to "what did my last gesture do?" — the
        HUD shows it too, but a transient chip near the pointer is not something
        the user can consult after the fact.
        """
        if self._last_action_key:
            self.last_action_value.setText(tr(self._last_action_key))
            semantic = "recent"
        else:
            self.last_action_value.setText(tr("main.last_action.none"))
            semantic = ""
        self.last_action_block.setVisible(bool(self._last_action_key))
        self.last_action_value.setProperty("semantic", semantic)
        self.last_action_value.style().unpolish(self.last_action_value)
        self.last_action_value.style().polish(self.last_action_value)

    # Lanes that fire continuously would rewrite this row every frame and make it
    # unreadable; only deliberate, discrete actions are worth remembering.
    _CONTINUOUS_ACTIONS = frozenset({"move_cursor", "drag", "none", ""})

    def _record_last_action(self, action):
        """Remember one executed action for the session card."""
        if not action or action in self._CONTINUOUS_ACTIONS:
            return
        key = f"gesture.action.{action}"
        # Only promise a label the catalogue actually has, so an unknown action
        # renders the generic fallback instead of a raw identifier.
        self._last_action_key = key if tr(key) != key else "gesture.action.unavailable"
        self._refresh_last_action()

    def _activation_summary_text(self):
        """Describe the live activation policy in the user's language.

        Building this from raw enum values leaked "Gesture · open_hand" into a
        Chinese UI, so every part goes through the catalogue with a safe
        fallback for values the catalogue does not know.
        """
        mode_keys = {
            "gesture": "settings.control.mode.gesture",
            "hold_shortcut": "settings.control.mode.hold_shortcut",
            "gesture_or_shortcut": "settings.control.mode.gesture_or_shortcut",
            "always": "settings.control.mode.always",
        }
        mode_key = mode_keys.get(self.control_session.mode.value)
        mode_text = tr(mode_key) if mode_key else tr("gesture.unavailable")

        template = self.control_session.activation_template
        if template is not None:
            detail = tr(
                "settings.control.custom_trigger.option",
                template_name=template.name or tr("settings.control.custom_trigger.title"),
            )
        else:
            label_key = self._GESTURE_LABEL_KEYS.get(self.control_session.activation_gesture)
            detail = tr(label_key) if label_key else tr("gesture.unavailable")
        return f"{mode_text} · {detail}"

    def _start_blocked_by_permissions(self) -> bool:
        """True when a missing permission (not the user) prevents starting."""
        permissions = self.platform_services.permission_provider.snapshot()
        return (
            permissions.camera.value != "granted"
            or permissions.accessibility.value != "granted"
        )

    def _refresh_control_session_status(self):
        if self._status_override_key:
            self.status_indicator.setText(f"● {self._status_override_label(self._status_override_key)}")
            semantic_state = "danger"
        elif self._hold_shortcut_error_key:
            self.status_indicator.setText(self._status_override_label(self._hold_shortcut_error_key))
            semantic_state = "danger"
        else:
            status = control_session_status_model(
                self.is_running,
                self.control_session.state,
                self.control_session.activation_gesture,
                ready=not self._start_blocked_by_permissions(),
            )
            self.status_indicator.setText(status.label)
            semantic_state = status.semantic_state
        self.status_indicator.setProperty("semantic", semantic_state)
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)

    def _perform_primary_action(self):
        model = control_button_model(
            self.is_running,
            self.platform_services.permission_provider.snapshot(),
            self.platform_services.capabilities.camera_permission_promptable,
        )
        if model.intent == "request_accessibility":
            self.request_accessibility_permission()
        elif model.intent == "request_camera":
            self.request_camera_permission_and_start()
        else:
            self.toggle_running()

    def _create_platform_services_from_config(self):
        """Create services with the policy persisted by the most recent Settings Save."""
        policy = ContextPolicy.from_config(self.config.get("context_aware") or {})
        return create_platform_services(context_policy=policy)

    def _refresh_platform_services(self):
        self._stop_hold_shortcut_monitor()
        self.platform_services = self._create_platform_services_from_config()
        self.action_coordinator = GestureActionCoordinator(self.platform_services)
        self._refresh_control_session_from_config()
        self._refresh_permission_status()
        self._refresh_precision_console()

    def request_accessibility_permission(self):
        """Only an explicit user click may open the macOS Accessibility prompt."""
        self.platform_services.permission_provider.request_accessibility_prompt()
        self._refresh_platform_services()

    def request_input_monitoring_permission(self):
        """Only an explicit user click may open the macOS Input Monitoring prompt."""
        self.platform_services.permission_provider.request_input_monitoring_prompt()
        self._refresh_platform_services()

    def request_camera_permission_and_start(self):
        """Request camera TCC access on the Qt main thread before worker startup."""
        self.platform_services.permission_provider.request_camera_access(
            self._on_camera_permission_result
        )

    def request_camera_permission(self):
        """Request Camera access from Settings without starting pointer control."""
        self.platform_services.permission_provider.request_camera_access(
            lambda _granted: self._refresh_platform_services()
        )

    def _on_camera_permission_result(self, granted):
        if not granted:
            self.is_running = False
            self._reset_gesture_observation_state()
            self._status_override_key = "main.camera_permission_denied"
            self._refresh_precision_console()
            return
        self._start_after_camera_permission()

    def _start_after_camera_permission(self):
        self._status_override_key = ""
        self._hold_shortcut_error_key = ""
        if not self._start_video_worker():
            self.is_running = False
            self.control_session.reset()
            self.action_machine.reset()
            self._reset_gesture_observation_state()
            self.action_coordinator.stop()
            self.hud.hide_persistent()
            self.overlay.hide_feedback()
            selected_device_id = (self.config.get("camera") or {}).get("device_id", "")
            self._status_override_key = (
                "main.selected_camera_unavailable"
                if selected_device_id
                else "main.camera_open_failed"
            )
            self._refresh_precision_console()
            return
        if not self._start_hold_shortcut_monitor():
            self.is_running = False
            self._stop_video_worker()
            self._reset_gesture_observation_state()
            self.action_coordinator.stop()
            self._hold_shortcut_error_key = "main.hold_shortcut_unavailable"
            self._refresh_precision_console()
            return
        self._status_override_key = "main.starting_camera"
        self._refresh_precision_console()

    def _start_hold_shortcut_monitor(self):
        monitor = getattr(self.platform_services, "hold_shortcut_monitor", None)
        if not (
            self.control_session.mode
            in {ActivationMode.HOLD_SHORTCUT, ActivationMode.GESTURE_OR_SHORTCUT}
            and bool(self.config.get("control_session", "hold_shortcut"))
        ):
            return True
        if monitor is None:
            return False
        if not monitor.configure(self.config.get("control_session", "hold_shortcut")):
            return False
        return monitor.start()

    def _stop_hold_shortcut_monitor(self):
        monitor = getattr(self.platform_services, "hold_shortcut_monitor", None)
        if monitor is not None:
            monitor.stop()

    def _is_hold_shortcut_held(self) -> bool:
        monitor = getattr(self.platform_services, "hold_shortcut_monitor", None)
        return bool(monitor and monitor.is_held())

    def _position_overlay(self):
        """将悬浮窗定位到屏幕中央"""
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.overlay.width()) // 2
        y = (screen.height() - self.overlay.height()) // 2
        self.overlay.move(x, y)

    def _init_ir_detector(self):
        """初始化红外人体检测器"""
        import platform

        if platform.system() != "Windows":
            return
        from utils.camera_utils import detect_cameras, find_ir_camera, IRPresenceDetector

        cameras = detect_cameras()
        ir_cam_id = find_ir_camera(cameras)

        if ir_cam_id is not None:
            # 确保红外摄像头不是当前使用的RGB摄像头
            rgb_cam_id = self.config.get("camera", "id")
            if ir_cam_id != rgb_cam_id:
                self.ir_detector = IRPresenceDetector(ir_cam_id)

    def toggle_running(self):
        """切换运行状态"""
        self.is_running = not self.is_running
        if self.is_running:
            self._refresh_platform_services()
            camera_state = self.platform_services.permission_provider.snapshot().camera
            if camera_state.value == "not_determined":
                self.request_camera_permission_and_start()
                return
            if camera_state.value != "granted":
                self.is_running = False
                self._status_override_key = "main.camera_permission_denied"
                self._refresh_precision_console()
                return
            self._start_after_camera_permission()
            if self.ir_detector is None:
                self._init_ir_detector()
            # 启动红外检测器
            if self.ir_detector:
                self.ir_detector.start()
        else:
            self._status_override_key = ""
            self._hold_shortcut_error_key = ""
            # 停止红外检测器
            if self.ir_detector:
                self.ir_detector.stop()
            self._stop_video_worker()
            self._stop_hold_shortcut_monitor()
            self.video_label.clear()
            self.tracker.reset()
            self.smoother.reset()
            self.classifier.reset_stabilization()
            self.action_machine.reset()
            self._reset_gesture_observation_state()
            self.control_session.reset()
            self.combo_detector.reset()
            self.action_coordinator.stop()
            self.hud.hide_persistent()
            self.overlay.hide_feedback()
            self.power_mode = "normal"
            self.no_hand_frames = 0
            # A stopping session has no "last action"; leaving the old one would
            # claim something happened that this session did not do.
            self._last_action_key = ""
            self._refresh_last_action()
            self.gesture_label.setText(tr("main.preview_idle"))
            self._refresh_precision_console()

    def process_frame(self, landmark_frame: LandmarkFrame):
        """在 Qt 主线程处理 worker 发来的最新推理结果。"""
        import time
        if not self.is_running:
            return
        frame = landmark_frame.frame
        landmarks_valid, landmarks = self._validate_landmarks(landmark_frame.landmarks)
        clock_now = time.monotonic()
        worker_timestamp_ms = getattr(landmark_frame, "timestamp_ms", None)
        if worker_timestamp_ms is None:
            frame_time = max(clock_now, getattr(self, "_last_frame_time", float("-inf")) + 0.001)
        else:
            if not self._accept_worker_timestamp(worker_timestamp_ms):
                self._fail_closed_for_invalid_frame_time()
                return
            frame_time = worker_timestamp_ms / 1000.0
        self._last_frame_time = frame_time
        if not landmarks_valid:
            self._fail_closed_for_invalid_landmarks(frame, frame_time)
            return

        # 节能模式管理
        self._update_power_mode(landmarks)

        # Consume one monotonic worker timestamp across the entire control lane.
        pos, detected = self.tracker.update(landmarks, frame.shape, timestamp=frame_time)
        tracking_lost = not detected
        released_this_frame = False
        if tracking_lost:
            # Tracker may retain a predicted pointer location briefly after the
            # hand disappears. That position is not valid evidence that the
            # same accessible target is still intentionally being pointed at.
            self._reset_gesture_observation_state()
            # The platform controller is authoritative for native mouse-down
            # state, so request its idempotent release without assuming the
            # Python state machine is still synchronized.
            self.action_coordinator.stop()
            released_this_frame = True
            self.action_machine.reset()

        # Edge feedback shares the worker's monotonic frame clock.
        self._check_edge_lost(landmarks, frame_time)

        hand_present = bool(landmarks)
        if hand_present and not getattr(self, "_hand_present_last_frame", False):
            # Hand returned: relative mode must re-anchor, otherwise the cursor
            # jumps by however far the hand moved while it was out of frame.
            self._pointer_anchor_pending = True
        self._hand_present_last_frame = hand_present

        gesture = self.classifier.classify(landmarks, timestamp=frame_time)
        if landmarks:
            assessment = self.hand_dynamics.update(landmarks, frame_time)
            # The episode tracker watches the classifier's own label, before the
            # guard rewrites it: otherwise a suppressed pinch would leave no
            # record, and suppression is exactly what the model has to judge.
            self._observe_pinch_episode(gesture, assessment, frame_time)
            gesture = self._apply_dynamics(gesture, assessment)
        else:
            self.hand_dynamics.reset()
        allowed_before_update = self.control_session.allows_pointer_actions()
        self.control_session.update(
            gesture=gesture,
            has_hand=bool(landmarks),
            shortcut_held=self._is_hold_shortcut_held(),
            now=frame_time,
            landmarks=landmarks,
        )
        if not allowed_before_update and self.control_session.allows_pointer_actions():
            # A fresh pointer session is the clutch: relative mode re-anchors
            # here rather than inheriting a stale hand position.
            self._pointer_anchor_pending = True
        if allowed_before_update and not self.control_session.allows_pointer_actions():
            # The session gate is an input-safety boundary.  If it closes,
            # release a native drag even when the hand is already lost and no
            # cursor position is available for the normal action path.
            if not released_this_frame:
                self.action_coordinator.stop()
            self.action_machine.reset()
            self.hand_dynamics.reset()
            self._reset_gesture_observation_state()
            self.hud.hide_persistent()
            self.overlay.hide_feedback()
        self._refresh_control_session_status()
        # Low-level labels are evidence, not commands. The arbiter grants one
        # lane ownership before optional shortcuts or pointer state transitions
        # may consume this frame.
        pinch_info = self.classifier.get_pinch_info(landmarks, timestamp=frame_time)
        intent_decision = self.intent_arbiter.update(
            gesture=gesture,
            pinch_info=pinch_info,
            pointer_state=self.action_machine.state,
            hand_present=bool(landmarks) and detected,
            now=frame_time,
        )
        status = self._get_status_text(detected)
        self.gesture_label.setText(
            tr("main.gesture_status", gesture=self._gesture_status_label(gesture), status=status)
        )

        # 执行绑定的动作
        lock_info = None
        if pos and detected:
            dynamic_anchor = self._map_pointer(pos, (frame.shape[1], frame.shape[0])) or (0, 0)
            dynamic_config = self.config.get("dynamic_gestures") or {}
            dynamic_lane_available = (
                intent_decision.allow_dynamic
                and dynamic_config.get("enabled", False)
                and self.dynamic_runtime_matcher is not None
            )
            _observation, dynamic_matched = self.observe_completed_dynamic_shortcut(
                landmarks,
                dynamic_anchor,
                gesture=gesture,
                allowed=dynamic_lane_available,
                hand_present=bool(landmarks) and detected,
                now=frame_time,
            )
            dynamic_owns_frame = (
                _observation.recording
                or _observation.completed_frames is not None
                or _observation.owns_frame
            )
            if dynamic_matched or dynamic_owns_frame:
                # Dynamic recording and its terminal neutral boundary own the
                # current frame. Even a rejected completed take must not fall
                # through and reinterpret its final neutral pose as a static,
                # combo, contextual, or pointer command.
                self._render_hud(timestamp=frame_time)
                self.display_frame(self._draw_landmarks(frame, landmarks))
                return
            lock_info = self.execute_action(
                gesture,
                pos,
                frame.shape,
                pinch_info,
                target_detected=detected,
                intent_decision=intent_decision,
                timestamp=frame_time,
            )
        else:
            # A contextual candidate is valid only while the target remains
            # continuously tracked. Never resume it after a lost hand/target.
            self.contextual_intent_controller.reset()
            self.hud.hide_persistent()
        self._render_hud(timestamp=frame_time)

        # 绘制并显示
        frame = self._draw_landmarks(frame, landmarks)
        # 绘制锁定状态视觉反馈
        if lock_info and lock_info.get('is_locked'):
            frame = self._draw_aiming_indicator(frame, lock_info['pos'])
        # 绘制边缘丢失提示
        frame = self._draw_edge_hint(frame, timestamp=frame_time)
        self.display_frame(frame)

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

    def _fail_closed_control_boundary(self):
        """Release native input and forget partial gesture state at any unsafe boundary."""
        self.action_coordinator.stop()
        self.action_machine.reset()
        self.control_session.reset()
        self._reset_gesture_observation_state()
        self.hud.hide_persistent()
        self.overlay.hide_feedback()

    def _fail_closed_for_invalid_landmarks(self, frame, frame_time):
        """Treat malformed detector output as a tracking boundary before classification."""
        self._update_power_mode(None)
        self._check_edge_lost(None, frame_time)
        self._fail_closed_control_boundary()
        self._refresh_control_session_status()
        self.gesture_label.setText(
            tr("main.gesture_status", gesture=self._gesture_status_label("none"), status=self._get_status_text(False))
        )
        self._render_hud(timestamp=frame_time)
        self.display_frame(frame)

    def _accept_worker_timestamp(self, timestamp_ms):
        """Accept only finite, strictly increasing timestamps from the worker."""
        if not isinstance(timestamp_ms, Real) or isinstance(timestamp_ms, bool):
            return False
        if not isfinite(timestamp_ms):
            return False
        if timestamp_ms <= getattr(self, "_last_worker_timestamp_ms", float("-inf")):
            return False
        self._last_worker_timestamp_ms = timestamp_ms
        return True

    def _fail_closed_for_invalid_frame_time(self):
        """Stop input before an invalid camera timestamp can be reinterpreted."""
        self._fail_closed_control_boundary()

    def execute_action(
        self,
        gesture,
        pos,
        frame_shape,
        pinch_info=None,
        target_detected=True,
        intent_decision: IntentDecision | None = None,
        timestamp: float | None = None,
    ):
        """Dispatch one already-arbitrated gesture observation.

        Direct callers without an ``intent_decision`` retain the legacy helper
        behavior used by focused UI tests. Live camera frames always supply one
        from ``IntentArbiter`` so optional lanes cannot steal pointer control.
        """
        import time
        now = time.monotonic() if timestamp is None else timestamp
        if not self.control_session.allows_pointer_actions():
            self.action_machine.reset()
            self.contextual_intent_controller.reset()
            self.hud.hide_persistent()
            return None
        h, w = frame_shape[:2]

        # 映射到屏幕坐标（绝对/相对由配置决定，多屏取并集）
        mapped = self._map_pointer(pos, (w, h))
        if mapped is None:
            return None
        screen_x, screen_y = self.smoother.smooth(mapped[0], mapped[1], timestamp=now)
        self.hud_anchor = (screen_x, screen_y)

        sens = self.config.get("global_sensitivity") or {}
        speed = sens.get("scroll_speed", 50)

        # 获取自定义快捷键
        gesture_cfg = self.config.get_gesture(gesture)
        hotkey = gesture_cfg.get("hotkey", "")
        contextual_label = ""
        contextual_target_id = ""

        # Pointer move/click/drag is a separate, deterministic lifecycle. For
        # camera frames, the arbiter supplies the only label allowed to reach
        # that state machine and gates every optional shortcut lane.
        STATE_MACHINE_GESTURES = {"point", "pinch", "pinch_hold"}
        pointer_gesture = gesture
        allow_combo = True
        allow_optional_shortcuts = True
        if intent_decision is not None:
            pointer_gesture = (
                intent_decision.effective_pointer_gesture
                if intent_decision.allow_pointer
                else None
            )
            allow_combo = intent_decision.allow_combo
            allow_optional_shortcuts = intent_decision.allow_combo

        if not allow_combo:
            # Never retain a partial sequence while a pointer intent owns the
            # hand: it could otherwise complete after the pointer interaction.
            self.combo_detector.reset()
        elif gesture not in STATE_MACHINE_GESTURES and gesture != "none":
            # Neutral is a rearm boundary, never a static-combo input.
            combo_result = self.combo_detector.update(gesture, timestamp=now)
            if combo_result:
                action = combo_result["action"]
                hotkey = combo_result.get("hotkey", "") or hotkey
                dispatch_result = self.action_coordinator.dispatch(
                    ActionRequest(
                        action=action,
                        x=screen_x,
                        y=screen_y,
                        scroll_amount=speed,
                        hotkey=hotkey,
                        gesture=gesture,
                    )
                )
                self._note_episode_action(action, now)
                self._update_hud_after_dispatch(action, dispatch_result, (screen_x, screen_y))
                if dispatch_result.executed and intent_decision is not None:
                    self.intent_arbiter.mark_shortcut_committed()
                return None

        # Only the arbitrated core label may drive mouse state transitions.
        if pointer_gesture in STATE_MACHINE_GESTURES:
            result = self.action_machine.update(
                pointer_gesture, (screen_x, screen_y), pinch_info, timestamp=now
            )
            action = result['action']
            exec_x, exec_y = result['pos']
            is_locked = result.get('is_locked', False)
            dispatch_gesture = pointer_gesture
        elif allow_optional_shortcuts:
            action = self.config.get_gesture_action(gesture)
            exec_x, exec_y = screen_x, screen_y
            is_locked = False
            dispatch_gesture = gesture
        else:
            action = "none"
            exec_x, exec_y = screen_x, screen_y
            is_locked = False
            dispatch_gesture = gesture

        # Accessibility target semantics can refine optional commands, but never
        # replace the deterministic pointer/click/drag lifecycle. A target must
        # first be deliberately pointed at before its contextual command arms.
        context = None
        context_cfg = self.config.get("context_aware") or {}
        if (
            allow_optional_shortcuts
            and target_detected
            and context_cfg.get("enabled", True)
            and context_cfg.get("intent_actions_enabled", True)
        ):
            try:
                context = self._cached_context(screen_x, screen_y)
                intent = self.contextual_intent_controller.observe(
                    context, gesture=gesture, now=now
                )
                if intent is not None:
                    contextual_label = intent.label
                if intent is not None and gesture not in STATE_MACHINE_GESTURES and not intent.requires_confirmation:
                    action = intent.action
                    contextual_target_id = context.target_id
            except Exception:
                context = None
                contextual_label = ""
                contextual_target_id = ""

        if action in {None, "", "none"}:
            # A disabled ordinary binding is a no-op, but it reaches this point
            # so a verified contextual target may safely refine it first.
            return None

        # 持续性动作：每帧都需要执行
        CONTINUOUS_ACTIONS = {
            "move_cursor", "drag", "drag_start", "drag_end",
            "scroll_up", "scroll_down", "scroll_left", "scroll_right"
        }

        # Detect gesture stability against the same frame timestamp.

        # 检测手势变化，记录变化时间
        if gesture != self.last_stable_gesture:
            self.last_gesture_change_time = now
            self.last_stable_gesture = gesture
            # 手势变化时重置执行记录，允许新手势执行动作
            self.last_executed_gesture = "none"
            self.last_executed_action = "none"

        # 一次性动作需要等待手势稳定期
        if action not in CONTINUOUS_ACTIONS:
            # 检查是否在手势稳定期内
            if self.last_gesture_change_time is not None:
                elapsed = now - self.last_gesture_change_time
                if elapsed < self.gesture_grace_period:
                    # 手势刚变化，等待稳定期结束再执行
                    return None

            # 同一手势同一动作只执行一次
            if gesture == self.last_executed_gesture and action == self.last_executed_action:
                return None

            # 记录本次执行
            self.last_executed_gesture = gesture
            self.last_executed_action = action
        else:
            # 持续性动作，重置记录
            self.last_executed_gesture = "none"
            self.last_executed_action = "none"

        dispatch_result = self.action_coordinator.dispatch(
            ActionRequest(
                action=action,
                x=exec_x,
                y=exec_y,
                scroll_amount=speed,
                hotkey=hotkey,
                gesture=dispatch_gesture,
                core_pointer=dispatch_gesture in STATE_MACHINE_GESTURES,
                contextual=bool(contextual_target_id),
                expected_target_id=contextual_target_id,
            )
        )
        self._note_episode_action(action, now)
        self._update_hud_after_dispatch(
            action, dispatch_result, (exec_x, exec_y), is_locked=is_locked, now=now
        )
        self._record_telemetry_action(
            action=action,
            executed=dispatch_result.executed,
            gesture=gesture,
            context=context,
            x=exec_x,
            y=exec_y,
            latency_ms=max(0.0, (time.monotonic() - now) * 1000.0),
        )
        if dispatch_result.executed and contextual_label:
            self.hud.show_contextual(contextual_label, now)

        # 返回锁定状态（用于视觉反馈）
        if is_locked and exec_x and exec_y:
            # 将屏幕坐标转回帧坐标
            frame_pos = self.pointer_mapper.unmap(
                (exec_x, exec_y), (w, h), self.screen_bounds
            ) or (exec_x, exec_y)
            return {'is_locked': True, 'pos': frame_pos}
        return None

    def _update_hud_after_dispatch(self, action, result, anchor, is_locked=False, now=None):
        """Translate actual action results into feedback instead of raw gesture labels."""
        import time

        now = time.monotonic() if now is None else now
        self.hud_anchor = anchor
        if not result.executed and action != "none":
            error_key = self._ACTION_ERROR_KEYS.get(
                result.error_code,
                "main.control_unavailable",
            )
            self.hud.show_error(tr(error_key), now)
            return
        # Continuous lanes are filtered inside _record_last_action so every call
        # site shares one rule.
        if result.executed:
            self._record_last_action(action)
        if is_locked:
            self.hud.show_locking(now)
        elif action in {"drag_start", "drag"} and result.executed:
            self.hud.show_dragging(now)
        elif action == "drag_end":
            self.hud.hide_dragging()
        elif action == "left_click" and result.executed:
            self.hud.show_click(now)
        elif action == "right_click" and result.executed:
            self.hud.show_secondary_click(now)
        elif action == "move_cursor" and result.executed:
            self.hud.show_pointer(now)

    def _render_hud(self, timestamp=None):
        import time

        now = time.monotonic() if timestamp is None else timestamp
        state = self.hud.current_state(now)
        if state is HudState.HIDDEN:
            self.overlay.hide_feedback()
            return
        self.overlay.show_state(state, self.hud_anchor, self.hud.message)

    def _draw_landmarks(self, frame, landmarks):
        if not landmarks:
            return frame
        for x, y, _z in landmarks:
            cv2.circle(frame, (int(x), int(y)), 5, (0, 255, 0), -1)
        for start, end in BaseHandDetector.HAND_CONNECTIONS:
            x1, y1, _ = landmarks[start]
            x2, y2, _ = landmarks[end]
            cv2.line(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
        return frame

    # The preview is a mirror, not a measurement surface. At 15 fps it still
    # reads as smooth video while halving the pixmap uploads and compositor
    # work the window forces every second.
    PREVIEW_FPS = 15.0

    def display_frame(self, frame):
        """显示帧到界面（预览限帧，控制链路不受影响）"""
        now = time.monotonic()
        if now - getattr(self, "_last_preview_at", 0.0) < 1.0 / self.PREVIEW_FPS:
            return
        self._last_preview_at = now
        display = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = display.shape
        img = QImage(display.data, w, h, ch * w, QImage.Format_RGB888)
        scaled = QPixmap.fromImage(img).scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation
        )
        self.video_label.setPixmap(scaled)

    def _update_power_mode(self, landmarks):
        """更新节能模式 - 分层节能策略"""
        if landmarks:
            # 检测到手，立即恢复正常模式
            if self.power_mode != "normal":
                self.power_mode = "normal"
            self.no_hand_frames = 0
            return

        self.no_hand_frames += 1

        # 深度休眠模式：使用红外检测人体存在
        if self.power_mode == "deep_sleep":
            if self.ir_detector:
                if self.ir_detector.detect_presence():
                    # 红外检测到人，唤醒到休眠模式
                    self.power_mode = "sleep"
                    self.no_hand_frames = self.SLEEP_THRESHOLD + 1
            return

        # 进入低功耗模式
        if self.no_hand_frames > self.LOW_THRESHOLD and self.power_mode == "normal":
            self.power_mode = "low"
        # 进入休眠模式
        elif self.no_hand_frames > self.SLEEP_THRESHOLD and self.power_mode == "low":
            self.power_mode = "sleep"
        # 进入深度休眠模式（仅当有红外检测器时）
        elif self.no_hand_frames > self.DEEP_SLEEP_THRESHOLD and self.power_mode == "sleep":
            if self.ir_detector:
                self.power_mode = "deep_sleep"

    def _get_status_text(self, detected):
        """Return a fixed localized runtime status without exposing raw state values."""
        status_key = self._POWER_STATUS_KEYS.get(
            self.power_mode,
            "main.status.detecting" if detected else "main.status.predicting",
        )
        return tr(status_key)

    def _check_edge_lost(self, landmarks, now):
        """检测手势是否从边缘丢失"""
        hand_detected = bool(landmarks)

        # 从有手变为无手
        if self.was_hand_detected and not hand_detected:
            # 方法1：之前在边缘区域
            if self.tracker.at_edge:
                self.edge_lost_time = now
                self.edge_lost_direction = self.tracker.edge_direction
                self.edge_lost_position = self.tracker.last_pos
            # 方法2：基于速度方向推断边缘丢失（解决上下边缘检测问题）
            elif self.tracker.last_pos and self.tracker.pre_lost_velocity:
                vx, vy = self.tracker.pre_lost_velocity
                px, py = self.tracker.last_pos
                w, h = self.tracker.frame_size

                # 速度阈值（像素/秒）
                vel_threshold = 50
                # 位置阈值（距离边缘的比例）
                pos_threshold = 0.25

                dx, dy = 0, 0
                # 检测是否向左/右边缘移动
                if vx < -vel_threshold and px < w * pos_threshold:
                    dx = -1
                elif vx > vel_threshold and px > w * (1 - pos_threshold):
                    dx = 1
                # 检测是否向上/下边缘移动
                if vy < -vel_threshold and py < h * pos_threshold:
                    dy = -1
                elif vy > vel_threshold and py > h * (1 - pos_threshold):
                    dy = 1

                if dx != 0 or dy != 0:
                    self.edge_lost_time = now
                    self.edge_lost_direction = (dx, dy)
                    self.edge_lost_position = self.tracker.last_pos

        self.was_hand_detected = hand_detected

    def _draw_edge_hint(self, frame, timestamp=None):
        """在帧上绘制边缘丢失提示"""
        import time

        if self.edge_lost_time is None or self.edge_lost_position is None:
            return frame

        now = time.monotonic() if timestamp is None else timestamp
        elapsed = now - self.edge_lost_time
        if elapsed > self.EDGE_HINT_DURATION:
            self.edge_lost_time = None
            self.edge_lost_position = None
            return frame

        h, w = frame.shape[:2]
        dx, dy = self.edge_lost_direction
        px, py = self.edge_lost_position

        # 限制位置在画面内
        px = max(50, min(w - 50, px))
        py = max(50, min(h - 50, py))

        # 计算箭头方向（指向边缘外）
        arrow_len = 50
        arrow_dx = dx * arrow_len
        arrow_dy = dy * arrow_len
        arrow_end = (px + arrow_dx, py + arrow_dy)

        # 计算透明度（渐隐效果）
        alpha = max(0, 1 - elapsed / self.EDGE_HINT_DURATION)
        color = (0, int(180 * alpha), int(255 * alpha))  # 橙色渐隐

        # 绘制箭头（从位置指向边缘外）
        cv2.arrowedLine(frame, (px, py), (int(arrow_end[0]), int(arrow_end[1])),
                        color, 3, tipLength=0.4)

        # 绘制提示文字（在箭头旁边）
        text_x = px - 40 if dx >= 0 else px + 10
        text_y = py - 20 if dy >= 0 else py + 30
        cv2.putText(frame, "Lost", (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        return frame

    def _draw_aiming_indicator(self, frame, pos):
        """绘制瞄准状态指示器 - 让用户知道位置已锁定"""
        if pos is None:
            return frame

        x, y = int(pos[0]), int(pos[1])

        # 绘制瞄准圆圈（绿色表示已锁定）
        cv2.circle(frame, (x, y), 20, (0, 255, 0), 2)
        # 绘制十字准星
        cv2.line(frame, (x - 25, y), (x - 10, y), (0, 255, 0), 2)
        cv2.line(frame, (x + 10, y), (x + 25, y), (0, 255, 0), 2)
        cv2.line(frame, (x, y - 25), (x, y - 10), (0, 255, 0), 2)
        cv2.line(frame, (x, y + 10), (x, y + 25), (0, 255, 0), 2)

        return frame

    def open_settings(self, section_id=None):
        """打开设置对话框"""
        from gui.settings_dialog import SettingsDialog

        was_running = self.is_running
        result = 0

        if was_running:
            # A paused camera stream can no longer observe pinch release, so
            # release native drag before opening the modal configuration UI.
            self.action_coordinator.stop()
            self.action_machine.reset()
            self._reset_gesture_observation_state()
            self._stop_video_worker()

        try:
            dialog = SettingsDialog(
                self.config,
                self,
                camera_service=self.platform_services.camera_service,
            )
            if section_id is not None:
                dialog.open_section(section_id)
            result = dialog.exec()
            if result:
                self.config.save()
                # Locale is presentation-only, but Save is the sole boundary
                # permitted to alter it. Cancel never mutates process locale.
                set_locale(self.config.get("ui", "language"))
                self.retranslate_ui()
                # The policy is part of the live dispatch boundary; only an
                # accepted Save may replace it. Cancel leaves the old provider
                # and action coordinator untouched.
                self._refresh_platform_services()
                self._refresh_runtime_configuration()
                self._refresh_control_session_from_config()
                self._refresh_dynamic_shortcuts_from_config()
                combos = self.config.get("gesture_combos") or []
                self.combo_detector.set_combos(combos)
                feedback = self.config.get("feedback") or {}
                self.hud.mode = feedback.get("mode", "standard")
                self.overlay.set_feedback_preferences(
                    opacity=feedback.get("opacity", 0.92),
                    scale=feedback.get("scale", 1.0),
                )
        except Exception:
            self._status_override_key = "main.control_unavailable"
            self._refresh_precision_console()
        finally:
            if was_running and self.is_running:
                if self._start_video_worker() and result:
                    self._start_hold_shortcut_monitor()


    def closeEvent(self, event):
        """关闭窗口时释放资源"""
        self.action_coordinator.stop()
        self._reset_gesture_observation_state()
        self._stop_hold_shortcut_monitor()
        self.hud_timer.stop()
        self.overlay.hide_feedback()
        self.overlay.close()
        if self.ir_detector:
            self.ir_detector.stop()
        self._stop_video_worker()
        event.accept()

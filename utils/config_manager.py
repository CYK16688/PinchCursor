"""配置管理器 - 保存和加载用户设置"""

import json
import os
from copy import deepcopy
from math import isfinite

from core.dynamic_gesture_template import ALLOWED_DYNAMIC_ACTIONS, DynamicGestureTemplate
from utils.hotkey_validation import normalize_hotkey
from utils.locale import DEFAULT_LOCALE, normalize_locale

CURRENT_SCHEMA_VERSION = 4

DYNAMIC_ACTIONS = ALLOWED_DYNAMIC_ACTIONS
DYNAMIC_TEMPLATE_FIELDS = frozenset({
    "template_id", "name", "action", "hotkey", "samples",
    "threshold", "cooldown_seconds", "min_motion_energy",
})
TEMPLATE_GATE_KEYS = (
    "threshold",
    "cooldown_seconds",
    "min_motion_energy",
)
DYNAMIC_DEFAULTS = {
    "threshold": 0.18,
    "cooldown_seconds": 0.75,
    "min_motion_energy": 0.05,
    # Whole-motion safety policy consumed by DynamicIntentLifecycle.
    "neutral_rearm_frames": 3,
    "end_neutral_frames": 2,
    "max_recording_frames": 180,
    "max_duration_seconds": 3.0,
}
LIFECYCLE_INTEGER_DEFAULT_KEYS = frozenset({
    "neutral_rearm_frames", "end_neutral_frames", "max_recording_frames",
})
CORE_POINTER_GESTURES = frozenset({"point", "pinch", "pinch_hold"})
# Generic combinations are discrete optional commands only. Continuous drag
# belongs exclusively to the core pointer state machine.
COMBO_ACTIONS = (
    "left_click",
    "right_click",
    "double_click",
    "middle_click",
    "scroll_up",
    "scroll_down",
    "custom_hotkey",
)
COMBO_ACTION_SET = frozenset(COMBO_ACTIONS)
# Optional static gestures are discrete semantic commands. Pointer movement and
# drag lifecycle remain exclusively owned by the deterministic core lane.
OPTIONAL_STATIC_ACTIONS = frozenset({"none", "left_click", "right_click", "custom_hotkey"})


def normalize_gesture_combos(value):
    """Keep generic shortcut combinations separate from the pointer lifecycle."""
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        gesture1 = item.get("gesture1")
        gesture2 = item.get("gesture2")
        action = item.get("action")
        combo_id = item.get("id")
        hotkey = item.get("hotkey", "")
        if (
            not isinstance(gesture1, str)
            or not isinstance(gesture2, str)
            or not isinstance(action, str)
            or not isinstance(combo_id, (str, int))
            or isinstance(combo_id, bool)
            or not isinstance(hotkey, str)
            or not gesture1
            or not gesture2
            or action not in COMBO_ACTION_SET
            or gesture1 in CORE_POINTER_GESTURES
            or gesture2 in CORE_POINTER_GESTURES
        ):
            continue
        if action == "custom_hotkey":
            try:
                hotkey = normalize_hotkey(hotkey)
            except ValueError:
                continue
        else:
            hotkey = ""
        normalized.append({
            "id": combo_id,
            "gesture1": gesture1,
            "gesture2": gesture2,
            "action": action,
            "hotkey": hotkey,
        })
    return normalized


def _finite_nonnegative(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def _safe_dynamic_defaults(value):
    defaults = dict(DYNAMIC_DEFAULTS)
    if not isinstance(value, dict):
        return defaults
    for key in defaults:
        candidate = value.get(key)
        if key in LIFECYCLE_INTEGER_DEFAULT_KEYS:
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 1:
                defaults[key] = candidate
        elif key == "max_duration_seconds":
            if _finite_nonnegative(candidate) and candidate > 0:
                defaults[key] = candidate
        elif _finite_nonnegative(candidate):
            defaults[key] = candidate
    return defaults


def _tuple_samples(value):
    if not isinstance(value, list):
        return None
    try:
        return tuple(tuple(tuple(float(item) for item in frame) for frame in sample) for sample in value)
    except (TypeError, ValueError):
        return None


def _safe_dynamic_template(value, defaults):
    """Return the persisted public fields for one model-safe dynamic template."""
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    hotkey = value.get("hotkey", "")
    if action not in DYNAMIC_ACTIONS or not isinstance(hotkey, str):
        return None
    if action == "custom_hotkey":
        try:
            hotkey = normalize_hotkey(hotkey)
        except ValueError:
            return None
    else:
        hotkey = ""
    samples = _tuple_samples(value.get("samples"))
    # Only the DTW template gates belong to DynamicGestureTemplate. Lifecycle
    # controls are shared runtime policy stored in defaults, never template
    # payload and never constructor kwargs.
    gates = {key: value.get(key, defaults[key]) for key in TEMPLATE_GATE_KEYS}
    if samples is None or not all(_finite_nonnegative(gates[key]) for key in gates):
        return None
    try:
        template = DynamicGestureTemplate(
            template_id=value.get("template_id"),
            name=value.get("name"),
            action=action,
            samples=samples,
            context_category=value.get("context_category", "") or "",
            **gates,
        )
    except (TypeError, ValueError):
        return None
    return {
        "template_id": template.template_id,
        "name": template.name,
        "action": template.action,
        "hotkey": hotkey.strip() if action == "custom_hotkey" else "",
        # Four decimals is far below the noise floor of the landmarks and cuts
        # roughly a third off every stored take.
        "samples": [
            [[round(value, 4) for value in frame] for frame in sample]
            for sample in template.samples
        ],
        "threshold": template.threshold,
        "cooldown_seconds": template.cooldown_seconds,
        "min_motion_energy": template.min_motion_energy,
        "context_category": template.context_category,
    }


def normalize_dynamic_gestures(value):
    """Fail closed on dynamic persistence; never retain RGB or unknown fields."""
    value = value if isinstance(value, dict) else {}
    defaults = _safe_dynamic_defaults(value.get("defaults"))
    templates = value.get("templates") if isinstance(value.get("templates"), list) else []
    return {
        "enabled": value.get("enabled", False) if isinstance(value.get("enabled", False), bool) else False,
        "defaults": defaults,
        "templates": [
            safe for item in templates
            if (safe := _safe_dynamic_template(item, defaults)) is not None
        ],
    }


DEFAULT_CONFIG = {
    "schema_version": CURRENT_SCHEMA_VERSION,
    "ui": {
        "language": DEFAULT_LOCALE,
    },
    "camera": {
        "id": 0,
        "device_id": "",
        "width": 640,
        "height": 480
    },
    "detection": {
        "confidence": 0.7,
        "tracking_confidence": 0.5,
        "detector_type": "mediapipe"
    },
    "performance": {
        "mode": "standard",
    },
    "pointer_assist": {
        "enabled": True,
        "mode": "bayesian",
        "model_path": "",
        "max_snap_distance": 24.0,
        "min_confidence": 0.55,
        "search_radius": 120.0,
    },
    "pointer_mapping": {
        "mode": "absolute",
        "gain": 2.0,
    },
    "telemetry": {
        "enabled": False,
    },
    "temporal": {
        "transition_guard": True,
    },
    "global_sensitivity": {
        "scroll_speed": 50,
        "smoothing": 0.005
    },
    "gestures": {
        "point": {
            "enabled": True,
            "action": "move_cursor",
            "hotkey": "",
            "description": "指向 - 控制光标移动"
        },
        "pinch": {
            "enabled": True,
            "action": "left_click",
            "hotkey": "",
            "threshold": 35,
            "description": "捏合 - 左键点击"
        },
        "pinch_hold": {
            "enabled": True,
            "action": "drag",
            "hotkey": "",
            "hold_time": 0.3,
            "description": "捏合长按 - 拖动操作"
        },
        "peace": {
            "enabled": True,
            "action": "right_click",
            "hotkey": "",
            "description": "剪刀手 - 右键点击"
        },
        "open_hand": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "张开手掌 - 自定义功能"
        },
        "fist": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "握拳 - 自定义功能"
        },
        "ilove_you": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "我爱你手势 - 拇指、食指和小指伸出"
        },
        "thumb_up": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "拇指向上 - 音量增加"
        },
        "thumb_down": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "拇指向下 - 音量减少"
        },
        "ok": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "OK手势 - 自定义功能"
        },
        "rock": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "摇滚手势 - 自定义功能"
        },
        "three": {
            "enabled": False,
            "action": "none",
            "hotkey": "",
            "description": "三指 - 自定义功能"
        },

    },
    "stabilization": {
        "confirm_threshold": 3,
        "min_switch_interval": 0.15,
        "exit_threshold": 4,
        "cooldown_time": 0.2
    },
    "context_aware": {
        "enabled": True,  # 默认启用智能上下文感知
        "intent_actions_enabled": True,
        # 组件类型 → 允许的手势列表（用户可自定义）
        "control_gestures": {
            "text_input": ["point", "pinch"],
            "clickable": ["point", "pinch", "peace"],
            "slider": ["point", "pinch_hold"],
            "menu": ["point", "pinch"],
            "scrollable": ["point", "pinch", "pinch_hold", "peace", "thumb_up", "thumb_down", "dynamic_shortcut"],
            "generic": ["point", "pinch", "pinch_hold", "peace", "dynamic_shortcut"]
        }
    },
    "zone_rules": [],
    "action_mode": {
        "dwell_threshold": 0.3,    # 停顿阈值（秒）
        "move_threshold": 8,       # 移动阈值（像素）
        "drag_threshold": 0.3      # 拖动阈值（秒）
    },
    "control_session": {
        "mode": "gesture",
        "activation_gesture": "open_hand",
        "exit_gesture": "fist",
        "hold_shortcut": "",
        "stability_seconds": 0.3,
        "no_hand_timeout_seconds": 2.0,
        "activation_template_id": "",
        "exit_template_id": "",
        "custom_static_templates": [],
    },
    "feedback": {
        "mode": "standard",
        "opacity": 0.92,
        "scale": 1.0,
    },
    "dynamic_gestures": {
        "enabled": False,
        "defaults": deepcopy(DYNAMIC_DEFAULTS),
        "templates": [],
    },
    # Pointer move/click/drag are an exclusive real-time intent lane. Generic
    # shortcut combinations begin empty and may only use non-pointer gestures.
    "gesture_combos": []
}

CONFIG_FILE = "settings.json"


class ConfigManager:
    """管理用户配置的读写"""

    def __init__(self, config_path=None):
        self.config = deepcopy(DEFAULT_CONFIG)
        self.config_path = os.fspath(config_path) if config_path is not None else self._get_config_path()
        self.load()

    def _get_config_path(self):
        """获取配置文件路径"""
        base_dir = os.path.dirname(os.path.dirname(__file__))
        return os.path.join(base_dir, CONFIG_FILE)

    def load(self):
        """加载配置文件"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self._merge_config(loaded)
            except Exception:
                pass

    def _merge_config(self, loaded):
        """合并加载的配置与默认配置"""
        if not isinstance(loaded, dict):
            return
        self._merge_dict(self.config, loaded)
        self._normalize_ui_locale()
        self._normalize_legacy_shapes()
        self.config["schema_version"] = CURRENT_SCHEMA_VERSION

    def _normalize_ui_locale(self):
        ui = self.config.get("ui")
        if not isinstance(ui, dict):
            ui = {}
            self.config["ui"] = ui
        ui["language"] = normalize_locale(ui.get("language", DEFAULT_LOCALE))

    def _normalize_configured_hotkeys(self):
        """Canonicalize configured shortcuts or discard unsafe values before runtime reads."""
        control_session = self.config.get("control_session")
        if isinstance(control_session, dict):
            hold_shortcut = control_session.get("hold_shortcut", "")
            try:
                control_session["hold_shortcut"] = normalize_hotkey(
                    hold_shortcut, allow_empty=True
                )
            except ValueError:
                control_session["hold_shortcut"] = ""

        gestures = self.config.get("gestures")
        if isinstance(gestures, dict):
            for gesture in gestures.values():
                if not isinstance(gesture, dict):
                    continue
                try:
                    # Static bindings may combine a semantic action with a
                    # shortcut. Preserve that existing behavior, while making
                    # every persisted non-empty chord canonical and fail-closed.
                    gesture["hotkey"] = normalize_hotkey(
                        gesture.get("hotkey", ""), allow_empty=True
                    )
                except ValueError:
                    gesture["hotkey"] = ""

    def _normalize_legacy_shapes(self):
        """Normalize historical configuration shapes before UI consumers read them."""
        self._normalize_configured_hotkeys()
        action_mode = self.config.get("action_mode")
        if isinstance(action_mode, dict):
            # Core pointer lifecycle is not an opt-in legacy mode.
            action_mode.pop("enabled", None)
        detection = self.config.get("detection")
        if not isinstance(detection, dict):
            detection = {}
            self.config["detection"] = detection
        # Only MediaPipe provides the 21 real hand landmarks required by every
        # pointer and dynamic-gesture safety contract.
        detection["detector_type"] = "mediapipe"
        sensitivity = self.config.get("global_sensitivity")
        if isinstance(sensitivity, dict):
            sensitivity.pop("mouse_speed", None)
        gestures = self.config.get("gestures")
        if isinstance(gestures, dict):
            # The historical "call" shape was indistinguishable from "rock"
            # in the landmark classifier. Drop its persisted binding rather
            # than presenting an action that cannot be intentionally invoked.
            gestures.pop("call", None)
            for gesture in gestures.values():
                if not isinstance(gesture, dict):
                    continue
                gesture.pop("sensitivity", None)
            for gesture_id, gesture in gestures.items():
                if not isinstance(gesture, dict) or gesture_id in CORE_POINTER_GESTURES:
                    continue
                if gesture.get("action") not in OPTIONAL_STATIC_ACTIONS:
                    gesture["enabled"] = False
                    gesture["action"] = "none"
                    gesture["hotkey"] = ""
            for gesture_id, action in (
                ("point", "move_cursor"),
                ("pinch", "left_click"),
                ("pinch_hold", "drag"),
            ):
                gesture = gestures.get(gesture_id)
                if isinstance(gesture, dict):
                    gesture["enabled"] = True
                    gesture["action"] = action
        zone_rules = self.config.get("zone_rules")
        if isinstance(zone_rules, dict):
            self.config["zone_rules"] = []
        elif isinstance(zone_rules, list):
            self.config["zone_rules"] = [rule for rule in zone_rules if isinstance(rule, dict)]
        else:
            self.config["zone_rules"] = []
        self.config["dynamic_gestures"] = normalize_dynamic_gestures(
            self.config.get("dynamic_gestures")
        )
        self.config["gesture_combos"] = normalize_gesture_combos(
            self.config.get("gesture_combos")
        )
        ui = self.config.get("ui")
        if not isinstance(ui, dict):
            ui = {}
            self.config["ui"] = ui
        ui["language"] = normalize_locale(ui.get("language", DEFAULT_LOCALE))

    @staticmethod
    def _merge_dict(destination, source):
        for key, value in source.items():
            if key not in destination:
                destination[key] = deepcopy(value)
            elif isinstance(destination[key], dict) and isinstance(value, dict):
                ConfigManager._merge_dict(destination[key], value)
            else:
                destination[key] = deepcopy(value)

    def save(self):
        """保存配置到文件"""
        self._normalize_ui_locale()
        self._normalize_legacy_shapes()
        self._normalize_configured_hotkeys()
        self.config["dynamic_gestures"] = normalize_dynamic_gestures(
            self.config.get("dynamic_gestures")
        )
        self.config["gesture_combos"] = normalize_gesture_combos(
            self.config.get("gesture_combos")
        )
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def get(self, section, key=None):
        """获取配置值"""
        if key is None:
            return self.config.get(section)
        return self.config.get(section, {}).get(key)

    def set(self, section, key, value):
        """设置配置值"""
        if key is None:
            self.config[section] = value
            return
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value

    def get_gesture(self, gesture_id):
        """获取手势配置"""
        return self.config.get("gestures", {}).get(gesture_id, {})

    def set_gesture(self, gesture_id, key, value):
        """设置手势配置"""
        if "gestures" not in self.config:
            self.config["gestures"] = {}
        if gesture_id not in self.config["gestures"]:
            self.config["gestures"][gesture_id] = {}
        self.config["gestures"][gesture_id][key] = value

    def get_gesture_action(self, gesture_id):
        """获取手势绑定的动作（兼容旧配置）"""
        gesture = self.get_gesture(gesture_id)
        if gesture and gesture.get("enabled", True):
            return gesture.get("action", "none")
        return "none"

    def is_gesture_enabled(self, gesture_id):
        """检查手势是否启用"""
        gesture = self.get_gesture(gesture_id)
        return gesture.get("enabled", True)

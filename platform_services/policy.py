from __future__ import annotations

from dataclasses import dataclass

from .contracts import UIContext


DEFAULT_GESTURES = {
    "text_input": frozenset({"point", "pinch"}),
    "clickable": frozenset({"point", "pinch", "peace"}),
    "slider": frozenset({"point", "pinch_hold"}),
    "menu": frozenset({"point", "pinch"}),
    "scrollable": frozenset(
        {"point", "pinch", "pinch_hold", "peace", "thumb_up", "thumb_down", "dynamic_shortcut"}
    ),
    "generic": frozenset({"point", "pinch", "pinch_hold", "peace", "dynamic_shortcut"}),
}

KNOWN_GESTURES = frozenset().union(*DEFAULT_GESTURES.values())

BLOCKED_ACTIONS = {
    "text_input": frozenset({"drag", "drag_start", "drag_end", "scroll_up", "scroll_down", "scroll_left", "scroll_right"}),
    "clickable": frozenset({"drag", "drag_start", "drag_end", "scroll_up", "scroll_down", "scroll_left", "scroll_right"}),
    "slider": frozenset({"left_click", "right_click", "double_click"}),
    "menu": frozenset({"drag", "drag_start", "drag_end", "scroll_up", "scroll_down"}),
    "scrollable": frozenset(),
    "generic": frozenset(),
}


@dataclass(frozen=True)
class ContextPolicy:
    allowed_gestures: dict[str, frozenset[str]]
    blocked_actions: dict[str, frozenset[str]]
    enabled: bool = True

    @classmethod
    def default(cls) -> "ContextPolicy":
        return cls(
            allowed_gestures={
                category: frozenset(gestures)
                for category, gestures in DEFAULT_GESTURES.items()
            },
            blocked_actions={
                category: frozenset(actions)
                for category, actions in BLOCKED_ACTIONS.items()
            },
        )

    @classmethod
    def from_config(cls, config: object) -> "ContextPolicy":
        """Build a fail-closed contextual policy from persisted settings."""
        policy = cls.default()
        if not isinstance(config, dict):
            return policy
        if config.get("enabled", True) is False:
            # Disabling context awareness removes optional contextual filtering;
            # it must not silently disable ordinary user-configured commands.
            return cls(
                allowed_gestures=policy.allowed_gestures,
                blocked_actions=policy.blocked_actions,
                enabled=False,
            )
        configured_rules = config.get("control_gestures")
        if not isinstance(configured_rules, dict):
            return policy
        for category, gestures in configured_rules.items():
            if category not in DEFAULT_GESTURES or not isinstance(
                gestures, (list, tuple, set, frozenset)
            ):
                continue
            policy.allowed_gestures[category] = frozenset(
                gesture
                for gesture in gestures
                if isinstance(gesture, str) and gesture in KNOWN_GESTURES
            )
        return policy

    def is_gesture_allowed(self, context: UIContext, gesture: str) -> bool:
        if gesture == "none":
            return True
        if not self.enabled:
            return True
        allowed = self.allowed_gestures.get(context.category, self.allowed_gestures["generic"])
        return gesture in allowed

    def is_action_allowed(self, context: UIContext, action: str) -> bool:
        if not self.enabled:
            return True
        blocked = self.blocked_actions.get(context.category, frozenset())
        return action not in blocked

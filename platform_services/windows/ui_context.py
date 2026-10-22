from __future__ import annotations

from platform_services.contracts import UIContext
from platform_services.policy import ContextPolicy


ROLE_CATEGORIES = {
    "Edit": "text_input",
    "ComboBox": "text_input",
    "Button": "clickable",
    "CheckBox": "clickable",
    "RadioButton": "clickable",
    "Hyperlink": "clickable",
    "Slider": "slider",
    "ScrollBar": "slider",
    "Menu": "menu",
    "MenuItem": "menu",
    "List": "scrollable",
    "Tree": "scrollable",
    "Document": "scrollable",
    "Pane": "scrollable",
}


class WindowsUIContextProvider:
    def __init__(self, native, policy: ContextPolicy | None = None):
        self.native = native
        self.policy = policy or ContextPolicy.default()

    def get_context(self, x: int | None = None, y: int | None = None) -> UIContext:
        if x is None or y is None:
            return UIContext(category="generic", source="missing_coordinates")
        try:
            role = self.native.role_at_position(x, y)
        except Exception:
            return UIContext(category="generic", source="uia_unavailable")
        return UIContext(
            category=ROLE_CATEGORIES.get(role, "generic"),
            native_role=role or "",
            source="uia",
        )

    def is_gesture_allowed(self, gesture: str, x: int | None = None, y: int | None = None) -> bool:
        return self.policy.is_gesture_allowed(self.get_context(x, y), gesture)

    def is_action_allowed(self, action: str, x: int | None = None, y: int | None = None) -> bool:
        return self.policy.is_action_allowed(self.get_context(x, y), action)

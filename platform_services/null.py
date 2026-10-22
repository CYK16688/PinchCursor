from __future__ import annotations

from .contracts import (
    ActionRequest,
    ActionResult,
    AuthorizationState,
    PermissionSnapshot,
    UIContext,
)
from .policy import ContextPolicy


class UnavailableCameraService:
    def list_devices(self):
        return []

    def open_selected(self, device_id: str, width: int, height: int):
        return None


class UnavailableInputController:
    def __init__(self, reason: str):
        self.reason = reason

    @property
    def supported_actions(self) -> frozenset[str]:
        return frozenset()

    def execute(self, request: ActionRequest) -> ActionResult:
        return ActionResult(executed=False, reason=self.reason, error_code="unavailable")

    def release_drag(self) -> ActionResult:
        return ActionResult(executed=True)


class GenericUIContextProvider:
    def __init__(self, policy: ContextPolicy | None = None, source: str = "generic"):
        self.policy = policy or ContextPolicy.default()
        self.source = source

    def get_context(self, x: int | None = None, y: int | None = None) -> UIContext:
        return UIContext(category="generic", source=self.source)

    def is_gesture_allowed(self, gesture: str, x: int | None = None, y: int | None = None) -> bool:
        return self.policy.is_gesture_allowed(self.get_context(x, y), gesture)

    def is_action_allowed(self, action: str, x: int | None = None, y: int | None = None) -> bool:
        return self.policy.is_action_allowed(self.get_context(x, y), action)


class UnavailablePermissionProvider:
    def snapshot(self) -> PermissionSnapshot:
        return PermissionSnapshot(
            camera=AuthorizationState.UNAVAILABLE,
            accessibility=AuthorizationState.UNAVAILABLE,
            input_monitoring=AuthorizationState.UNAVAILABLE,
        )

    def request_accessibility_prompt(self) -> bool:
        return False

    def request_input_monitoring_prompt(self) -> bool:
        return False


class NullHoldShortcutMonitor:
    """Portable no-op monitor used where native global shortcuts are unavailable."""

    def configure(self, shortcut: str) -> bool:
        return False

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        return None

    def is_held(self) -> bool:
        return False

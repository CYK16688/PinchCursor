from platform_services.contracts import ActionRequest, ActionResult, AuthorizationState
from core.input_guard import InputGuard


class GestureActionCoordinator:
    """Dispatches pure gesture intents through platform policy and input services."""

    def __init__(self, services):
        self.services = services
        self.input_guard = InputGuard(lambda: self.services.input_controller)

    def dispatch(self, request: ActionRequest | None) -> ActionResult:
        if request is None or request.action == "none":
            return ActionResult(False, "No action requested", "no_action")
        if request.action not in self.services.capabilities.supported_actions:
            reason = self.services.capabilities.unavailable_reasons.get(
                request.action,
                f"{request.action} is unavailable on {self.services.capabilities.platform}",
            )
            return ActionResult(False, reason, "unsupported_action")
        # A started native drag must always receive its matching release, even
        # if TCC status changes mid-gesture. The adapter's release is idempotent.
        if request.action == "drag_end":
            return self.input_guard.execute(request)
        if (
            self.services.capabilities.platform == "macos"
            and self.services.capabilities.permissions.accessibility
            is not AuthorizationState.GRANTED
        ):
            return ActionResult(
                False,
                "Accessibility permission is required before macOS input control can run",
                "accessibility_permission_required",
            )
        # Deterministic pointer lifecycle remains safe and usable when AX is
        # unavailable. Only optional semantic/contextual commands consult the
        # context provider and bind themselves to an expected target identity.
        if request.core_pointer:
            return self.input_guard.execute(request)
        if not request.expected_target_id:
            if request.contextual:
                return ActionResult(False, "Context target is unavailable", "context_target_unavailable")
        else:
            current_context = self.services.context_provider.get_context(request.x, request.y)
            if current_context.target_id != request.expected_target_id:
                return ActionResult(False, "Context target changed", "context_target_changed")
        if not self.services.context_provider.is_gesture_allowed(request.gesture, request.x, request.y):
            return ActionResult(False, "Gesture is blocked in the current UI context", "gesture_blocked")
        if not self.services.context_provider.is_action_allowed(request.action, request.x, request.y):
            return ActionResult(False, "Action is blocked in the current UI context", "action_blocked")
        return self.input_guard.execute(request)

    def stop(self) -> ActionResult:
        return self.input_guard.release()

    def close(self):
        self.input_guard.close()

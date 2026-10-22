from core.action_coordinator import GestureActionCoordinator
from platform_services.contracts import (
    ActionRequest,
    ActionResult,
    AuthorizationState,
    PermissionSnapshot,
    PlatformCapabilities,
    PlatformServices,
    UIContext,
)


class FakeInputController:
    def __init__(self):
        self.release_drag_calls = 0
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return ActionResult(True)

    def release_drag(self):
        self.release_drag_calls += 1
        return ActionResult(True)


class FakeContextProvider:
    def get_context(self, x=None, y=None):
        return UIContext(category="generic")

    def is_gesture_allowed(self, gesture, x=None, y=None):
        return True

    def is_action_allowed(self, action, x=None, y=None):
        return True


class FakePermissions:
    def snapshot(self):
        return None

    def request_accessibility_prompt(self):
        return False


def test_stopping_control_releases_active_drag():
    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test", architecture="test", supported_actions=frozenset({"drag"})
        ),
        input_controller=input_controller,
        context_provider=FakeContextProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).stop()

    assert result.executed is True
    assert input_controller.release_drag_calls == 1


def test_context_denial_prevents_input_execution():
    class BlockingContextProvider(FakeContextProvider):
        def is_action_allowed(self, action, x=None, y=None):
            return False

    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test", architecture="test", supported_actions=frozenset({"drag"})
        ),
        input_controller=input_controller,
        context_provider=BlockingContextProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).dispatch(ActionRequest(action="drag", gesture="pinch_hold"))

    assert result.executed is False
    assert result.error_code == "action_blocked"


def test_drag_end_bypasses_context_policy_to_release_an_active_drag():
    class BlockingContextProvider(FakeContextProvider):
        def is_gesture_allowed(self, gesture, x=None, y=None):
            return False

        def is_action_allowed(self, action, x=None, y=None):
            return False

    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test", architecture="test", supported_actions=frozenset({"drag_end"})
        ),
        input_controller=input_controller,
        context_provider=BlockingContextProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).dispatch(
        ActionRequest(action="drag_end", x=10, y=20, gesture="point")
    )

    assert result.executed is True


def test_drag_end_reaches_input_controller_after_macos_accessibility_revocation():
    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos",
            architecture="arm64",
            supported_actions=frozenset({"drag_end"}),
            permissions=PermissionSnapshot(
                camera=AuthorizationState.GRANTED,
                accessibility=AuthorizationState.DENIED,
            ),
        ),
        input_controller=input_controller,
        context_provider=FakeContextProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).dispatch(
        ActionRequest(action="drag_end", x=10, y=20, gesture="point", core_pointer=True)
    )

    assert result.executed is True
    assert input_controller.requests[-1].action == "drag_end"


def test_core_pointer_request_executes_when_accessibility_context_is_unavailable():
    class BlockingContextProvider(FakeContextProvider):
        def get_context(self, x=None, y=None):
            raise AssertionError("core pointer requests must not query AX context")

        def is_gesture_allowed(self, gesture, x=None, y=None):
            return False

    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test", architecture="test", supported_actions=frozenset({"move_cursor"})
        ),
        input_controller=input_controller,
        context_provider=BlockingContextProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).dispatch(
        ActionRequest(action="move_cursor", x=10, y=20, gesture="point", core_pointer=True)
    )

    assert result.executed is True
    assert input_controller.requests[-1].action == "move_cursor"


def test_contextual_request_fails_closed_when_target_changes_before_dispatch():
    class ChangedTargetProvider(FakeContextProvider):
        def get_context(self, x=None, y=None):
            return UIContext(category="scrollable", target_id="new-target")

    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="test", architecture="test", supported_actions=frozenset({"scroll_down"})
        ),
        input_controller=input_controller,
        context_provider=ChangedTargetProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).dispatch(
        ActionRequest(
            action="scroll_down", gesture="thumb_down", contextual=True,
            expected_target_id="old-target",
        )
    )

    assert result.executed is False
    assert result.error_code == "context_target_changed"
    assert not input_controller.requests


def test_macos_input_is_blocked_until_accessibility_is_granted():
    input_controller = FakeInputController()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos",
            architecture="arm64",
            supported_actions=frozenset({"move_cursor"}),
            permissions=PermissionSnapshot(
                camera=AuthorizationState.NOT_DETERMINED,
                accessibility=AuthorizationState.DENIED,
            ),
        ),
        input_controller=input_controller,
        context_provider=FakeContextProvider(),
        permission_provider=FakePermissions(),
    )

    result = GestureActionCoordinator(services).dispatch(
        ActionRequest(action="move_cursor", x=10, y=20, gesture="point")
    )

    assert result.executed is False
    assert result.error_code == "accessibility_permission_required"

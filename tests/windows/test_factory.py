"""Factory contract: Windows services are composed, and never raise when they can't be."""

import sys

import pytest

from platform_services.contracts import (
    ActionRequest,
    AuthorizationState,
    CameraDevice,
    PermissionSnapshot,
    PlatformCapabilities,
    PlatformServices,
)
from platform_services.factory import _create_windows_services, create_platform_services
from platform_services.null import (
    NullHoldShortcutMonitor,
    UnavailableCameraService,
    UnavailableInputController,
)
from platform_services.windows.input_controller import WindowsInputController
from platform_services.windows.native import WindowsNativeFacade
from platform_services.windows.permissions import WindowsPermissionProvider
from platform_services.windows.shortcut_monitor import WindowsHoldShortcutMonitor
from platform_services.windows.ui_context import WindowsUIContextProvider

UI_ACTIONS = frozenset(
    {
        "left_click",
        "right_click",
        "double_click",
        "middle_click",
        "scroll_up",
        "scroll_down",
        "custom_hotkey",
    }
)


class FakeBinding:
    def __init__(self, window_class="", async_state=None):
        self.window_class = window_class
        self.async_state = async_state or {}
        self.batches = []

    def send_inputs(self, inputs):
        self.batches.append(list(inputs))
        return len(inputs)

    def async_key_state(self, virtual_key):
        return self.async_state.get(virtual_key, 0)

    def virtual_screen_bounds(self):
        return (0, 0, 1920, 1080)

    def window_class_at_point(self, x, y):
        return self.window_class


class StubCameraService:
    def list_devices(self):
        return [CameraDevice("windows-index-0", "Camera 0", "unknown", True)]

    def open_selected(self, device_id, width, height):
        return None


def _windows_services(binding=None):
    native = WindowsNativeFacade(binding or FakeBinding())
    return native, _create_windows_services(native=native, camera_service=StubCameraService())


def test_windows_factory_composes_every_platform_service():
    native, services = _windows_services()

    assert isinstance(services, PlatformServices)
    assert services.capabilities.platform == "windows"
    assert services.capabilities.unavailable_reasons == {}
    assert services.capabilities.supported_actions == WindowsInputController(native).supported_actions
    assert isinstance(services.input_controller, WindowsInputController)
    assert isinstance(services.context_provider, WindowsUIContextProvider)
    assert isinstance(services.permission_provider, WindowsPermissionProvider)
    assert isinstance(services.camera_service, StubCameraService)
    assert isinstance(services.hold_shortcut_monitor, WindowsHoldShortcutMonitor)


def test_windows_capabilities_expose_every_action_the_ui_offers():
    _native, services = _windows_services()

    assert UI_ACTIONS <= services.capabilities.supported_actions
    assert "move_cursor" in services.capabilities.supported_actions


def test_windows_capabilities_report_permissions_without_macos_prompts():
    _native, services = _windows_services()

    permissions = services.capabilities.permissions
    assert permissions.accessibility is AuthorizationState.GRANTED
    assert permissions.camera is AuthorizationState.NOT_DETERMINED
    assert permissions.input_monitoring is AuthorizationState.UNAVAILABLE


def test_windows_coordinator_dispatches_a_pointer_click_through_the_ctypes_facade():
    from core.action_coordinator import GestureActionCoordinator

    binding = FakeBinding()
    _native, services = _windows_services(binding)

    result = GestureActionCoordinator(services).dispatch(
        ActionRequest(action="left_click", x=100, y=200, core_pointer=True)
    )

    assert result.executed is True
    assert [len(batch) for batch in binding.batches] == [2, 1]
    assert binding.batches[0][0].u.mi.dx > 0
    assert binding.batches[0][0].u.mi.dy > 0


def test_windows_context_provider_uses_the_native_role_lookup():
    _native, services = _windows_services(FakeBinding(window_class="Edit"))

    context = services.context_provider.get_context(10, 20)

    assert context.category == "text_input"
    assert context.native_role == "Edit"


def test_windows_hold_shortcut_monitor_is_wired_to_the_native_key_state():
    binding = FakeBinding(async_state={0xA2: 0x8000, 0x20: 0x8000})
    _native, services = _windows_services(binding)
    monitor = services.hold_shortcut_monitor

    assert services.capabilities.platform == "windows"
    assert monitor.configure("ctrl+space") is True
    assert monitor.start() is True
    assert monitor.is_held() is True


def test_windows_factory_falls_back_when_the_native_facade_cannot_be_built(monkeypatch):
    def exploding_facade(*_args, **_kwargs):
        raise RuntimeError("user32 unavailable")

    monkeypatch.setattr("platform_services.windows.native.WindowsNativeFacade", exploding_facade)

    services = _create_windows_services()

    assert services.capabilities.platform == "windows"
    assert isinstance(services.input_controller, UnavailableInputController)
    assert isinstance(services.camera_service, UnavailableCameraService)
    assert isinstance(services.hold_shortcut_monitor, NullHoldShortcutMonitor)
    assert "Windows native services are unavailable" in services.capabilities.unavailable_reasons["all"]
    assert services.capabilities.supported_actions == frozenset()


def test_windows_factory_falls_back_when_camera_service_construction_fails(monkeypatch):
    class ExplodingCameraService:
        def __init__(self):
            raise ImportError("cv2 missing")

    monkeypatch.setattr("platform_services.windows.camera.WindowsCameraService", ExplodingCameraService)

    services = _create_windows_services(native=WindowsNativeFacade(FakeBinding()))

    assert isinstance(services.input_controller, UnavailableInputController)
    assert "cv2 missing" in services.capabilities.unavailable_reasons["all"]


def test_windows_factory_degrades_camera_consent_instead_of_failing_the_build():
    class OpaqueNative(WindowsNativeFacade):
        def camera_authorization(self):
            raise OSError("no consent store")

    services = _create_windows_services(
        native=OpaqueNative(FakeBinding()), camera_service=StubCameraService()
    )

    assert isinstance(services.input_controller, WindowsInputController)
    assert services.capabilities.permissions.camera is AuthorizationState.NOT_DETERMINED


@pytest.mark.skipif(sys.platform == "win32", reason="Windows hosts have a real native facade")
def test_windows_factory_on_a_foreign_host_reports_unavailable_instead_of_raising():
    services = create_platform_services(system_name="Windows")

    assert services.capabilities.platform == "windows"
    assert isinstance(services.input_controller, UnavailableInputController)
    assert services.capabilities.unavailable_reasons["all"].startswith("Windows native services")


def test_unknown_platforms_stay_unsupported():
    services = create_platform_services(system_name="Linux")

    assert services.capabilities.platform == "unsupported"
    assert isinstance(services.input_controller, UnavailableInputController)
    assert "Linux" in services.capabilities.unavailable_reasons["all"]


def test_windows_services_satisfy_the_shared_platform_contract():
    _native, services = _windows_services()

    assert isinstance(services.capabilities, PlatformCapabilities)
    for attribute in ("execute", "release_drag"):
        assert callable(getattr(services.input_controller, attribute))
    for attribute in ("get_context", "is_gesture_allowed", "is_action_allowed"):
        assert callable(getattr(services.context_provider, attribute))
    for attribute in ("configure", "start", "stop", "is_held"):
        assert callable(getattr(services.hold_shortcut_monitor, attribute))
    assert isinstance(services.permission_provider.snapshot(), PermissionSnapshot)
    for attribute in ("list_devices", "open_selected"):
        assert callable(getattr(services.camera_service, attribute))
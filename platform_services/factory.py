from __future__ import annotations

import platform

from .contracts import PlatformCapabilities, PlatformServices
from .null import (
    GenericUIContextProvider,
    NullHoldShortcutMonitor,
    UnavailableCameraService,
    UnavailableInputController,
    UnavailablePermissionProvider,
)
from .policy import ContextPolicy


def create_platform_services(
    system_name: str | None = None,
    context_policy: ContextPolicy | None = None,
) -> PlatformServices:
    system_name = system_name or platform.system()
    if system_name == "Darwin":
        return _create_macos_services(context_policy)
    if system_name == "Windows":
        return _create_windows_services(context_policy)

    return _unavailable_services(
        platform_name="unsupported",
        reason=f"{system_name or 'Unknown'} platform adapter is not available",
        context_policy=context_policy,
        source="platform_unavailable",
    )


def _unavailable_services(
    platform_name: str,
    reason: str,
    context_policy: ContextPolicy | None,
    source: str,
    *,
    camera_permission_promptable: bool = True,
) -> PlatformServices:
    """Build the safe no-op service set used by every failed adapter path."""
    permissions = UnavailablePermissionProvider()
    return PlatformServices(
        capabilities=PlatformCapabilities(
            platform=platform_name,
            architecture=platform.machine(),
            unavailable_reasons={"all": reason},
            permissions=permissions.snapshot(),
            camera_permission_promptable=camera_permission_promptable,
        ),
        input_controller=UnavailableInputController(reason),
        context_provider=GenericUIContextProvider(policy=context_policy, source=source),
        permission_provider=permissions,
        camera_service=UnavailableCameraService(),
        hold_shortcut_monitor=NullHoldShortcutMonitor(),
    )


def _create_windows_services(
    context_policy: ContextPolicy | None = None,
    *,
    native=None,
    camera_service=None,
) -> PlatformServices:
    """Compose Windows services, or fall back to Unavailable rather than raise.

    ``native`` and ``camera_service`` exist so the composition itself can be
    exercised with fakes on a non-Windows host. Production callers pass neither
    and get the ctypes-backed facade.
    """
    try:
        from .windows.camera import WindowsCameraService
        from .windows.input_controller import WindowsInputController
        from .windows.native import WindowsNativeFacade
        from .windows.permissions import WindowsPermissionProvider
        from .windows.shortcut_monitor import WindowsHoldShortcutMonitor
        from .windows.ui_context import WindowsUIContextProvider

        if native is None:
            native = WindowsNativeFacade()
        permissions = WindowsPermissionProvider(native)
        input_controller = WindowsInputController(native)
        return PlatformServices(
            capabilities=PlatformCapabilities(
                platform="windows",
                architecture=platform.machine(),
                supported_actions=input_controller.supported_actions,
                permissions=permissions.snapshot(),
                # Win32 has no in-app camera consent prompt: Settings-privacy
                # can block capture, but the block only surfaces as a failed
                # open, so the UI must offer "Start control" rather than a
                # "Grant camera access" button that cannot raise anything.
                camera_permission_promptable=False,
            ),
            input_controller=input_controller,
            context_provider=WindowsUIContextProvider(
                native, context_policy or ContextPolicy.default()
            ),
            permission_provider=permissions,
            camera_service=camera_service if camera_service is not None else WindowsCameraService(),
            hold_shortcut_monitor=WindowsHoldShortcutMonitor(native),
        )
    except Exception as error:
        return _unavailable_services(
            platform_name="windows",
            reason=f"Windows native services are unavailable: {error}",
            context_policy=context_policy,
            source="native_unavailable",
            camera_permission_promptable=False,
        )


def _create_macos_services(context_policy: ContextPolicy | None = None) -> PlatformServices:
    try:
        from .macos.input_controller import MacOSInputController
        from .macos.camera import MacOSCameraService
        from .macos.native import MacOSNativeFacade
        from .macos.permissions import MacOSPermissionProvider
        from .macos.shortcut_monitor import MacOSHoldShortcutMonitor
        from .macos.ui_context import MacOSUIContextProvider

        native = MacOSNativeFacade()
        permissions = MacOSPermissionProvider(native)
        input_controller = MacOSInputController(native)
        return PlatformServices(
            capabilities=PlatformCapabilities(
                platform="macos",
                architecture=platform.machine(),
                supported_actions=input_controller.supported_actions,
                permissions=permissions.snapshot(),
            ),
            input_controller=input_controller,
            context_provider=MacOSUIContextProvider(
                native, context_policy or ContextPolicy.default()
            ),
            permission_provider=permissions,
            camera_service=MacOSCameraService(native),
            hold_shortcut_monitor=MacOSHoldShortcutMonitor(native),
        )
    except Exception as error:
        return _unavailable_services(
            platform_name="macos",
            reason=f"macOS native services are unavailable: {error}",
            context_policy=context_policy,
            source="native_unavailable",
        )

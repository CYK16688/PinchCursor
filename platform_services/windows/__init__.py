"""Windows platform services.

Importing this package must stay safe on non-Windows hosts: nothing here loads
user32 at import time. The native facade is constructed by the platform factory
only, and falls back to the Unavailable services when it cannot be built.
"""

from .camera import WindowsCameraService
from .input_controller import WindowsInputController
from .native import WindowsNativeFacade
from .permissions import WindowsPermissionProvider
from .shortcut_monitor import WindowsHoldShortcutMonitor
from .ui_context import WindowsUIContextProvider

__all__ = [
    "WindowsCameraService",
    "WindowsHoldShortcutMonitor",
    "WindowsInputController",
    "WindowsNativeFacade",
    "WindowsPermissionProvider",
    "WindowsUIContextProvider",
]

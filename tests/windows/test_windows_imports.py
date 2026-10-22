"""Import hygiene: the Windows adapter must load on any host without user32.

The shared gesture code and the platform factory are imported on macOS too, so
every Windows module has to be importable without touching user32, pywin32,
comtypes, or pyautogui. Only ``WindowsApiBinding`` may open the native library,
and only when it is actually constructed.
"""

import importlib
import sys

import pytest

WINDOWS_MODULES = (
    "platform_services.windows",
    "platform_services.windows.camera",
    "platform_services.windows.input_controller",
    "platform_services.windows.native",
    "platform_services.windows.permissions",
    "platform_services.windows.shortcut_monitor",
    "platform_services.windows.ui_context",
)

FORBIDDEN_NATIVE_MODULES = (
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "comtypes",
    "pywintypes",
    "pyautogui",
)


def test_windows_adapter_modules_import_on_any_host():
    for module_name in WINDOWS_MODULES:
        assert importlib.import_module(module_name) is not None


def test_windows_adapter_imports_pull_no_third_party_native_layer():
    for module_name in WINDOWS_MODULES:
        importlib.import_module(module_name)

    loaded = [name for name in FORBIDDEN_NATIVE_MODULES if name in sys.modules]
    assert loaded == []


def test_windows_package_exports_the_full_service_set():
    package = importlib.import_module("platform_services.windows")

    assert set(package.__all__) == {
        "WindowsCameraService",
        "WindowsHoldShortcutMonitor",
        "WindowsInputController",
        "WindowsNativeFacade",
        "WindowsPermissionProvider",
        "WindowsUIContextProvider",
    }
    for exported in package.__all__:
        assert getattr(package, exported) is not None


@pytest.mark.skipif(sys.platform == "win32", reason="Windows hosts can load user32")
def test_user32_is_only_opened_when_the_binding_is_constructed():
    from platform_services.windows.native import WindowsApiBinding

    with pytest.raises(RuntimeError):
        WindowsApiBinding()

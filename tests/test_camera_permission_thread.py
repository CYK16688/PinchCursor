"""Camera permission completion: AVFoundation calls back off the GUI thread."""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication

from gui import main_window
from platform_services.contracts import (
    AuthorizationState,
    PermissionSnapshot,
    PlatformCapabilities,
    PlatformServices,
)
from platform_services.null import (
    GenericUIContextProvider,
    UnavailableCameraService,
    UnavailableInputController,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Provider:
    def __init__(self):
        self.completion = None

    def snapshot(self):
        return PermissionSnapshot(
            camera=AuthorizationState.NOT_DETERMINED,
            accessibility=AuthorizationState.GRANTED,
            input_monitoring=AuthorizationState.GRANTED,
        )

    def request_accessibility_prompt(self):
        return False

    def request_input_monitoring_prompt(self):
        return False

    def request_camera_access(self, completion):
        self.completion = completion


def _window(monkeypatch):
    provider = _Provider()
    services = PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos",
            architecture="arm64",
            permissions=provider.snapshot(),
        ),
        input_controller=UnavailableInputController("test"),
        context_provider=GenericUIContextProvider(),
        permission_provider=provider,
        camera_service=UnavailableCameraService(),
    )
    monkeypatch.setattr(main_window, "create_platform_services", lambda **_kwargs: services)
    return main_window.MainWindow(), provider


def test_the_camera_request_hands_over_a_plain_python_callable(app, monkeypatch):
    """PyObjC cannot turn a builtin such as Signal.emit into an ObjC block."""
    window, provider = _window(monkeypatch)
    try:
        window.request_camera_permission_and_start()
        assert callable(provider.completion)
        assert not isinstance(provider.completion, type(window.camera_permission_ready.emit))
        assert provider.completion == window._deliver_camera_ready
        window.request_camera_permission()
        assert provider.completion == window._deliver_camera_settled
    finally:
        window.close()


class _Probe(QObject):
    """Records which thread the signal handler ran on."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, granted):
        self.calls.append((granted, QThread.currentThread() is self.thread()))


def test_a_background_completion_is_delivered_on_the_gui_thread(app, monkeypatch):
    window, provider = _window(monkeypatch)
    try:
        window.camera_permission_ready.disconnect(window._on_camera_permission_result)
        probe = _Probe()
        window.camera_permission_ready.connect(probe.record)

        worker = threading.Thread(target=lambda: provider.completion and provider.completion(False))
        window.request_camera_permission_and_start()
        worker.start()
        worker.join()
        app.processEvents()

        assert probe.calls == [(False, True)]
    finally:
        window.close()

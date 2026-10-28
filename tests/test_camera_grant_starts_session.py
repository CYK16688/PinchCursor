"""Granting camera access from the primary button must start the session.

The button that asked for the TCC prompt and the button that says "Stop control"
are the same button. If the granted callback only started the worker without
marking the session running, every frame was dropped and the preview stayed on
the placeholder, so the user had to click Start a second time.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
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
        self.camera = AuthorizationState.NOT_DETERMINED

    def snapshot(self):
        return PermissionSnapshot(
            camera=self.camera,
            accessibility=AuthorizationState.GRANTED,
            input_monitoring=AuthorizationState.GRANTED,
        )

    def request_accessibility_prompt(self):
        return False

    def request_input_monitoring_prompt(self):
        return False

    def request_camera_access(self, completion):
        self.camera = AuthorizationState.GRANTED
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
    window = main_window.MainWindow()
    window._start_video_worker = lambda: True
    window._start_hold_shortcut_monitor = lambda: True
    return window, provider


def test_granting_camera_access_starts_the_control_session(app, monkeypatch):
    window, provider = _window(monkeypatch)
    try:
        assert window.is_running is False
        window._perform_primary_action()
        assert window.is_running is False

        provider.completion(True)
        app.processEvents()

        assert window.is_running is True
        # The primary button is now the stop affordance, not a second "grant".
        assert window.primary_control_button.text() == main_window.tr("main.stop")
    finally:
        window.close()


def test_a_denied_camera_grant_leaves_the_session_stopped(app, monkeypatch):
    window, provider = _window(monkeypatch)
    try:
        window._perform_primary_action()
        provider.completion(False)
        app.processEvents()

        assert window.is_running is False
        assert window._status_override_key == "main.camera_permission_denied"
    finally:
        window.close()


def test_starting_the_camera_is_a_waiting_state_not_a_failure(app, monkeypatch):
    """A transient the user asked for must not paint in the danger colour."""
    window, provider = _window(monkeypatch)
    try:
        window._perform_primary_action()
        provider.completion(True)
        app.processEvents()

        assert window._status_override_key == "main.starting_camera"
        assert window.status_indicator.property("semantic") == "waiting"
        assert window.status_chip.property("semantic") == "waiting"
    finally:
        window.close()

"""The console must teach the gestures it actually bound.

The gesture reference is derived from configuration rather than hard-coded, so it
can never advertise a binding the runtime would not execute. It also has to
appear without opening Settings: a new user has no other way to learn that an
open palm takes the pointer and a pinch clicks.
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
from utils.config_manager import ConfigManager


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Provider:
    def snapshot(self):
        return PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.GRANTED,
            input_monitoring=AuthorizationState.GRANTED,
        )

    def request_accessibility_prompt(self):
        return False

    def request_input_monitoring_prompt(self):
        return False

    def request_camera_access(self, completion):
        return None


def _window(monkeypatch, tmp_path, config=None):
    config = config or ConfigManager(config_path=tmp_path / "settings.json")
    monkeypatch.setattr(main_window, "ConfigManager", lambda: config)
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
    return main_window.MainWindow()


def test_core_pointer_gestures_are_always_listed(app, monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    try:
        listed = set(window.gesture_rows)
        assert {"point", "pinch", "pinch_hold", "thumb_up", "thumb_down"} <= listed
        assert dict(window._bound_gestures())["thumb_down"] == "scroll_down"
    finally:
        window.close()


def test_an_unbound_optional_gesture_is_not_advertised(app, monkeypatch, tmp_path):
    """The sheet must not promise a gesture the runtime ignores."""
    window = _window(monkeypatch, tmp_path)
    try:
        assert "ok" not in window.gesture_rows
    finally:
        window.close()


def test_contextual_only_mode_does_not_advertise_unbound_core_scroll(app, monkeypatch, tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("pointer_scroll", "enabled", False)
    window = _window(monkeypatch, tmp_path, config=config)
    try:
        assert "thumb_up" not in window.gesture_rows
        assert "thumb_down" not in window.gesture_rows
    finally:
        window.close()


def test_binding_an_optional_gesture_adds_it_to_the_sheet(app, monkeypatch, tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set_gesture("open_hand", "action", "left_click")
    config.set_gesture("open_hand", "enabled", True)
    window = _window(monkeypatch, tmp_path, config=config)
    try:
        assert "open_hand" in window.gesture_rows
    finally:
        window.close()


def test_the_reference_is_hidden_when_nothing_is_bound(app, monkeypatch, tmp_path):
    """A header with no rows would be an empty promise; hide the whole block."""
    window = _window(monkeypatch, tmp_path)
    try:
        window.config.config["gestures"] = {}
        window._rebuild_gesture_reference()
        assert window.gesture_reference.isVisible() is False
    finally:
        window.close()


def test_the_state_dot_carries_the_semantic_not_the_text(app, monkeypatch, tmp_path):
    """A glyph inside localised text cannot be restyled and is read aloud."""
    window = _window(monkeypatch, tmp_path)
    try:
        window._on_camera_permission_result(False)
        assert "●" not in window.status_indicator.text()
        assert window.state_dot.property("semantic") == "denied"
    finally:
        window.close()


def test_the_hint_tells_the_user_what_to_do_next(app, monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    try:
        window.is_running = False
        window._refresh_control_session_status()
        idle_hint = window.session_hint.text()
        window.is_running = True
        window._refresh_control_session_status()
        running_hint = window.session_hint.text()

        assert idle_hint
        assert running_hint
        # The two states must not read identically, or the hint says nothing.
        assert idle_hint != running_hint
    finally:
        window.close()

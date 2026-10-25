"""Permission page: a recheck that works, and the restart rule stated plainly."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from gui.settings_dialog import SettingsDialog
from platform_services.contracts import AuthorizationState, PermissionSnapshot
from utils.config_manager import ConfigManager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(tmp_path, app):
    page = SettingsDialog(ConfigManager(config_path=str(tmp_path / "settings.json")))
    yield page
    page.close()


def test_the_page_states_the_restart_rule(dialog):
    assert "重新打开" in dialog.restart_hint_label.text() or "reopen" in dialog.restart_hint_label.text()


def test_rechecking_without_a_window_is_a_no_op(dialog):
    # No parent provider: the button must not build native services or raise.
    dialog.recheck_permissions_button.click()


def _state(value):
    return getattr(AuthorizationState, value.upper())


class _Provider:
    def __init__(self, snapshot):
        self.snapshot_value = snapshot
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return self.snapshot_value


class _Window(QWidget):
    """Stand-in parent exposing the two attributes the page reaches for."""

    def __init__(self, provider):
        super().__init__()
        from types import SimpleNamespace

        self.platform_services = SimpleNamespace(permission_provider=provider)
        self.refreshed = 0

    def _refresh_permission_status(self):
        self.refreshed += 1


def test_recheck_repaints_from_a_fresh_snapshot(dialog):
    provider = _Provider(
        PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.GRANTED,
            input_monitoring=AuthorizationState.DENIED,
        )
    )
    window = _Window(provider)

    dialog._recheck_permissions(window)

    assert window.refreshed == 1
    assert provider.calls >= 1
    assert dialog.permissions_accessibility_value.text() == "已授权" or (
        dialog.permissions_accessibility_value.text() == "Granted"
    )
    assert dialog.permissions_accessibility_value.property("semantic") == ""
    assert dialog.permissions_input_monitoring_value.property("semantic") == "denied"


def test_recheck_survives_a_provider_that_raises(dialog):
    class _Broken:
        def snapshot(self):
            raise RuntimeError("AX unavailable")

    window = _Window(_Broken())

    dialog._recheck_permissions(window)

    assert window.refreshed == 1

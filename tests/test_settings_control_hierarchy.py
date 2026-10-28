"""Primary pointer tuning stays reachable; advanced edits keep staged semantics."""

from copy import deepcopy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from gui.i18n import set_locale
from gui.settings_dialog import SettingsDialog
from gui.theme import DARK_THEME
from utils.config_manager import ConfigManager


class NoCamera:
    def list_devices(self):
        return []


@pytest.fixture
def dialog(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    window = SettingsDialog(config, camera_service=NoCamera())
    window.setStyleSheet(DARK_THEME)
    yield app, window, config
    window.close()
    window.deleteLater()


def _within_viewport(widget, scroll):
    origin = widget.mapTo(scroll.viewport(), QPoint(0, 0))
    return scroll.viewport().rect().contains(origin) and scroll.viewport().rect().contains(
        origin + QPoint(widget.width() - 1, widget.height() - 1)
    )


@pytest.mark.parametrize("locale", ["zh_CN", "en_US"])
@pytest.mark.parametrize("size", [(1040, 720), (900, 640)])
def test_primary_pointer_controls_fit_without_scrolling(dialog, locale, size):
    app, window, _config = dialog
    set_locale(locale)
    window.retranslate_ui()
    window.resize(*size)
    window.show()
    app.processEvents()

    for field in (
        window.mapping_mode, window.mapping_gain, window.point_assist_check,
        window.scroll_speed, window.smoothing, window.dead_zone, window.calibrate_button,
    ):
        assert field.isVisible(), field.accessibleName()
        assert _within_viewport(field, window.pointer_page), field.accessibleName()
    assert window.pointer_page.horizontalScrollBar().maximum() == 0
    assert not window.custom_trigger_group.isVisible()
    assert not window.assist_mode.isVisible()


def test_control_shortcuts_select_the_requested_task_each_time(dialog):
    _app, window, _config = dialog
    window.open_section("activation")
    assert window.current_section_id == "control"
    assert window.control_tabs.currentWidget() is window.activation_page
    window.open_section("camera")
    assert window.current_section_id == "camera"
    window.open_section("pointer")
    assert window.current_section_id == "control"
    assert window.control_tabs.currentWidget() is window.pointer_page
    window.open_section("activation")
    window.open_section("control")
    assert window.control_tabs.currentWidget() is window.pointer_page


def test_moved_pointer_and_advanced_edits_are_discarded_by_cancel(dialog):
    _app, window, config = dialog
    original = deepcopy(config.config)
    window.mapping_mode.setCurrentData("relative")
    window.mapping_gain.setValue(3.2)
    window.smoothing.setValue(13)
    window.dead_zone.setValue(3)
    window.control_tabs.setCurrentWidget(window.control_advanced_page)
    window.stability_seconds.setValue(650)
    window.assist_mode.setCurrentData("shadow")
    window.reject()
    assert config.config == original


def test_moved_pointer_and_advanced_values_survive_save_and_reopen(dialog):
    _app, window, config = dialog
    window.mapping_mode.setCurrentData("relative")
    window.mapping_gain.setValue(3.2)
    window.scroll_speed.setValue(71)
    window.smoothing.setValue(13)
    window.dead_zone.setValue(3)
    window.stability_seconds.setValue(650)
    window.assist_mode.setCurrentData("shadow")
    window.save_settings()
    # The host persists an accepted dialog's staged configuration.
    config.save()

    reopened = SettingsDialog(ConfigManager(config_path=config.config_path), camera_service=NoCamera())
    try:
        assert reopened.mapping_mode.currentData() == "relative"
        assert reopened.mapping_gain.value() == pytest.approx(3.2)
        assert reopened.scroll_speed.value() == 71
        assert reopened.smoothing.value() == 13
        assert reopened.dead_zone.value() == 3
        assert reopened.stability_seconds.value() == 650
        assert reopened.assist_mode.currentData() == "shadow"
    finally:
        reopened.close()
        reopened.deleteLater()


def test_retranslation_keeps_names_on_visible_pointer_controls(dialog):
    _app, window, _config = dialog
    set_locale("en_US")
    window.retranslate_ui()
    assert window.point_assist_check.text() == "Click assist"
    assert window.point_assist_check.accessibleName() == "Click assist"
    assert window.smoothing.accessibleName() == window.smoothing_label.text()
    assert window.mapping_gain.accessibleName() == "Movement gain"
    assert window.mapping_gain_label.buddy() is window.mapping_gain

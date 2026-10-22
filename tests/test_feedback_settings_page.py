import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.feedback_settings_page import FeedbackSettingsPage
from gui.i18n import DEFAULT_LOCALE, set_locale
from utils.config_manager import ConfigManager


def test_feedback_page_stages_and_persists_hud_preferences(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    page = FeedbackSettingsPage(config)
    try:
        page.mode_combo.setCurrentIndex(page.mode_combo.findData("quiet"))
        page.opacity_input.setValue(82)
        page.scale_input.setValue(115)
        page.apply_to_config()

        assert config.get("feedback", "mode") == "quiet"
        assert config.get("feedback", "opacity") == 0.82
        assert config.get("feedback", "scale") == 1.15
    finally:
        page.close()


def test_feedback_page_retranslates_static_copy_without_changing_staged_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = FeedbackSettingsPage(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        quiet_index = page.mode_combo.findData("quiet")
        page.mode_combo.setCurrentIndex(quiet_index)
        page.opacity_input.setValue(82)

        assert page.title_label.text() == "反馈"
        assert page.mode_combo.itemText(quiet_index) == "安静 — 拖动锁定和错误"

        set_locale("en_US")
        page.retranslate_ui()

        assert page.title_label.text() == "Feedback"
        assert page.mode_combo.itemText(page.mode_combo.findData("quiet")) == "Quiet — drag lock and errors"
        assert page.mode_combo.currentData() == "quiet"
        assert page.opacity_input.value() == 82
    finally:
        page.close()


def test_quiet_feedback_copy_matches_lock_and_error_behavior(tmp_path):
    app = QApplication.instance() or QApplication([])
    page = FeedbackSettingsPage(ConfigManager(config_path=tmp_path / "settings.json"))
    try:
        quiet_index = page.mode_combo.findData("quiet")

        assert page.mode_combo.itemText(quiet_index) == "安静 — 拖动锁定和错误"
    finally:
        page.close()

from gui.combo_card import ComboCard
from gui.dynamic_gesture_settings_page import DynamicGestureSettingsPage
from gui.gesture_list import GestureList
from gui.i18n import translate
from gui.main_window import MainWindow


def _all_display_keys():
    yield from ComboCard._GESTURE_LABEL_KEYS.values()
    yield from ComboCard._ACTION_LABEL_KEYS.values()
    yield from GestureList._GESTURE_LABEL_KEYS.values()
    yield from GestureList._ACTION_LABEL_KEYS.values()
    yield from GestureList._CONTRACT_LABEL_KEYS.values()
    yield from DynamicGestureSettingsPage.ACTION_KEYS.values()
    yield from MainWindow._GESTURE_LABEL_KEYS.values()
    yield from MainWindow._POWER_STATUS_KEYS.values()


def test_all_current_display_key_allowlists_have_translations_in_each_supported_locale():
    for locale in ("zh_CN", "en_US"):
        for key in set(_all_display_keys()):
            assert translate(key, locale=locale) != key

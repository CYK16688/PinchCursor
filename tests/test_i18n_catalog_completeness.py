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


def test_literal_ui_translation_keys_exist_and_locale_placeholders_match():
    import ast
    from pathlib import Path
    from string import Formatter

    from gui.i18n import _CATALOGS

    chinese, english = _CATALOGS["zh_CN"], _CATALOGS["en_US"]
    assert chinese.keys() == english.keys()
    for key in chinese:
        def fields(value):
            return {name for _, name, _, _ in Formatter().parse(value) if name is not None}
        assert fields(chinese[key]) == fields(english[key]), key
    for path in (Path(__file__).resolve().parents[1] / "gui").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {"tr", "translate"} and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                assert node.args[0].value in chinese, (path.name, node.lineno, node.args[0].value)

from gui.i18n import _CATALOGS, DEFAULT_LOCALE, current_locale, normalize_locale, set_locale, tr


def setup_function():
    set_locale(DEFAULT_LOCALE)


def test_default_locale_is_simplified_chinese():
    assert DEFAULT_LOCALE == "zh_CN"
    assert current_locale() == "zh_CN"
    assert tr("common.save") == "保存"


def test_invalid_locale_falls_back_to_simplified_chinese():
    assert normalize_locale("fr_FR") == "zh_CN"
    assert set_locale("fr_FR") == "zh_CN"
    assert tr("common.cancel") == "取消"


def test_english_translates_core_settings_labels():
    set_locale("en_US")

    assert tr("settings.language") == "Language"
    assert tr("common.save") == "Save"
    assert tr("common.cancel") == "Cancel"


def test_missing_key_returns_the_stable_key():
    assert tr("missing.translation") == "missing.translation"

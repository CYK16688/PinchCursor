from gui.theme import DARK_THEME


def test_dark_theme_explicitly_styles_combo_popup_rows_for_readability():
    assert "QComboBox QAbstractItemView" in DARK_THEME
    assert "background: #1A1D24;" in DARK_THEME
    assert "color: #F5F7FA;" in DARK_THEME
    assert "selection-background-color: #2B447A;" in DARK_THEME


def test_dark_theme_gives_primary_titles_explicit_foreground_color():
    assert "QLabel#appTitle {\n    color: #F5F7FA;" in DARK_THEME
    assert "QLabel#settingsPageTitle {\n    color: #F5F7FA;" in DARK_THEME
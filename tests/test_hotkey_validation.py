import pytest

from utils.hotkey_validation import normalize_hotkey


@pytest.mark.parametrize(
    ("shortcut", "expected"),
    (
        ("command + shift + P", "cmd+shift+p"),
        ("ctrl+option+space", "ctrl+alt+space"),
        ("tab", "tab"),
    ),
)
def test_normalize_hotkey_accepts_only_source_controlled_tokens(shortcut, expected):
    assert normalize_hotkey(shortcut) == expected


@pytest.mark.parametrize(
    "shortcut",
    (
        "",
        "cmd+",
        "+p",
        "cmd++p",
        "cmd+bogus+p",
        "bogus+p",
        "cmd+cmd+p",
        "cmd+command+p",
        "cmd+unknown",
        "cmd+shift",
    ),
)
def test_normalize_hotkey_rejects_malformed_or_ambiguous_shortcuts(shortcut):
    with pytest.raises(ValueError):
        normalize_hotkey(shortcut)

"""Text the user has to read must clear WCAG AA on the dark theme.

The primary button carried white ink on the brand accent: 3.15:1 at rest and
2.68:1 on hover, i.e. the most-used control was worst exactly when the user was
pointing at it. Body-size content was painted in the disabled tier (3.04:1).
These tests compute the real ratios from the tokens, so a new colour cannot
quietly reintroduce the problem.
"""

import re
import pathlib

import pytest

THEME = pathlib.Path(__file__).resolve().parents[1] / "gui" / "theme.py"


def _luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    high, low = sorted(
        (_luminance(foreground), _luminance(background)), reverse=True
    )
    return (high + 0.05) / (low + 0.05)


AA_NORMAL = 4.5


def _block(selector: str) -> str:
    """Return the QSS rule body for one selector."""
    source = THEME.read_text(encoding="utf-8")
    pattern = re.escape(selector) + r"\s*\{([^}]*)\}"
    match = re.search(pattern, source)
    assert match, f"{selector} not found in theme.py"
    return match.group(1)


def _colour(block: str, prop: str) -> str:
    match = re.search(prop + r"\s*:\s*(#[0-9A-Fa-f]{6})", block)
    assert match, f"{prop} not defined"
    return match.group(1)


@pytest.mark.parametrize("selector", ["QPushButton#primaryControlButton"])
def test_the_primary_button_ink_is_legible(selector):
    block = _block(selector)
    assert contrast(_colour(block, "color"), _colour(block, "background")) >= AA_NORMAL


def test_the_primary_button_hover_is_not_worse_than_its_rest_state():
    rest = _block("QPushButton#primaryControlButton")
    hover = _block("QPushButton#primaryControlButton:hover")
    ink = _colour(rest, "color")
    assert contrast(ink, _colour(hover, "background")) >= AA_NORMAL


def test_the_save_button_ink_is_legible():
    block = _block("QPushButton#saveBtn")
    assert contrast(_colour(block, "color"), _colour(block, "background")) >= AA_NORMAL


def test_the_last_action_value_is_legible_on_a_card():
    block = _block("QLabel#lastActionValue")
    assert contrast(_colour(block, "color"), "#121419") >= AA_NORMAL


def test_hint_copy_is_legible_on_every_background():
    block = _block("QLabel#hintLabel, QLabel#comboLabel")
    ink = _colour(block, "color")
    for background in ("#0B0C0F", "#121419", "#1A1D24"):
        assert contrast(ink, background) >= AA_NORMAL, background


def test_the_disabled_tier_is_never_used_for_readable_content():
    """#5C636F is the inactive signal; it is too dark to carry content."""
    for selector in (
        "QLabel#lastActionValue",
        "QLabel#comboEmpty",
        "QLabel#hintLabel, QLabel#comboLabel",
    ):
        assert _colour(_block(selector), "color").upper() != "#5C636F", selector

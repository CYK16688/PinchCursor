"""Fail-closed Windows shortcut validation for native input injection."""

from __future__ import annotations

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "meta": "win",
}

# Keep this source-controlled independently from macOS virtual keycodes. The
# Windows adapter receives string chords, so only retain tokens it can safely
# forward to its native facade.
TERMINAL_KEYS = frozenset(
    {
        *(chr(code) for code in range(ord("a"), ord("z") + 1)),
        *(str(number) for number in range(10)),
        "space", "enter", "escape", "tab", "backspace", "delete", "insert",
        "home", "end", "pageup", "pagedown", "left", "right", "down", "up",
        *(f"f{number}" for number in range(1, 13)),
    }
)


def normalize_windows_hotkey(value: str, *, allow_empty: bool = False) -> str:
    """Return a canonical Windows chord or reject malformed/unsupported text."""
    if not isinstance(value, str):
        raise ValueError("Shortcut must be text")
    if not value.strip():
        if allow_empty:
            return ""
        raise ValueError("Shortcut is empty")

    parts = [part.strip().lower() for part in value.split("+")]
    if any(not part for part in parts):
        raise ValueError("Shortcut contains an empty token")

    terminal = parts[-1]
    if terminal in _MODIFIER_ALIASES:
        raise ValueError("Shortcut requires a terminal key")
    if terminal not in TERMINAL_KEYS:
        raise ValueError("Unsupported shortcut key")

    modifiers = []
    for token in parts[:-1]:
        modifier = _MODIFIER_ALIASES.get(token)
        if modifier is None:
            raise ValueError("Unsupported shortcut modifier")
        if modifier in modifiers:
            raise ValueError("Duplicate shortcut modifier")
        modifiers.append(modifier)
    return "+".join(
        (*[modifier for modifier in ("ctrl", "alt", "shift", "win") if modifier in modifiers], terminal)
    )

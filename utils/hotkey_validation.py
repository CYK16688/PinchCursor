"""Pure, fail-closed normalization for persisted and injected shortcuts."""

from __future__ import annotations

_MODIFIER_ALIASES = {
    "cmd": "cmd",
    "command": "cmd",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
}

# Source-controlled macOS virtual-key table shared by persistence validation,
# native injection, and the listen-only hold monitor. Do not accept a UI token
# unless this table contains a corresponding native key.
MACOS_KEYCODES = {
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5,
    "h": 4, "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45,
    "o": 31, "p": 35, "q": 12, "r": 15, "s": 1, "t": 17, "u": 32,
    "v": 9, "w": 13, "x": 7, "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23,
    "6": 22, "7": 26, "8": 28, "9": 25,
    "space": 49, "enter": 36, "escape": 53, "tab": 48,
    "backspace": 51, "delete": 117, "insert": 114, "home": 115,
    "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96,
    "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
    "f11": 103, "f12": 111,
}
TERMINAL_KEYS = frozenset(MACOS_KEYCODES)


def normalize_hotkey(value: str, *, allow_empty: bool = False) -> str:
    """Return a canonical shortcut or reject malformed/ambiguous input.

    A shortcut has zero or more unique modifier tokens followed by exactly one
    source-controlled terminal key. Unknown tokens and empty segments are never
    silently discarded.
    """
    if not isinstance(value, str):
        raise ValueError("Shortcut must be text")
    stripped = value.strip()
    if not stripped:
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
    canonical_modifiers = tuple(
        modifier for modifier in ("cmd", "ctrl", "alt", "shift") if modifier in modifiers
    )
    return "+".join((*canonical_modifiers, terminal))

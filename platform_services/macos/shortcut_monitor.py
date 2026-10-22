from __future__ import annotations

from utils.hotkey_validation import normalize_hotkey


class MacOSHoldShortcutMonitor:
    """Listen-only macOS global shortcut monitor with injectable native I/O."""

    _modifier_aliases = {
        "cmd": "cmd",
        "command": "cmd",
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "option": "alt",
        "shift": "shift",
    }

    def __init__(self, native):
        self.native = native
        self._tap = None
        self._terminal_keycode: int | None = None
        self._modifier_keycodes: frozenset[int] = frozenset()
        self._required_modifiers: frozenset[str] = frozenset()
        self._pressed_modifier_codes: set[int] = set()
        self._terminal_down = False

    def configure(self, shortcut: str) -> bool:
        self.stop()
        self._clear_state()
        try:
            required_modifiers, terminal_keycode, modifier_keycodes = self._parse(shortcut)
        except (AttributeError, KeyError, TypeError, ValueError):
            self._terminal_keycode = None
            self._modifier_keycodes = frozenset()
            self._required_modifiers = frozenset()
            return False
        self._required_modifiers = required_modifiers
        self._terminal_keycode = terminal_keycode
        self._modifier_keycodes = modifier_keycodes
        return True

    def start(self) -> bool:
        if self._tap is not None:
            return True
        if self._terminal_keycode is None:
            return False
        tap = self.native.create_listen_only_event_tap(self._handle_event)
        if tap is None or not self.native.start_event_tap(tap):
            return False
        self._tap = tap
        return True

    def stop(self) -> None:
        if self._tap is not None:
            self.native.stop_event_tap(self._tap)
            self._tap = None
        self._clear_state()

    def is_held(self) -> bool:
        return bool(
            self._terminal_down
            and self._required_modifiers <= self._active_modifiers()
        )

    def _parse(self, shortcut: str) -> tuple[frozenset[str], int, frozenset[int]]:
        normalized = normalize_hotkey(shortcut)
        parts = normalized.split("+")
        terminal = parts[-1]
        terminal_keycode = self.native.shortcut_keycodes[terminal]
        required_modifiers = tuple(parts[:-1])
        modifier_keycodes = frozenset(
            keycode
            for modifier in required_modifiers
            for keycode in self.native.shortcut_modifier_keycodes[modifier]
        )
        return frozenset(required_modifiers), int(terminal_keycode), modifier_keycodes

    def _handle_event(self, event_type: str, keycode: int | None = None) -> None:
        if event_type in {"tap_disabled_timeout", "tap_disabled_user_input"}:
            self._clear_state()
            return
        if event_type == "key_down":
            if keycode == self._terminal_keycode:
                self._terminal_down = True
            return
        if event_type == "key_up":
            if keycode == self._terminal_keycode:
                self._terminal_down = False
            return
        if event_type == "flags_changed" and keycode in self._modifier_keycodes:
            if keycode in self._pressed_modifier_codes:
                self._pressed_modifier_codes.remove(keycode)
                if not self._required_modifiers <= self._active_modifiers():
                    self._terminal_down = False
            else:
                self._pressed_modifier_codes.add(keycode)

    def _active_modifiers(self) -> frozenset[str]:
        return frozenset(
            modifier
            for modifier, keycodes in self.native.shortcut_modifier_keycodes.items()
            if self._pressed_modifier_codes.intersection(keycodes)
        )

    def _clear_state(self) -> None:
        self._pressed_modifier_codes.clear()
        self._terminal_down = False

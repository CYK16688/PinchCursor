"""Polled Windows hold-shortcut monitor.

Windows global hotkeys are usually built on ``RegisterHotKey`` or a low-level
``SetWindowsHookEx`` keyboard hook. Both are wrong here: the first consumes the
combination system-wide, and the second needs a message loop plus a callback that
must never stall the 60 fps frame loop. Because the GUI already polls every
frame, ``GetAsyncKeyState`` is both simpler and safer - it only observes, never
consumes, and installs nothing that has to be torn down.

The monitor keeps the same lifecycle as the macOS adapter:
``configure(shortcut)`` -> ``start()`` -> ``is_held()`` repeatedly -> ``stop()``.
"""

from __future__ import annotations

from utils.windows_hotkey_validation import normalize_windows_hotkey


class WindowsHoldShortcutMonitor:
    """Observe one configured global shortcut by polling key state."""

    def __init__(self, native):
        self.native = native
        self._running = False
        self._terminal_keycode: int | None = None
        self._modifier_keycode_groups: tuple[frozenset[int], ...] = ()

    def configure(self, shortcut: str) -> bool:
        """Parse and store a canonical chord; return False for unusable text."""
        self.stop()
        self._terminal_keycode = None
        self._modifier_keycode_groups = ()
        try:
            terminal_keycode, modifier_groups = self._parse(shortcut)
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
        self._terminal_keycode = terminal_keycode
        self._modifier_keycode_groups = modifier_groups
        return True

    def start(self) -> bool:
        if self._running:
            return True
        if self._terminal_keycode is None:
            return False
        # Polling allocates nothing, so "starting" only proves the native query
        # works. A broken binding must fail here instead of pinning the session
        # to a monitor that can never report a hold.
        try:
            self.native.key_is_down(self._terminal_keycode)
        except Exception:
            return False
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def is_held(self) -> bool:
        if not self._running or self._terminal_keycode is None:
            return False
        try:
            if not self.native.key_is_down(self._terminal_keycode):
                return False
            return all(
                any(self.native.key_is_down(keycode) for keycode in group)
                for group in self._modifier_keycode_groups
            )
        except Exception:
            # Never let a failing key query count as a held shortcut.
            return False

    def _parse(self, shortcut: str) -> tuple[int, tuple[frozenset[int], ...]]:
        normalized = normalize_windows_hotkey(shortcut)
        parts = normalized.split("+")
        terminal_keycode = int(self.native.shortcut_keycodes[parts[-1]])
        modifier_groups = tuple(
            frozenset(
                int(keycode) for keycode in self.native.shortcut_modifier_keycodes[modifier]
            )
            for modifier in parts[:-1]
        )
        return terminal_keycode, modifier_groups

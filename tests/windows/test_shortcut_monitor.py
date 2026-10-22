"""Polled hold-shortcut monitor contract on an injected fake native facade."""

from platform_services.windows.shortcut_monitor import WindowsHoldShortcutMonitor

CTRL_LEFT, CTRL_RIGHT = 0xA2, 0xA3
SHIFT_LEFT, SHIFT_RIGHT = 0xA0, 0xA1
SPACE = 0x20
P = 0x50


class FakeNative:
    shortcut_keycodes = {"space": SPACE, "p": P}
    shortcut_modifier_keycodes = {
        "ctrl": frozenset({CTRL_LEFT, CTRL_RIGHT}),
        "shift": frozenset({SHIFT_LEFT, SHIFT_RIGHT}),
    }

    def __init__(self, down=(), failing=False):
        self.down = set(down)
        self.failing = failing
        self.queries = []

    def key_is_down(self, virtual_key):
        self.queries.append(virtual_key)
        if self.failing:
            raise RuntimeError("key state unavailable")
        return virtual_key in self.down


def test_configure_accepts_a_canonical_chord_and_rejects_junk():
    monitor = WindowsHoldShortcutMonitor(FakeNative())

    assert monitor.configure("ctrl+shift+space") is True
    assert monitor.configure("ctrl+bogus") is False
    assert monitor.configure("") is False
    assert monitor.configure("command+space") is False


def test_is_held_requires_start_and_every_modifier():
    native = FakeNative()
    monitor = WindowsHoldShortcutMonitor(native)
    assert monitor.configure("ctrl+shift+space") is True

    native.down = {CTRL_LEFT, SHIFT_LEFT, SPACE}
    assert monitor.is_held() is False

    assert monitor.start() is True
    assert monitor.is_held() is True

    native.down = {CTRL_LEFT, SPACE}
    assert monitor.is_held() is False

    native.down = {SHIFT_LEFT, SPACE}
    assert monitor.is_held() is False

    native.down = {CTRL_RIGHT, SHIFT_RIGHT, SPACE}
    assert monitor.is_held() is True

    native.down = {CTRL_RIGHT, SHIFT_RIGHT}
    assert monitor.is_held() is False


def test_stop_clears_hold_and_start_is_idempotent():
    native = FakeNative(down={CTRL_LEFT, SHIFT_LEFT, SPACE})
    monitor = WindowsHoldShortcutMonitor(native)
    monitor.configure("ctrl+shift+space")

    assert monitor.start() is True
    assert monitor.start() is True
    assert monitor.is_held() is True

    monitor.stop()
    assert monitor.is_held() is False

    assert monitor.start() is True
    assert monitor.is_held() is True


def test_shortcut_without_modifiers_holds_on_the_terminal_key_alone():
    native = FakeNative(down={SPACE})
    monitor = WindowsHoldShortcutMonitor(native)

    assert monitor.configure("space") is True
    assert monitor.start() is True
    assert monitor.is_held() is True

    native.down = set()
    assert monitor.is_held() is False


def test_reconfigure_stops_the_monitor_and_clears_stale_state():
    native = FakeNative(down={CTRL_LEFT, SHIFT_LEFT, SPACE})
    monitor = WindowsHoldShortcutMonitor(native)
    monitor.configure("ctrl+shift+space")
    monitor.start()
    assert monitor.is_held() is True

    assert monitor.configure("ctrl+p") is True

    assert monitor.is_held() is False
    assert monitor.start() is True
    assert monitor.is_held() is False

    native.down = {CTRL_LEFT, P}
    assert monitor.is_held() is True


def test_failed_configure_never_reports_a_hold():
    native = FakeNative(down={CTRL_LEFT, SPACE})
    monitor = WindowsHoldShortcutMonitor(native)

    assert monitor.configure("ctrl+bogus") is False
    assert monitor.start() is False
    assert monitor.is_held() is False


def test_start_fails_when_the_native_key_query_is_broken():
    monitor = WindowsHoldShortcutMonitor(FakeNative(down={CTRL_LEFT, SPACE}, failing=True))
    monitor.configure("ctrl+space")

    assert monitor.start() is False
    assert monitor.is_held() is False


def test_broken_key_query_during_polling_is_not_treated_as_held():
    native = FakeNative(down={CTRL_LEFT, SPACE})
    monitor = WindowsHoldShortcutMonitor(native)
    monitor.configure("ctrl+space")
    assert monitor.start() is True

    native.failing = True

    assert monitor.is_held() is False


def test_unknown_key_table_entries_are_rejected_without_raising():
    class SparseNative(FakeNative):
        shortcut_keycodes = {}
        shortcut_modifier_keycodes = {}

    monitor = WindowsHoldShortcutMonitor(SparseNative())

    assert monitor.configure("ctrl+space") is False
    assert monitor.is_held() is False


def test_monitor_only_reads_key_state():
    native = FakeNative(down={CTRL_LEFT, SPACE})
    monitor = WindowsHoldShortcutMonitor(native)
    monitor.configure("ctrl+space")
    monitor.start()
    monitor.is_held()
    monitor.stop()

    assert set(native.queries) <= {CTRL_LEFT, CTRL_RIGHT, SPACE}

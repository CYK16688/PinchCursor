from platform_services.macos.shortcut_monitor import MacOSHoldShortcutMonitor


class FakeNative:
    shortcut_keycodes = {
        "a": 0,
        "space": 49,
    }
    shortcut_modifier_keycodes = {
        "cmd": frozenset({55, 54}),
        "ctrl": frozenset({59, 62}),
        "alt": frozenset({58, 61}),
        "shift": frozenset({56, 60}),
    }

    def __init__(self):
        self.callback = None
        self.started = []
        self.stopped = []

    def create_listen_only_event_tap(self, callback):
        self.callback = callback
        return "tap"

    def start_event_tap(self, tap):
        self.started.append(tap)
        return True

    def stop_event_tap(self, tap):
        self.stopped.append(tap)

    def emit(self, event_type, keycode=None):
        self.callback(event_type, keycode)


def test_configured_chord_is_held_only_while_terminal_and_modifiers_are_down():
    native = FakeNative()
    monitor = MacOSHoldShortcutMonitor(native)

    assert monitor.configure("command + shift + a") is True
    assert monitor.start() is True
    native.emit("flags_changed", 55)
    native.emit("flags_changed", 56)
    native.emit("key_down", 0)
    assert monitor.is_held() is True

    native.emit("key_up", 0)
    assert monitor.is_held() is False


def test_modifier_first_release_and_tap_disable_clear_held_state():
    native = FakeNative()
    monitor = MacOSHoldShortcutMonitor(native)
    monitor.configure("ctrl+space")
    monitor.start()
    native.emit("flags_changed", 59)
    native.emit("key_down", 49)
    assert monitor.is_held() is True

    native.emit("flags_changed", 59)
    assert monitor.is_held() is False

    native.emit("flags_changed", 59)
    native.emit("key_down", 49)
    native.emit("tap_disabled_timeout")
    assert monitor.is_held() is False


def test_releasing_one_side_of_a_required_modifier_keeps_chord_held():
    native = FakeNative()
    monitor = MacOSHoldShortcutMonitor(native)
    monitor.configure("shift+a")
    monitor.start()

    native.emit("flags_changed", 56)
    native.emit("flags_changed", 60)
    native.emit("key_down", 0)
    assert monitor.is_held() is True

    native.emit("flags_changed", 56)
    assert monitor.is_held() is True

    native.emit("flags_changed", 60)
    assert monitor.is_held() is False


def test_stop_reconfigure_and_invalid_shortcuts_clear_state_without_creating_taps():
    native = FakeNative()
    monitor = MacOSHoldShortcutMonitor(native)
    monitor.configure("alt+a")
    monitor.start()
    native.emit("flags_changed", 58)
    native.emit("key_down", 0)
    assert monitor.is_held() is True

    monitor.configure("shift+space")
    assert monitor.is_held() is False
    assert native.stopped == ["tap"]
    for invalid in ("cmd+unknown", "cmd++space", "cmd+command+space", "bogus+space"):
        assert monitor.configure(invalid) is False
        assert monitor.is_held() is False
        assert monitor.start() is False


def test_unrelated_keys_never_activate_the_configured_chord():
    native = FakeNative()
    monitor = MacOSHoldShortcutMonitor(native)
    monitor.configure("cmd+a")
    monitor.start()

    native.emit("flags_changed", 55)
    native.emit("key_down", 49)
    assert monitor.is_held() is False

    native.emit("key_down", 0)
    assert monitor.is_held() is True

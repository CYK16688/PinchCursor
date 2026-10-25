"""The permission buttons: ask the OS, then show the switch that grants it."""

from types import SimpleNamespace

from gui.main_window import MainWindow


class _Provider:
    def __init__(self, *, granted=False, fail=False):
        self.granted = granted
        self.fail = fail
        self.opened = []

    def request_accessibility_prompt(self):
        if self.fail:
            raise RuntimeError("AX framework unavailable")
        return self.granted

    def request_input_monitoring_prompt(self):
        if self.fail:
            raise RuntimeError("CGPreflight unavailable")
        return self.granted

    def open_privacy_settings(self, pane):
        self.opened.append(pane)
        return True


def _window(provider):
    window = MainWindow.__new__(MainWindow)
    window.platform_services = SimpleNamespace(permission_provider=provider)
    window._refresh_permission_status = lambda: None
    window._refresh_precision_console = lambda: None
    return window


def test_a_refused_accessibility_prompt_opens_the_privacy_pane():
    provider = _Provider(granted=False)

    _window(provider).request_accessibility_permission()

    assert provider.opened == ["accessibility"]


def test_an_already_granted_accessibility_does_not_open_settings():
    provider = _Provider(granted=True)

    _window(provider).request_accessibility_permission()

    assert provider.opened == []


def test_input_monitoring_falls_back_to_its_own_pane():
    provider = _Provider(granted=False)

    _window(provider).request_input_monitoring_permission()

    assert provider.opened == ["input_monitoring"]


def test_a_failing_native_call_still_sends_the_user_to_the_pane():
    provider = _Provider(granted=False, fail=True)

    _window(provider).request_accessibility_permission()

    assert provider.opened == ["accessibility"]


def test_a_backend_without_deep_links_is_not_an_error():
    class Bare:
        def request_accessibility_prompt(self):
            return False

    window = _window(Bare())

    window.request_accessibility_permission()

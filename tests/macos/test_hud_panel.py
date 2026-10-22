from platform_services.macos.hud_panel import MacOSHudPanelController


class FakePanel:
    def __init__(self):
        self.calls = []

    def setLevel_(self, value):
        self.calls.append(("level", value))

    def setCollectionBehavior_(self, value):
        self.calls.append(("behavior", value))

    def setIgnoresMouseEvents_(self, value):
        self.calls.append(("mouse", value))

    def setHidesOnDeactivate_(self, value):
        self.calls.append(("hides", value))

    def orderFrontRegardless(self):
        self.calls.append(("front",))


class FakeNative:
    status_window_level = 25
    collection_behavior = 1 | 256 | 8

    def panel_for_widget(self, _widget):
        return self.panel


def test_macos_hud_panel_is_global_mouse_transparent_and_visible_over_full_screen_spaces():
    native = FakeNative()
    native.panel = FakePanel()
    controller = MacOSHudPanelController(native)

    controller.attach(object())
    controller.raise_panel()

    assert ("level", 25) in native.panel.calls
    assert ("behavior", 265) in native.panel.calls
    assert ("mouse", True) in native.panel.calls
    assert ("hides", False) in native.panel.calls
    assert ("front",) in native.panel.calls

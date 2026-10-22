"""macOS-only native panel policy for the global Gesture Control HUD."""


class MacOSHudPanelController:
    """Applies desktop-wide, non-interactive panel behavior through an injected facade."""

    def __init__(self, native):
        self.native = native
        self.panel = None

    def attach(self, widget):
        self.panel = self.native.panel_for_widget(widget)
        if self.panel is None:
            return False
        self.panel.setLevel_(self.native.status_window_level)
        self.panel.setCollectionBehavior_(self.native.collection_behavior)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setHidesOnDeactivate_(False)
        return True

    def raise_panel(self):
        if self.panel is not None:
            self.panel.orderFrontRegardless()

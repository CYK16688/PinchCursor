import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.hud_state import HudState
from gui.i18n import DEFAULT_LOCALE, set_locale
from gui.overlay import GestureOverlay
from platform_services.macos.hud_panel import MacOSHudPanelController


def setup_function():
    set_locale(DEFAULT_LOCALE)


def test_overlay_is_non_activating_and_transparent_to_mouse_events():
    app = QApplication.instance() or QApplication([])
    overlay = GestureOverlay()
    try:
        flags = overlay.windowFlags()
        assert flags & Qt.FramelessWindowHint
        assert flags & Qt.Tool
        assert flags & Qt.WindowStaysOnTopHint
        assert overlay.testAttribute(Qt.WA_TranslucentBackground)
        assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert overlay.testAttribute(Qt.WA_ShowWithoutActivating)
    finally:
        overlay.close()


def test_overlay_delegates_raise_to_native_panel_when_enabled():
    class Panel:
        def setLevel_(self, _value): pass
        def setCollectionBehavior_(self, _value): pass
        def setIgnoresMouseEvents_(self, _value): pass
        def setHidesOnDeactivate_(self, _value): pass
        def orderFrontRegardless(self): self.raised = True

    class Native:
        status_window_level = 25
        collection_behavior = 265
        def panel_for_widget(self, _widget): return self.panel

    app = QApplication.instance() or QApplication([])
    native = Native(); native.panel = Panel(); native.panel.raised = False
    overlay = GestureOverlay()
    try:
        overlay.enable_macos_global_panel(native)
        overlay.show_state("pointer", (100, 100))
        assert native.panel.raised is True
    finally:
        overlay.close()


def test_overlay_maps_every_hud_state_to_a_consistent_outline_icon():
    app = QApplication.instance() or QApplication([])
    overlay = GestureOverlay()
    try:
        expected = {
            "pointer": "point",
            "locking": "pinch",
            "clicked": "pinch",
            "dragging": "grab",
            "secondary_click": "peace",
            "volume": "thumb_volume",
        }

        for state, icon_name in expected.items():
            assert overlay.icon_name_for_state(state) == icon_name
    finally:
        overlay.close()


def test_overlay_translates_a_visible_persistent_state_without_changing_hud_state():
    from gui.i18n import set_locale

    app = QApplication.instance() or QApplication([])
    overlay = GestureOverlay()
    try:
        overlay.show_state("pointer", (100, 100))
        assert overlay.label.text() == "指针已激活"

        set_locale("en_US")
        overlay.retranslate_ui()

        assert overlay.label.text() == "Pointer active"
        assert overlay.current_state == "pointer"
    finally:
        overlay.close()

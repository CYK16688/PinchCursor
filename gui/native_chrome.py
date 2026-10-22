"""Native macOS window chrome that Qt cannot express through style sheets.

Qt styles the content area, but the title bar is drawn by AppKit and follows the
system appearance, not the app's palette. A light title bar above a dark console
reads as two windows glued together, so the app opts the window into dark aqua.
Every call is best-effort: on other platforms, or without pyobjc, the window
simply keeps the system chrome.
"""

from __future__ import annotations

import sys


def apply_dark_titlebar(window) -> bool:
    """Ask AppKit to draw this window's title bar in dark aqua.

    Returns True when the appearance was applied. Never raises: chrome is
    cosmetic and must not be able to stop the app from starting.
    """
    if sys.platform != "darwin":
        return False
    try:
        from PySide6.QtGui import QGuiApplication

        # Only the cocoa platform plugin hands back a real NSView. Under
        # offscreen/minimal, winId() is a dummy pointer and the objc call
        # segfaults before any exception can be raised.
        if QGuiApplication.platformName() != "cocoa":
            return False
        handle = int(window.winId())
        if handle == 0:
            return False

        import objc
        from AppKit import NSAppearance, NSAppearanceNameDarkAqua

        # Qt's winId() is the backing NSView on macOS; its window() is the
        # NSWindow whose appearance drives the title bar.
        view = objc.objc_object(c_void_p=handle)
        native_window = view.window()
        if native_window is None:
            return False
        appearance = NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua)
        if appearance is None:
            return False
        native_window.setAppearance_(appearance)
        return True
    except Exception:
        return False

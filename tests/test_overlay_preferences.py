import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.overlay import GestureOverlay


def test_overlay_applies_feedback_scale_and_opacity():
    app = QApplication.instance() or QApplication([])
    overlay = GestureOverlay()
    try:
        overlay.set_feedback_preferences(opacity=0.82, scale=1.15)

        assert overlay.windowOpacity() == pytest.approx(0.82, abs=0.01)
        assert overlay.size().width() == 193
    finally:
        overlay.close()

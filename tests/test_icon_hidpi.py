"""Icons must rasterise at the display's device pixel ratio.

Every generated pixmap used to be built at ratio 1 and upscaled by Qt, so all
glyphs, the app mark and the preview placeholder looked soft next to the 13 px
text on a Retina display — which on a macOS-only product is essentially every
display.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui import icons


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_a_ratio_two_pixmap_carries_twice_the_device_pixels(app):
    pixmap = icons.pixmap("sliders", "#FFFFFF", 16, ratio=2.0)
    assert (pixmap.width(), pixmap.height()) == (32, 32)
    assert pixmap.devicePixelRatio() == pytest.approx(2.0)
    # Qt still lays it out at the requested logical size.
    logical = pixmap.deviceIndependentSize()
    assert (logical.width(), logical.height()) == (16.0, 16.0)


def test_the_app_mark_scales_its_device_pixels(app):
    mark = icons.app_mark(30, ratio=2.0)
    assert mark.width() == 60
    assert mark.deviceIndependentSize().toTuple() == (30.0, 30.0)


def test_padded_pixmaps_keep_their_logical_footprint(app):
    padded = icons.padded_pixmap("sliders", "#FFFFFF", 15, 4, ratio=2.0)
    assert padded.width() == 38
    assert padded.deviceIndependentSize().width() == pytest.approx(19.0)


def test_the_ratio_is_never_below_one(app):
    pixmap = icons.pixmap("sliders", "#FFFFFF", 16, ratio=0.5)
    assert pixmap.devicePixelRatio() >= 1.0

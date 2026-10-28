"""Window-level wiring for pointer mapping: config, anchoring, multi-display."""

import pathlib
import tempfile

import pytest
from PySide6.QtGui import QCursor
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from core.pointer_mapping import AbsoluteMapper, RelativeMapper, ScreenBounds
from gui.main_window import MainWindow
from utils.config_manager import ConfigManager

FRAME = (640, 480)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(bounds=(0, 0, 1000, 500), mapper=None):
    window = MainWindow.__new__(MainWindow)
    window.screen_bounds = ScreenBounds(*bounds)
    window.pointer_mapper = mapper or AbsoluteMapper()
    window._pointer_anchor_pending = True
    return window


def test_computed_bounds_cover_every_attached_display(app):
    bounds = MainWindow._compute_screen_bounds()

    union = QApplication.screens()[0].geometry()
    for screen in QApplication.screens()[1:]:
        union = union.united(screen.geometry())
    assert (bounds.x, bounds.y, bounds.width, bounds.height) == (
        union.x(), union.y(), union.width(), union.height()
    )


def test_absolute_pointer_maps_frame_centre_to_screen_centre(app):
    window = _window()

    assert MainWindow._map_pointer(window, (320, 240), FRAME) == (500, 250)


def test_relative_mode_does_not_jump_on_the_first_frame(app):
    window = _window(mapper=RelativeMapper(gain=2.0))
    start = QCursor.pos()

    first = MainWindow._map_pointer(window, (320, 240), FRAME)

    assert first == (start.x(), start.y())
    assert window._pointer_anchor_pending is False


def test_relative_mode_moves_by_displacement_times_gain(app):
    window = _window(mapper=RelativeMapper(gain=2.0))
    MainWindow._map_pointer(window, (320, 240), FRAME)  # anchor

    moved = MainWindow._map_pointer(window, (384, 240), FRAME)  # +10 % of width

    # 10 % of 1000 px at gain 2 = 200 px to the right of the anchor.
    assert moved[0] - window.screen_bounds.x == pytest.approx(
        QCursor.pos().x() - window.screen_bounds.x + 200, abs=1
    )


def test_reanchor_after_hand_returns_uses_actual_cursor_even_if_mouse_moved(app, monkeypatch):
    window = _window(mapper=RelativeMapper(gain=2.0))
    MainWindow._map_pointer(window, (320, 240), FRAME)
    moved = MainWindow._map_pointer(window, (500, 400), FRAME)
    window._last_cursor_pos = moved

    # Hand leaves the frame; the caller flags a pending re-anchor.
    window._pointer_anchor_pending = True
    monkeypatch.setattr(QCursor, "pos", lambda: QPoint(210, 160))
    reanchored = MainWindow._map_pointer(window, (100, 100), FRAME)

    assert reanchored == (210, 160)


def test_refresh_builds_a_relative_mapper_from_configuration(app):
    config = ConfigManager(config_path=pathlib.Path(tempfile.mkdtemp()) / "settings.json")
    config.set("pointer_mapping", "mode", "relative")
    config.set("pointer_mapping", "gain", 3.0)
    window = MainWindow.__new__(MainWindow)
    window.config = config

    MainWindow._refresh_pointer_mapping(window)

    assert isinstance(window.pointer_mapper, RelativeMapper)
    assert window.pointer_mapper.gain == 3.0
    assert window._pointer_anchor_pending is True


def test_refresh_defaults_to_absolute_on_bad_configuration(app):
    config = ConfigManager(config_path=pathlib.Path(tempfile.mkdtemp()) / "settings.json")
    config.set("pointer_mapping", "mode", "relative")
    config.set("pointer_mapping", "gain", "not-a-number")
    window = MainWindow.__new__(MainWindow)
    window.config = config

    MainWindow._refresh_pointer_mapping(window)

    assert isinstance(window.pointer_mapper, AbsoluteMapper)

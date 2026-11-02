"""Guard the methods MainWindow shares with ControlEngine by reference."""

import pytest

from core.control_engine import ControlEngine
from gui import main_window

SHARED = (
    "_record_candidates",
    "_snap_cursor_position",
    "_freeze_pointer_for_pinch",
    "_restore_static_templates",
    "_clear_dynamic_shortcut_observation",
)


@pytest.mark.parametrize("name", SHARED)
def test_window_method_is_the_engine_method(name):
    assert getattr(main_window.MainWindow, name) is getattr(ControlEngine, name)
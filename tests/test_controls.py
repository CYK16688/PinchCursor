"""One control per job: switches for features, checkboxes for sets, segments for choices.

The surface used a checkbox for all three, which is why configuring the app felt
heavier than it is — a column of checkboxes gives no hint whether you are
turning on a feature, picking items out of a set, or choosing between mutually
exclusive modes.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui.controls import SegmentedControl, ToggleSwitch


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ── ToggleSwitch ─────────────────────────────────────────────────────────────
def test_a_switch_is_checkable_and_starts_off(app):
    switch = ToggleSwitch("Usage data")
    assert switch.isCheckable()
    assert switch.isChecked() is False


def test_toggling_a_switch_animates_the_knob_to_the_far_end(app):
    switch = ToggleSwitch("Usage data")
    switch.setChecked(True)
    assert switch.get_knob_offset() == pytest.approx(1.0)
    switch.setChecked(False)
    assert switch.get_knob_offset() == pytest.approx(0.0)


def test_a_switch_can_take_keyboard_focus(app):
    """It is a real control, so it has to be reachable by Tab."""
    from PySide6.QtCore import Qt

    switch = ToggleSwitch("Usage data")
    assert switch.focusPolicy() != Qt.NoFocus


def test_a_switch_reports_a_size_that_fits_its_label(app):
    short = ToggleSwitch("On")
    long = ToggleSwitch("Record usage data on this machine")
    assert long.sizeHint().width() > short.sizeHint().width()


# ── SegmentedControl ─────────────────────────────────────────────────────────
def test_a_segment_control_starts_on_the_first_option(app):
    control = SegmentedControl()
    control.addItem("Absolute", "absolute")
    control.addItem("Relative", "relative")
    assert control.currentIndex() == 0
    assert control.currentData() == "absolute"


def test_selecting_a_segment_is_exclusive(app):
    control = SegmentedControl()
    control.addItem("A", "a")
    control.addItem("B", "b")
    control.addItem("C", "c")

    control.setCurrentData("c")

    assert control.currentData() == "c"
    checked = [button.isChecked() for button in control._buttons]
    assert checked == [False, False, True]


def test_a_segment_control_emits_the_expected_api_like_a_combo(app):
    """It replaces QComboBox at call sites, so the accessors must match."""
    control = SegmentedControl()
    control.addItem("A", "a")
    control.addItem("B", "b")

    assert control.count() == 2
    assert control.findData("b") == 1
    assert control.itemData(0) == "a"

    control.setItemText(1, "Bee")
    assert control._buttons[1].text() == "Bee"


def test_changing_the_segment_emits_the_change_signal(app):
    control = SegmentedControl()
    control.addItem("A", "a")
    control.addItem("B", "b")
    seen = []
    control.currentIndexChanged.connect(seen.append)

    control.setCurrentIndex(1)

    assert seen == [1]


def test_segment_corner_positions_follow_the_list(app):
    control = SegmentedControl()
    control.addItem("A", "a")
    control.addItem("B", "b")
    control.addItem("C", "c")

    positions = [button.property("position") for button in control._buttons]
    assert positions == ["first", "middle", "last"]


def test_a_single_segment_gets_both_rounded_corners(app):
    control = SegmentedControl()
    control.addItem("Only", "only")
    assert control._buttons[0].property("position") == "only"


def test_disabling_a_segment_control_disables_every_segment(app):
    control = SegmentedControl()
    control.addItem("A", "a")
    control.addItem("B", "b")

    control.setEnabled(False)

    assert all(not button.isEnabled() for button in control._buttons)

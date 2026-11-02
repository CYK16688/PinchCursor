"""One source for the power table and the mode thresholds that select it."""

import pytest

from core import power_policy


def test_every_mode_has_a_frame_spacing():
    assert set(power_policy.FRAME_SECONDS) == {"normal", "low", "sleep", "deep_sleep"}


def test_deeper_modes_wait_longer_between_passes():
    table = power_policy.FRAME_SECONDS
    assert table["normal"] == 0.0
    assert 0 < table["low"] < table["sleep"] < table["deep_sleep"] <= 1.0


def test_thresholds_are_ordered_and_positive():
    assert 0 < power_policy.LOW_AFTER < power_policy.SLEEP_AFTER < power_policy.DEEP_AFTER


@pytest.mark.parametrize(
    "frames, ir_present, expected",
    [
        (0, None, "normal"),
        (power_policy.LOW_AFTER, None, "normal"),
        (power_policy.LOW_AFTER + 1, None, "low"),
        (power_policy.SLEEP_AFTER + 1, None, "sleep"),
        (power_policy.DEEP_AFTER + 1, None, "sleep"),
        (power_policy.DEEP_AFTER + 1, True, "sleep"),
        (power_policy.DEEP_AFTER + 1, False, "deep_sleep"),
    ],
)
def test_mode_for_follows_the_thresholds(frames, ir_present, expected):
    assert power_policy.mode_for(frames, ir_present) == expected


def test_deep_sleep_needs_an_explicit_absent_sample():
    frames = power_policy.DEEP_AFTER + 1
    assert power_policy.mode_for(frames, None) == "sleep"
    assert power_policy.mode_for(frames, True) == "sleep"
    assert power_policy.mode_for(frames, False) == "deep_sleep"
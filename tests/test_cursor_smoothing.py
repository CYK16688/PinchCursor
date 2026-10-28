"""The smoothing dial must actually smooth, and only to a bounded degree.

The persisted ``smoothing`` preference was wired to the 1€ filter's ``beta``,
the high-speed term. Measured on this machine, dragging it end to end moved a
still hand's jitter from 10 px to 13 px — in the wrong direction — while the
parameter that governs resting jitter, ``mincutoff``, was pinned to a constant.
Users were told a dial existed and it did nothing.
"""

import pytest

from utils.smoothing import (
    CURSOR_SMOOTHING_BETA,
    MINCUTOFF_CEILING,
    MINCUTOFF_FLOOR,
    SM00THING_DEFAULT,
    CursorSmoother,
    mincutoff_for_smoothing,
)


def test_the_default_preference_keeps_the_default_cutoff():
    """Existing setups must not change feel just because the wiring was fixed."""
    assert mincutoff_for_smoothing(SM00THING_DEFAULT) == pytest.approx(1.5)
    assert mincutoff_for_smoothing(SM00THING_DEFAULT, default=1.2) == pytest.approx(1.2)


def test_more_smoothing_means_a_lower_cutoff():
    """The dial has to move the quantity that actually controls jitter."""
    least = mincutoff_for_smoothing(0.001)
    middle = mincutoff_for_smoothing(0.005)
    most = mincutoff_for_smoothing(0.020)

    assert least > middle > most


def test_the_dial_spans_a_meaningful_range():
    """A dial that moves mincutoff by 0.05 would not be worth showing."""
    span = mincutoff_for_smoothing(0.001) - mincutoff_for_smoothing(0.020)
    assert span > 1.0


def test_the_cutoff_stays_inside_the_useful_band():
    for preference in (0.0, 0.0001, 0.001, 0.005, 0.020, 0.5, 99):
        cutoff = mincutoff_for_smoothing(preference)
        assert MINCUTOFF_FLOOR <= cutoff <= MINCUTOFF_CEILING


@pytest.mark.parametrize("bad", [None, "x", object(), float("nan"), float("inf")])
def test_a_corrupt_preference_falls_back_instead_of_breaking_the_cursor(bad):
    assert mincutoff_for_smoothing(bad) == pytest.approx(1.5)


def test_beta_is_no_longer_derived_from_the_dial():
    """Beta is the motion term; exposing it is what made the dial misleading."""
    smoother = CursorSmoother(mincutoff=mincutoff_for_smoothing(0.020), beta=CURSOR_SMOOTHING_BETA)
    assert smoother.filter_x.beta == CURSOR_SMOOTHING_BETA


def test_the_measured_jitter_actually_improves_across_the_dial():
    """End-to-end: a still hand must jitter less at the smoothing end."""
    from core.pointer_mapping import AbsoluteMapper, ScreenBounds
    import random

    bounds = ScreenBounds(0, 0, 2560, 1440)
    mapper = AbsoluteMapper()

    def jitter(preference):
        random.seed(7)
        smoother = CursorSmoother(mincutoff=mincutoff_for_smoothing(preference))
        points, now = [], 0.0
        for _ in range(90):
            x = 320.0 + random.gauss(0, 2.0)
            y = 240.0 + random.gauss(0, 2.0)
            mapped = mapper.map((x, y), (640, 480), bounds)
            points.append(smoother.smooth(mapped[0], mapped[1], timestamp=now))
            now += 1 / 30
        tail = points[-40:]
        xs = [p[0] for p in tail]
        ys = [p[1] for p in tail]
        return max(max(xs) - min(xs), max(ys) - min(ys))

    assert jitter(0.020) < jitter(0.001)


@pytest.mark.parametrize("dead_zone", [0, 8])
@pytest.mark.parametrize("start,target", [(100.0, 2559.0), (2559.0, 100.0)])
def test_a_fast_target_change_never_overshoots(dead_zone, start, target):
    smoother = CursorSmoother(dead_zone=dead_zone)
    smoother.smooth(start, 100.0, timestamp=0.0)
    for index in range(1, 31):
        x, _ = smoother.smooth(target, 100.0, timestamp=index / 30)
        assert min(start, target) <= x <= max(start, target)

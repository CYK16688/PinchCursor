"""Jitter attenuation must preserve sustained small corrections and endpoints.

These are synthetic control replays, not camera or user accuracy measurements.
"""

import math
import random

import pytest

from core.pointer_mapping import AbsoluteMapper, ScreenBounds
from utils.smoothing import CURSOR_SMOOTHING_BETA, DEFAULT_DEAD_ZONE, CursorSmoother

BOUNDS = ScreenBounds(0, 0, 2560, 1440)


def _jitter(dead_zone, sigma=1.92, frames=150):
    """Screen-point spread of a still hand, after mapping and smoothing."""
    random.seed(1)
    smoother = CursorSmoother(
        mincutoff=1.5, beta=CURSOR_SMOOTHING_BETA, dead_zone=dead_zone
    )
    mapper = AbsoluteMapper()
    points = []
    now = 0.0
    for _ in range(frames):
        x = 320.0 + random.gauss(0, sigma)
        y = 240.0 + random.gauss(0, sigma)
        mapped = mapper.map((x, y), (640, 480), BOUNDS)
        points.append(smoother.smooth(mapped[0], mapped[1], timestamp=now))
        now += 1 / 30
    tail = points[-60:]
    xs = [p[0] for p in tail]
    ys = [p[1] for p in tail]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def test_the_default_dead_zone_removes_nearly_all_resting_jitter():
    assert _jitter(DEFAULT_DEAD_ZONE) <= 2


def test_without_a_dead_zone_a_still_hand_wobbles():
    """The baseline this feature exists to fix."""
    assert _jitter(0) >= 10


def test_a_larger_zone_is_steadier():
    assert _jitter(12) <= _jitter(4)


def test_slow_precise_movement_still_travels():
    """A dead zone must not eat small deliberate moves."""
    def travel(dead_zone):
        smoother = CursorSmoother(
            mincutoff=1.5, beta=CURSOR_SMOOTHING_BETA, dead_zone=dead_zone
        )
        mapper = AbsoluteMapper()
        start = None
        now = 0.0
        moved = None
        for step in range(150):
            x = 320.0 + step * 1.0  # 1 px per frame: a slow, careful move
            mapped = mapper.map((x, 240.0), (640, 480), BOUNDS)
            position = smoother.smooth(mapped[0], mapped[1], timestamp=now)
            now += 1 / 30
            if start is None:
                start = position
            moved = position
        return moved[0] - start[0]

    hand_travel = (1.0 / 640) * BOUNDS.width * 150
    for zone in (0, 4, 8, 12):
        assert travel(zone) >= hand_travel * 0.85, zone


def test_the_pointer_never_jumps_more_than_the_hand_moved():
    """The anchor advances only by the excess, so there is no visible step."""
    smoother = CursorSmoother(mincutoff=1.5, beta=CURSOR_SMOOTHING_BETA, dead_zone=8.0)
    now = 0.0
    previous = None
    for step in range(60):
        x = 320.0 + step * 0.5
        position = smoother.smooth(x * 4, 240.0 * 4, timestamp=now)
        now += 1 / 30
        if previous is not None:
            assert abs(position[0] - previous[0]) <= 12
        previous = position


def test_nonsense_dead_zones_are_clamped_rather_than_breaking_the_cursor():
    for bad in (None, "x", object(), float("nan"), float("inf"), -5):
        smoother = CursorSmoother(dead_zone=bad)
        assert smoother.dead_zone == 0.0
        assert smoother.smooth(100, 100) is not None


def test_resetting_clears_the_anchor():
    """A re-anchor (tracking loss, mode switch) must not snap from a stale point."""
    smoother = CursorSmoother(mincutoff=1.5, beta=CURSOR_SMOOTHING_BETA, dead_zone=8.0)
    smoother.smooth(100, 100, timestamp=0.0)
    smoother.smooth(101, 100, timestamp=1 / 30)
    smoother.reset()

    # After a reset the first sample re-establishes the anchor, so a far-away
    # position is adopted without a jump from the old one.
    assert smoother.smooth(900, 900, timestamp=1.0) == (900, 900)


def test_the_dead_zone_does_not_leak_between_frames_of_a_fast_move():
    """Fast moves exceed the zone on every frame, so they track continuously."""
    smoother = CursorSmoother(mincutoff=1.5, beta=CURSOR_SMOOTHING_BETA, dead_zone=8.0)
    now = 0.0
    positions = []
    for step in range(20):
        positions.append(smoother.smooth(100 + step * 40, 200, timestamp=now))
        now += 1 / 30

    assert positions[-1][0] > positions[0][0] + 400


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("distance", [1.0, -1.0, 4.0, 8.0])
def test_small_sustained_corrections_reach_the_target(fps, distance):
    smoother = CursorSmoother()
    for index in range(fps):
        smoother.smooth(100.0, 100.0, timestamp=index / fps)
    # The correction is smaller than the old permanent eight-point dead zone.
    for index in range(1, int(fps * 0.6) + 1):
        position = smoother.smooth(100.0 + distance, 100.0, timestamp=1.0 + index / fps)
    assert position == pytest.approx((100.0 + distance, 100.0), abs=0.25)


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_small_correction_with_bounded_observation_noise_still_settles(fps):
    smoother = CursorSmoother()
    smoother.smooth(100.0, 100.0, timestamp=0.0)
    for index in range(1, fps + 1):
        noise = 0.1 if index % 2 else -0.1
        position = smoother.smooth(104.0 + noise, 100.0 - noise, timestamp=index / fps)
    assert position == pytest.approx((104.0, 100.0), abs=0.3)


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("target", [(0, 0), (999, 499)])
def test_clamped_screen_edges_are_reachable_after_settling(fps, target):
    bounds = ScreenBounds(0, 0, 1000, 500)
    smoother = CursorSmoother()
    smoother.smooth(500, 250, timestamp=0.0)
    for index in range(1, fps + 1):
        # The mapper cannot provide coordinates beyond the screen to make up
        # for a dead-zone offset; the filtered endpoint itself must converge.
        position = smoother.smooth(*bounds.clamp_float(*target), timestamp=index / fps)
    assert bounds.clamp(*position) == target


def test_one_frame_offset_does_not_turn_into_a_small_correction():
    smoother = CursorSmoother()
    for index in range(10):
        smoother.smooth(100, 100, timestamp=index / 30)
    smoother.smooth(104, 100, timestamp=10 / 30)
    positions = [smoother.smooth(100, 100, timestamp=index / 30) for index in range(11, 25)]
    assert max(abs(position[0] - 100) for position in positions) < 0.25

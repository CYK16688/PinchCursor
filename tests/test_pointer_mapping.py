"""Pointer mapping: absolute vs relative (clutch) and multi-display bounds."""

import pytest

from core.pointer_mapping import AbsoluteMapper, RelativeMapper, ScreenBounds

FRAME = (640, 480)


def test_absolute_maps_frame_corners_onto_the_screen_rectangle():
    mapper = AbsoluteMapper()
    bounds = ScreenBounds(0, 0, 1000, 500)

    assert mapper.map((0, 0), FRAME, bounds) == (0, 0)
    assert mapper.map((320, 240), FRAME, bounds) == (500, 250)
    assert mapper.map((640, 480), FRAME, bounds) == (999, 499)


def test_absolute_respects_a_negative_origin_for_a_left_hand_display():
    # A second display placed to the left of the main one has x < 0.
    bounds = ScreenBounds(-1200, 0, 1200, 800)
    mapper = AbsoluteMapper()

    assert mapper.map((0, 0), FRAME, bounds) == (-1200, 0)
    assert mapper.map((640, 480), FRAME, bounds) == (-1, 799)


def test_absolute_unmap_is_the_inverse_of_map():
    bounds = ScreenBounds(100, 50, 800, 600)
    mapper = AbsoluteMapper()

    screen = mapper.map((160, 120), FRAME, bounds)
    frame = mapper.unmap(screen, FRAME, bounds)

    assert frame == (160, 120)


def test_absolute_rejects_degenerate_input_instead_of_raising():
    mapper = AbsoluteMapper()
    bounds = ScreenBounds(0, 0, 100, 100)

    assert mapper.map(None, FRAME, bounds) is None
    assert mapper.map((float("nan"), 0), FRAME, bounds) is None
    assert mapper.map((10, 10), (0, 0), bounds) is None


def test_relative_starts_at_the_cursor_without_jumping():
    mapper = RelativeMapper(gain=2.0)
    bounds = ScreenBounds(0, 0, 1000, 500)

    first = mapper.map((320, 240), FRAME, bounds)

    assert first == (500, 250)


def test_relative_displacement_scales_with_gain():
    bounds = ScreenBounds(0, 0, 1000, 500)
    for gain, expected in ((1.0, 600), (2.0, 700), (3.0, 800)):
        mapper = RelativeMapper(gain=gain)
        mapper.begin((320, 240), FRAME, bounds, cursor=(500, 250))

        # 10 % of the frame to the right = 100 px at gain 1.
        assert mapper.map((384, 240), FRAME, bounds)[0] == expected


def test_relative_clamps_inside_the_display_union():
    mapper = RelativeMapper(gain=4.0)
    bounds = ScreenBounds(0, 0, 1000, 500)
    mapper.begin((320, 240), FRAME, bounds, cursor=(500, 250))

    assert mapper.map((640, 480), FRAME, bounds) == (999, 499)
    assert mapper.map((0, 0), FRAME, bounds) == (0, 0)


def test_relative_reanchors_after_reset_without_moving_the_cursor():
    mapper = RelativeMapper(gain=2.0)
    bounds = ScreenBounds(0, 0, 1000, 500)
    mapper.begin((100, 100), FRAME, bounds, cursor=(200, 200))

    mapper.reset()
    after_reset = mapper.map((500, 400), FRAME, bounds)

    # A new anchor starts from the display centre, not the old cursor.
    assert after_reset == (500, 250)


def test_relative_handles_a_negative_origin():
    bounds = ScreenBounds(-1000, -200, 1000, 800)
    mapper = RelativeMapper(gain=1.0)
    mapper.begin((320, 240), FRAME, bounds, cursor=(-500, 200))

    # 96 px of 480 = 20 % of the frame, i.e. 160 px of an 800 px tall union.
    assert mapper.map((320, 336), FRAME, bounds) == (-500, 360)


def test_relative_survives_a_lost_frame_without_moving():
    bounds = ScreenBounds(0, 0, 1000, 500)
    mapper = RelativeMapper()
    mapper.begin((320, 240), FRAME, bounds, cursor=(400, 200))

    assert mapper.map(None, FRAME, bounds) is None
    # The anchor is still intact, so the next good frame continues from it.
    assert mapper.map((320, 240), FRAME, bounds) == (400, 200)


def test_bounds_reject_a_degenerate_rectangle():
    with pytest.raises(ValueError):
        ScreenBounds(0, 0, 0, 500)


def test_gain_must_be_positive_and_finite():
    with pytest.raises(ValueError):
        RelativeMapper(gain=0)
    with pytest.raises(ValueError):
        RelativeMapper(gain=float("inf"))

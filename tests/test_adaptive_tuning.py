"""The bounded tuning rules: what moves, how far, and on what evidence."""

import pytest

from core.adaptive_tuning import (
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    MIN_CLICKS,
    RADIUS_MAX,
    RADIUS_MIN,
    tune_snapping,
)


def test_thin_evidence_holds_every_value():
    tuning = tune_snapping(
        max_snap_distance=24.0,
        min_confidence=0.55,
        clicks=MIN_CLICKS - 1,
        misses=20,
        snaps=10,
        mean_snap_distance=22.0,
    )

    assert tuning.changed is False
    assert tuning.reason == "insufficient_evidence"
    assert tuning.max_snap_distance == 24.0
    assert tuning.min_confidence == 0.55
    assert tuning.miss_rate is None


def test_reaching_too_far_narrows_the_radius_and_raises_the_floor():
    # 12 of 50 clicks were re-aimed, and the snaps averaged 35 px out of a 40 px
    # radius: the assist is grabbing from the edge of its reach.
    tuning = tune_snapping(
        max_snap_distance=40.0,
        min_confidence=0.55,
        clicks=50,
        misses=12,
        snaps=25,
        mean_snap_distance=35.0,
    )

    assert tuning.changed is True
    assert tuning.reason == "over_reach"
    assert tuning.max_snap_distance == pytest.approx(34.0)
    assert tuning.min_confidence == pytest.approx(0.58)
    assert tuning.miss_rate == pytest.approx(0.24)


def test_shallow_ambiguous_snaps_move_only_the_confidence_floor():
    # Same miss rate, but snaps land well inside the radius: the problem is two
    # neighbours sharing the probability mass, not reach.
    tuning = tune_snapping(
        max_snap_distance=40.0,
        min_confidence=0.55,
        clicks=50,
        misses=12,
        snaps=25,
        mean_snap_distance=8.0,
    )

    assert tuning.changed is True
    assert tuning.reason == "ambiguous_targets"
    assert tuning.max_snap_distance == 40.0
    assert tuning.min_confidence == pytest.approx(0.58)


def test_clean_clicks_relax_the_floor_but_never_widen_the_radius():
    tuning = tune_snapping(
        max_snap_distance=32.0,
        min_confidence=0.55,
        clicks=120,
        misses=2,
        snaps=40,
        mean_snap_distance=6.0,
    )

    assert tuning.changed is True
    assert tuning.reason == "clean_clicks"
    assert tuning.max_snap_distance == 32.0
    assert tuning.min_confidence == pytest.approx(0.52)


def test_a_rate_inside_the_band_changes_nothing():
    tuning = tune_snapping(
        max_snap_distance=32.0,
        min_confidence=0.55,
        clicks=60,
        misses=6,
        snaps=10,
        mean_snap_distance=20.0,
    )

    assert tuning.changed is False
    assert tuning.reason == "within_band"
    assert tuning.max_snap_distance == 32.0
    assert tuning.min_confidence == 0.55


def test_values_are_clamped_into_the_supported_range():
    low = tune_snapping(max_snap_distance=2.0, min_confidence=0.1, clicks=0, misses=0)
    high = tune_snapping(max_snap_distance=500.0, min_confidence=0.99, clicks=0, misses=0)

    assert low.max_snap_distance == RADIUS_MIN
    assert low.min_confidence == CONFIDENCE_MIN
    assert high.max_snap_distance == RADIUS_MAX
    assert high.min_confidence == CONFIDENCE_MAX


def test_the_floor_stops_at_its_ceiling():
    tuning = tune_snapping(
        max_snap_distance=40.0,
        min_confidence=CONFIDENCE_MAX,
        clicks=80,
        misses=30,
        snaps=30,
        mean_snap_distance=10.0,
    )

    assert tuning.min_confidence == CONFIDENCE_MAX
    assert tuning.changed is False


def test_the_radius_stops_at_its_floor():
    tuning = tune_snapping(
        max_snap_distance=RADIUS_MIN,
        min_confidence=0.60,
        clicks=80,
        misses=30,
        snaps=30,
        mean_snap_distance=RADIUS_MIN,
    )

    assert tuning.max_snap_distance == RADIUS_MIN
    assert tuning.min_confidence == pytest.approx(0.63)
    assert tuning.changed is True


def test_malformed_input_holds_instead_of_raising():
    tuning = tune_snapping(
        max_snap_distance=None,
        min_confidence="0.55",
        clicks=100,
        misses=10,
    )

    assert tuning.changed is False
    assert tuning.reason == "invalid_parameters"


def test_misses_are_capped_at_the_click_count():
    tuning = tune_snapping(
        max_snap_distance=30.0,
        min_confidence=0.60,
        clicks=10,
        misses=99,
        snaps=0,
        mean_snap_distance=None,
    )

    assert tuning.misses == 10
    assert tuning.miss_rate is None  # still below the evidence floor

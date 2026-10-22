"""Episode labels: the only place the guard can learn to be wrong."""

from core.hand_dynamics import DynamicAssessment
from core.transition_episodes import PinchEpisodeTracker


def _assessment(*, transition=False, ratio=0.2, others=2.4):
    return DynamicAssessment(
        pinch_ratio=ratio,
        pinch_confidence=0.8,
        transition=transition,
        others_rate=-0.2,
        wrist_speed=0.4,
        others_distance=others,
        pinch_slope=-0.5,
    )


def test_a_clicked_pinch_is_a_positive_episode_immediately():
    tracker = PinchEpisodeTracker()
    assert tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0) == []

    tracker.note_action("left_click", 1.1)
    records = tracker.observe(gesture="point", assessment=_assessment(), now=1.3)

    assert len(records) == 1
    assert records[0].label == 1
    assert records[0].outcome == "acted"
    assert len(records[0].features) == 6


def test_a_drag_counts_as_acting_too():
    tracker = PinchEpisodeTracker()
    tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0)
    tracker.note_action("drag_start", 1.1)

    records = tracker.observe(gesture="point", assessment=_assessment(), now=1.4)

    assert records[0].label == 1


def test_a_quick_revert_is_negative_but_waits_for_a_retry():
    tracker = PinchEpisodeTracker(retry_window=0.55)
    tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0)
    assert tracker.observe(gesture="point", assessment=_assessment(), now=1.1) == []

    records = tracker.observe(gesture="point", assessment=_assessment(), now=1.7)

    assert len(records) == 1
    assert records[0].label == 0
    assert records[0].outcome == "reverted"


def test_coming_back_inside_the_window_flips_the_drop_to_a_retry():
    tracker = PinchEpisodeTracker(retry_window=0.55)
    tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0)
    tracker.observe(gesture="point", assessment=_assessment(), now=1.1)

    records = tracker.observe(gesture="pinch", assessment=_assessment(), now=1.4)

    assert len(records) == 1
    assert records[0].label == 1
    assert records[0].outcome == "retried"


def test_a_rejected_episode_without_a_retry_stays_negative():
    tracker = PinchEpisodeTracker(retry_window=0.55)
    tracker.observe(gesture="pinch", assessment=_assessment(transition=True), now=1.0)

    assert tracker.observe(gesture="point", assessment=_assessment(), now=1.6) == []
    # negatives are held for the retry window, rejection or not
    records = tracker.observe(gesture="point", assessment=_assessment(), now=2.2)

    assert len(records) == 1
    assert records[0].label == 0
    assert records[0].outcome == "rejected"
    assert records[0].rule_rejected is True


def test_a_long_hold_without_an_action_is_not_recorded():
    tracker = PinchEpisodeTracker(revert_window=0.30, retry_window=0.50)
    tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0)

    records = tracker.observe(gesture="point", assessment=_assessment(), now=1.8)

    assert records == []


def test_a_frame_without_a_usable_assessment_does_not_open_an_episode():
    tracker = PinchEpisodeTracker()

    assert tracker.observe(gesture="pinch", assessment=None, now=1.0) == []
    assert tracker.has_open_episode is False


def test_reset_forgets_the_open_episode():
    tracker = PinchEpisodeTracker()
    tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0)
    tracker.reset()

    assert tracker.has_open_episode is False
    assert tracker.observe(gesture="point", assessment=_assessment(), now=1.2) == []


def test_drain_returns_pending_records():
    tracker = PinchEpisodeTracker(retry_window=10.0)
    tracker.observe(gesture="pinch", assessment=_assessment(), now=1.0)
    tracker.observe(gesture="point", assessment=_assessment(), now=1.1)

    drained = tracker.drain()

    assert len(drained) == 1
    assert drained[0].label == 0

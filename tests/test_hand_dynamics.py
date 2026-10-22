"""Causal hand dynamics: pinch confidence and pass-through detection."""

import math

from core.hand_dynamics import HandDynamics


def hand(pinch_ratio, others_ratio, *, wrist=(320.0, 240.0), palm=100.0):
    """Build 21 landmarks with a controlled pinch distance and finger curl.

    ``pinch_ratio`` is thumb-tip to index-tip distance in palm units, and
    ``others_ratio`` is the mean distance from the middle/ring/pinky tips to the
    wrist, also in palm units. Open hand ~1.3, fist ~0.5.
    """
    wrist_x, wrist_y = wrist
    centre = (wrist_x, wrist_y - 1.2 * palm)
    points = [(wrist_x, wrist_y)] + [centre] * 20
    points[9] = (wrist_x, wrist_y - palm)  # middle MCP defines the palm scale
    points[4] = (centre[0] - pinch_ratio * palm / 2, centre[1])
    points[8] = (centre[0] + pinch_ratio * palm / 2, centre[1])
    for index, angle in ((12, -0.5), (16, 0.0), (20, 0.5)):
        points[index] = (
            wrist_x + others_ratio * palm * math.sin(angle),
            wrist_y - others_ratio * palm * math.cos(angle),
        )
    return [(x, y, 0.0) for x, y in points]


def run(sequence, matcher=None, dt=1 / 30):
    matcher = matcher or HandDynamics()
    assessment = None
    now = 0.0
    for landmarks in sequence:
        assessment = matcher.update(landmarks, now)
        now += dt
    return assessment


def test_an_ordinary_pinch_reads_as_intended():
    # Thumb meets index over ~200 ms; the other fingers stay extended.
    sequence = [
        hand(0.8 - 0.55 * (i / 6), 1.30) for i in range(7)
    ]

    assessment = run(sequence)

    assert assessment is not None
    assert assessment.transition is False
    assert assessment.pinch_confidence > 0.7


def test_closing_a_fist_reads_as_a_transition_not_a_click():
    # Both the pinch distance and the rest of the hand collapse together.
    sequence = [
        hand(0.8 - 0.65 * (i / 6), 1.30 - 0.75 * (i / 6)) for i in range(7)
    ]

    assessments = []
    matcher = HandDynamics()
    now = 0.0
    for landmarks in sequence:
        assessments.append(matcher.update(landmarks, now))
        now += 1 / 30

    crossing = [a for a in assessments if a is not None and a.pinch_ratio <= 0.29]
    assert crossing, "the synthetic motion must cross the pinch threshold"
    assert any(a.transition for a in crossing)
    # A transition never carries confidence, so it can never arm a click.
    assert all(a.pinch_confidence == 0.0 for a in crossing if a.transition)


def test_a_still_open_hand_has_no_pinch_confidence():
    sequence = [hand(0.85, 1.30) for _ in range(8)]

    assessment = run(sequence)

    assert assessment is not None
    assert assessment.transition is False
    assert assessment.pinch_confidence < 0.2


def test_a_fast_hand_movement_is_visible_in_the_assessment():
    still = [hand(0.8, 1.30, wrist=(320, 240)) for _ in range(6)]
    moving = [hand(0.8, 1.30, wrist=(320 + 40 * i, 240)) for i in range(6)]

    assert run(still).wrist_speed < 1.0
    assert run(moving).wrist_speed > 5.0


def test_confidence_needs_sustained_pinches_and_drops_when_released():
    matcher = HandDynamics()
    now = 0.0
    held = 0.0
    for _ in range(8):
        held = matcher.update(hand(0.22, 1.30), now).pinch_confidence
        now += 1 / 30

    released = 0.0
    for _ in range(4):
        released = matcher.update(hand(0.85, 1.30), now).pinch_confidence
        now += 1 / 30

    assert held > 0.85
    assert released < 0.4


def test_reset_clears_history_and_confidence():
    matcher = HandDynamics()
    now = 0.0
    for _ in range(6):
        matcher.update(hand(0.2, 1.3), now)
        now += 1 / 30
    assert matcher._confidence > 0.5

    matcher.reset()
    assessment = matcher.update(hand(0.85, 1.3), now)

    assert assessment.pinch_confidence < 0.2


def test_invalid_landmarks_are_ignored():
    matcher = HandDynamics()

    assert matcher.update(None, 0.0) is None
    assert matcher.update([(0.0, 0.0, 0.0)] * 3, 0.0) is None
    assert matcher.update([(float("nan"), 0.0, 0.0)] * 21, 0.0) is None

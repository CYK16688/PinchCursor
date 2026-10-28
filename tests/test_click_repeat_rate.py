"""A pinch that physically opens may end at once.

The stabiliser used to require `exit_threshold` frames (four) of a *different*
label before it would leave the pinch state, even though the pinch has its own
hysteresis (enter 0.29, exit 0.42) and therefore already knows the fingers
opened. Two clicks could not start closer than 233 ms because of that, which
ruled out double-clicks entirely.

The fast path is deliberately gated so it cannot invent clicks:
  * the release must persist for RELEASE_CONFIRM_FRAMES, and
  * it must overshoot the exit threshold by RELEASE_MARGIN.

Without the second gate, a hand holding a pinch right at the boundary produced
phantom clicks under measurement noise (measured: 24 per 10 s at ratio 0.25 with
8 px of noise).
"""

import random

import pytest

from core.gesture_classifier import GestureClassifier

PALM = 100.0
PINCH_FAMILY = {"pinch", "pinch_hold"}
FPS = 30.0


def _hand(pinching: bool, ratio: float = 0.09, noise: float = 0.0, rng=None):
    """21 landmarks with a controlled thumb-to-index distance."""
    offset = ratio * PALM
    if noise and rng is not None:
        offset = max(2.0, offset + rng.gauss(0, noise))
    landmarks = [(320.0, 240.0, 0.0)] * 21
    landmarks = list(landmarks)
    landmarks[0] = (320.0, 340.0, 0.0)
    landmarks[9] = (320.0, 240.0, 0.0)
    landmarks[5] = (250.0, 220.0, 0.0)
    landmarks[6] = (245.0, 185.0, 0.0)
    landmarks[7] = (243.0, 165.0, 0.0)
    landmarks[8] = (242.0, 150.0, 0.0)
    if pinching:
        landmarks[4] = (242.0 + offset, 150.0, 0.0)
    else:
        landmarks[4] = (175.0, 255.0, 0.0)  # well past the exit threshold
    landmarks[10] = (320.0, 200.0, 0.0)
    landmarks[11] = (325.0, 215.0, 0.0)
    landmarks[12] = (330.0, 228.0, 0.0)
    landmarks[13] = (390.0, 215.0, 0.0)
    landmarks[14] = (395.0, 230.0, 0.0)
    landmarks[15] = (400.0, 242.0, 0.0)
    landmarks[16] = (404.0, 252.0, 0.0)
    landmarks[17] = (440.0, 230.0, 0.0)
    landmarks[18] = (443.0, 243.0, 0.0)
    landmarks[19] = (446.0, 254.0, 0.0)
    landmarks[20] = (449.0, 263.0, 0.0)
    return landmarks


def _pinch_runs(release_frames):
    """Classify a hold/release/hold sequence and report how many pinch runs appear."""
    classifier = GestureClassifier()
    now = 0.0
    sequence = [True] * 4 + [False] * release_frames + [True] * 4 + [False] * 10
    runs = 0
    previous = None
    for pinching in sequence:
        stable = classifier.classify(_hand(pinching), timestamp=now)
        if stable != previous:
            if stable in PINCH_FAMILY:
                runs += 1
            previous = stable
        now += 1 / FPS
    return runs


def test_two_clicks_no_longer_need_a_third_of_a_second_apart():
    """The whole point: a quick repeat must register as a second click."""
    assert _pinch_runs(2) == 2, "67 ms of release must already count as a new click"


def test_a_single_released_frame_is_not_enough():
    """One frame could be a dropped detection, not a deliberate opening."""
    assert _pinch_runs(1) == 1


def test_a_held_pinch_is_still_one_click():
    assert _pinch_runs(0) == 1


def test_the_release_streak_resets_on_the_next_pinch():
    classifier = GestureClassifier()
    now = 0.0
    for _ in range(4):
        classifier.classify(_hand(True), timestamp=now)
        now += 1 / FPS
    for _ in range(2):
        classifier.classify(_hand(False), timestamp=now)
        now += 1 / FPS
    assert classifier._pinch_release_streak == 2

    classifier.classify(_hand(True), timestamp=now)
    assert classifier._pinch_release_streak == 0


def test_a_marginal_opening_does_not_take_the_fast_path():
    """A release that barely clears the exit threshold is ambiguous."""
    classifier = GestureClassifier()
    # Just past the exit ratio, not past the margin.
    assert not classifier._release_decisive()
    classifier._release_measure = classifier.pinch_exit_ratio * 1.01
    classifier._release_threshold = classifier.pinch_exit_ratio
    classifier._pinch_release_streak = 5
    assert not classifier._release_decisive()


def test_a_decisive_opening_does_take_the_fast_path():
    classifier = GestureClassifier()
    classifier._release_measure = classifier.pinch_exit_ratio * 1.5
    classifier._release_threshold = classifier.pinch_exit_ratio
    assert classifier._release_decisive()


def test_a_missing_measure_cannot_be_decisive():
    classifier = GestureClassifier()
    classifier._release_measure = None
    classifier._release_threshold = None
    assert not classifier._release_decisive()


def _phantom_clicks(ratio, noise, frames=300, seed=0, warmup=10):
    """A hand holding a pinch must not produce extra clicks."""
    rng = random.Random(seed)
    classifier = GestureClassifier()
    now = 0.0
    extra = 0
    left = False
    for index in range(frames + warmup):
        stable = classifier.classify(
            _hand(True, ratio=ratio, noise=noise, rng=rng), timestamp=now
        )
        now += 1 / FPS
        if index < warmup:
            continue
        if stable in PINCH_FAMILY:
            if left:
                extra += 1
                left = False
        else:
            left = True
    return extra


@pytest.mark.parametrize("ratio", [0.10, 0.20])
def test_a_comfortable_hold_never_fires_a_phantom_click(ratio):
    """Normal pinch pressure is far from the exit threshold and must be silent."""
    total = sum(_phantom_clicks(ratio, noise=8, seed=seed) for seed in range(5))
    assert total == 0


def test_a_hold_right_at_the_boundary_is_noisy_but_rare():
    """Honest bound: a hand resting exactly on the threshold is genuinely ambiguous.

    This is the case the decisive-margin gate exists to keep rare rather than
    eliminate; asserting a hard zero would be a lie about what is measurable.
    """
    per_ten_seconds = sum(
        _phantom_clicks(0.28, noise=8, seed=seed) for seed in range(5)
    ) / 5
    assert per_ten_seconds < 2

"""Trajectory channel, adaptive thresholds, and context-bound motion."""

import math

from core.dynamic_gesture_template import (
    DynamicGestureMatcher,
    DynamicGestureTemplate,
)

# A 21-point hand: wrist at index 0, middle MCP at index 9 (~0.12 palm scale).
BASE = [(0.5 + 0.10 * math.cos(i * 0.6), 0.5 + 0.10 * math.sin(i * 0.6), 0.0) for i in range(21)]
BASE[0] = (0.5, 0.62, 0.0)
BASE[9] = (0.5, 0.50, 0.0)
TIPS = (4, 8, 12, 16, 20)


def swipe(frames=36, start=0.15, end=0.85, y_shift=0.0, backward=False):
    """Translate the hand across the frame, keeping its shape constant."""
    out = []
    for index in range(frames):
        t = index / (frames - 1)
        x = start + (end - start) * (1 - t if backward else t)
        out.append([(px + x, py + y_shift, pz) for px, py, pz in BASE])
    return out


def curl(frames=36):
    """Change the hand shape without moving its wrist."""
    out = []
    for index in range(frames):
        k = 0.5 * math.sin(math.pi * index / frames)
        out.append([
            (x + (0.5 - x) * k, y + (0.62 - y) * k, z) if i in TIPS else (x, y, z)
            for i, (x, y, z) in enumerate(BASE)
        ])
    return out


def test_recording_carries_wrist_displacement_in_palm_units():
    matcher = DynamicGestureMatcher()
    prepared = matcher.prepare_recording(swipe())

    assert prepared is not None
    assert len(prepared[0]) == 65
    # Origin-relative: the first frame is at zero displacement.
    assert prepared[0][63] == 0.0 and prepared[0][64] == 0.0
    # 0.7 of frame width against a 0.12 palm scale.
    assert prepared[-1][63] > 4.0


def test_absolute_position_does_not_change_the_motion():
    matcher = DynamicGestureMatcher()

    left = matcher.prepare_recording(swipe(start=0.10, end=0.60))
    right = matcher.prepare_recording(swipe(start=0.40, end=0.90))

    assert matcher.dtw_distance(left, right) < 1e-6


def test_a_swipe_and_its_reverse_are_different_motions():
    matcher = DynamicGestureMatcher()
    forward = matcher.prepare_recording(swipe())
    backward = matcher.prepare_recording(swipe(backward=True))

    # Well above any accepted threshold (default 0.18); DTW aligns the sweep
    # but the trajectory channel cannot be mirrored, so the two separate.
    assert matcher.dtw_distance(forward, backward) > 0.5


def test_hand_shape_change_is_still_distinguishable_from_a_swipe():
    matcher = DynamicGestureMatcher()
    forward = matcher.prepare_recording(swipe())
    shape = matcher.prepare_recording(curl())

    assert matcher.dtw_distance(forward, shape) > 0.05


def test_a_legacy_63_wide_template_still_matches():
    matcher = DynamicGestureMatcher()
    template = matcher.create_template("legacy", "scroll_up", [swipe()])
    legacy = DynamicGestureTemplate(
        template_id="legacy63",
        name="legacy",
        action="scroll_up",
        samples=tuple(tuple(frame[:63] for frame in sample) for sample in template.samples),
    )

    distance = matcher.distance_to_template(matcher.prepare_recording(swipe()), legacy)

    assert distance == 0.0


def test_suggested_threshold_grows_with_take_variability():
    matcher = DynamicGestureMatcher()
    consistent = [matcher.prepare_recording(swipe()) for _ in range(3)]
    varied = [
        matcher.prepare_recording(swipe(end=0.85)),
        matcher.prepare_recording(swipe(end=0.55)),
    ]

    tight = matcher.suggest_threshold(consistent)
    loose = matcher.suggest_threshold(varied)

    assert tight is not None and loose is not None
    assert tight < loose
    assert 0.06 <= tight and loose <= 0.45


def test_suggested_threshold_needs_two_takes():
    matcher = DynamicGestureMatcher()

    assert matcher.suggest_threshold([]) is None
    assert matcher.suggest_threshold([matcher.prepare_recording(swipe())]) is None


def test_context_binding_filters_at_match_time():
    matcher = DynamicGestureMatcher()
    template = matcher.create_template(
        "bound", "scroll_up", [swipe()], min_motion_energy=0.0, context_category="clickable"
    )
    runtime = matcher.create_runtime_matcher([template])

    assert runtime.ingest(swipe(), active=True, now=1.0, context_category="text_input") is None
    assert runtime.ingest(swipe(), active=True, now=2.0, context_category="clickable") is template


def test_an_unbound_template_matches_in_any_context():
    matcher = DynamicGestureMatcher()
    template = matcher.create_template("global", "scroll_up", [swipe()], min_motion_energy=0.0)
    runtime = matcher.create_runtime_matcher([template])

    assert runtime.ingest(swipe(), active=True, now=1.0, context_category="text_input") is template

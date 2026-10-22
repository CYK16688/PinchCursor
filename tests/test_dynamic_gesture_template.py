from __future__ import annotations

import math

import pytest

from core.dynamic_gesture_template import (
    ALLOWED_DYNAMIC_ACTIONS,
    DynamicGestureMatcher,
    DynamicGestureTemplate,
    is_allowed_dynamic_action,
)


def landmarks(offset_x: float = 0.0, scale: float = 1.0):
    """A non-degenerate 21-landmark hand with a stable palm reference."""
    points = []
    for index in range(21):
        x = offset_x + scale * ((index % 5) * 0.11)
        y = scale * ((index // 5) * 0.09)
        z = scale * ((index % 3) * 0.03)
        points.append((x, y, z))
    points[0] = (offset_x, 0.0, 0.0)  # wrist
    points[9] = (offset_x, scale * 0.25, 0.0)  # middle MCP / palm scale
    return points


def articulate(points, delta_x: float, delta_y: float = 0.0):
    """Move the fingers relative to the wrist while preserving palm scale."""
    moved = list(points)
    for index in (4, 8, 12, 16, 20):
        x, y, z = moved[index]
        moved[index] = (x + delta_x, y + delta_y, z)
    return moved


def translate(points, delta_x: float, delta_y: float = 0.0):
    return [(x + delta_x, y + delta_y, z) for x, y, z in points]


def moving_take(frame_count: int, distance: float = 1.0):
    return [articulate(landmarks(), distance * index / (frame_count - 1)) for index in range(frame_count)]


def translated_take(frame_count: int, distance: float = 1.0):
    return [translate(landmarks(), distance * index / (frame_count - 1)) for index in range(frame_count)]


def test_normalize_is_wrist_relative_and_palm_scale_invariant():
    matcher = DynamicGestureMatcher()

    original = landmarks()
    translated_scaled = landmarks(offset_x=10.0, scale=3.0)

    assert matcher.normalize_frame(original) == matcher.normalize_frame(translated_scaled)


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [(0.0, 0.0, 0.0)] * 20,
        [(0.0, 0.0, 0.0)] * 21,
        [(math.nan, 0.0, 0.0)] + [(0.1, 0.1, 0.0)] * 20,
        [(math.inf, 0.0, 0.0)] + [(0.1, 0.1, 0.0)] * 20,
    ],
)
def test_normalize_rejects_incomplete_degenerate_and_nonfinite_landmarks(invalid):
    assert DynamicGestureMatcher().normalize_frame(invalid) is None


def test_recording_acceptance_resamples_fixed_length_and_rejects_bad_takes():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4, max_recording_frames=12)

    accepted = matcher.prepare_recording(moving_take(6))

    assert accepted is not None
    assert len(accepted) == 8
    # 63 hand-shape dimensions plus wrist displacement from the segment origin.
    assert all(len(frame) == 65 for frame in accepted)
    assert matcher.prepare_recording(moving_take(3)) is None
    assert matcher.prepare_recording(moving_take(13)) is None
    assert matcher.prepare_recording(moving_take(6, distance=0.001)) is None
    # Translation used to vanish in normalization; the trajectory channel is
    # exactly what makes a swipe recordable, so it must now be accepted and the
    # displacement must land in the two appended dimensions.
    translated = matcher.prepare_recording(translated_take(6))
    assert translated is not None
    assert translated[-1][64] == 0.0
    assert abs(translated[-1][63]) > 0.5


def test_bounded_dtw_matches_time_warped_motion_and_rejects_distinct_motion():
    matcher = DynamicGestureMatcher(sequence_length=12, min_recording_frames=4, sakoe_chiba_band=3)
    template_sequence = matcher.prepare_recording(moving_take(12))
    warped_sequence = matcher.prepare_recording(moving_take(7))
    different_sequence = matcher.prepare_recording(
        [articulate(landmarks(), 0.0, index / 11) for index in range(12)]
    )

    assert template_sequence is not None
    assert warped_sequence is not None
    assert different_sequence is not None
    assert matcher.dtw_distance(template_sequence, warped_sequence) < 0.02
    assert matcher.dtw_distance(template_sequence, different_sequence) > 0.05


def test_dynamic_template_supports_multiple_samples_and_only_whitelisted_action():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)
    first = matcher.prepare_recording(moving_take(6))
    second = matcher.prepare_recording(moving_take(7))

    assert first is not None
    assert second is not None
    template = matcher.create_template(
        name="Swipe down",
        action="scroll_down",
        landmark_samples=[moving_take(6), moving_take(7)],
        template_id="scroll-down-swipe",
        threshold=0.03,
        cooldown_seconds=0.5,
        min_motion_energy=0.05,
    )

    assert template == DynamicGestureTemplate(
        template_id="scroll-down-swipe",
        name="Swipe down",
        action="scroll_down",
        samples=(first, second),
        threshold=0.03,
        cooldown_seconds=0.5,
        min_motion_energy=0.05,
    )
    assert matcher.create_template("Unsafe", "delete", [moving_take(6)]) is None


def test_factory_rejects_unsafe_template_ids_without_constructing_a_template():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)

    assert matcher.create_template("Unsafe", "scroll_down", [moving_take(6)], template_id="unsafe/id") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("template_id", ""),
        ("template_id", None),
        ("template_id", " ../unsafe"),
        ("template_id", "unsafe/id"),
        ("action", None),
        ("action", "delete"),
        ("threshold", math.nan),
        ("threshold", math.inf),
        pytest.param("threshold", 10**10000, id="threshold-oversized"),
        ("threshold", "0.03"),
        ("threshold", -0.03),
        ("cooldown_seconds", math.nan),
        ("cooldown_seconds", math.inf),
        pytest.param("cooldown_seconds", 10**10000, id="cooldown-oversized"),
        ("cooldown_seconds", "0.5"),
        ("cooldown_seconds", -0.5),
        ("min_motion_energy", math.nan),
        ("min_motion_energy", math.inf),
        pytest.param("min_motion_energy", 10**10000, id="motion-energy-oversized"),
        ("min_motion_energy", "0.05"),
        ("min_motion_energy", -0.05),
    ],
)
def test_direct_template_construction_rejects_unsafe_metadata_and_runtime_gates(field, value):
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)
    sample = matcher.prepare_recording(moving_take(6))
    assert sample is not None
    values = {
        "template_id": "forward-swipe",
        "name": "Swipe right",
        "action": "scroll_down",
        "samples": (sample,),
        "threshold": 0.03,
        "cooldown_seconds": 0.5,
        "min_motion_energy": 0.05,
    }
    values[field] = value

    with pytest.raises(ValueError):
        DynamicGestureTemplate(**values)


@pytest.mark.parametrize(
    "samples",
    [
        (),
        (((0.0,) * 62, (0.1,) * 62),),
        (((0.0,) * 63, (math.nan,) + (0.1,) * 62),),
        (((0.0,) * 63, ("bad",) + (0.1,) * 62),),
    ],
)
def test_direct_template_construction_rejects_missing_or_malformed_samples(samples):
    with pytest.raises(ValueError):
        DynamicGestureTemplate(
            template_id="forward-swipe",
            name="Swipe right",
            action="scroll_down",
            samples=samples,
            threshold=0.03,
            cooldown_seconds=0.5,
            min_motion_energy=0.05,
        )


def test_runtime_matcher_skips_bypassed_invalid_template_without_matching_or_retriggering():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4, neutral_motion_energy=0.01)
    sample = matcher.prepare_recording(moving_take(6))
    assert sample is not None
    invalid = object.__new__(DynamicGestureTemplate)
    for field, value in {
        "template_id": "unsafe/id",
        "name": "Unsafe swipe",
        "action": "scroll_down",
        "samples": (sample,),
        "threshold": math.inf,
        "cooldown_seconds": -1.0,
        "min_motion_energy": -1.0,
    }.items():
        object.__setattr__(invalid, field, value)
    runtime = matcher.create_runtime_matcher([invalid])

    assert runtime.ingest(moving_take(6), active=True, now=0.0) is None
    assert runtime.ingest(moving_take(6), active=True, now=1.0) is None


@pytest.mark.parametrize("field", ("threshold", "cooldown_seconds", "min_motion_energy"))
def test_runtime_matcher_skips_bypassed_oversized_integer_gate_values(field):
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)
    sample = matcher.prepare_recording(moving_take(6))
    assert sample is not None
    invalid = object.__new__(DynamicGestureTemplate)
    for name, value in {
        "template_id": "unsafe-swipe",
        "name": "Unsafe swipe",
        "action": "scroll_down",
        "samples": (sample,),
        "threshold": 0.03,
        "cooldown_seconds": 0.5,
        "min_motion_energy": 0.05,
        field: 10**10000,
    }.items():
        object.__setattr__(invalid, name, value)

    runtime = matcher.create_runtime_matcher([invalid])

    assert runtime.ingest(moving_take(6), active=True, now=0.0) is None


def test_template_rejects_infinite_threshold_and_cannot_match_arbitrary_motion():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)

    template = matcher.create_template(
        "Unsafe swipe",
        "scroll_down",
        [moving_take(6)],
        threshold=math.inf,
    )
    arbitrary_motion = [articulate(landmarks(), 0.0, index / 7) for index in range(8)]

    assert template is None
    assert matcher.create_runtime_matcher([]).ingest(arbitrary_motion, active=True, now=0.0) is None


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("cooldown_seconds", math.nan),
        ("cooldown_seconds", math.inf),
        ("min_motion_energy", math.nan),
        ("min_motion_energy", math.inf),
    ],
)
def test_template_rejects_nonfinite_runtime_gate_values(parameter, value):
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)

    template = matcher.create_template(
        "Unsafe swipe",
        "scroll_down",
        [moving_take(6)],
        **{parameter: value},
    )

    assert template is None


def test_runtime_matcher_fires_once_then_requires_neutral_rearm_and_cooldown():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4, neutral_motion_energy=0.01)
    template = matcher.create_template(
        "Swipe right",
        "scroll_down",
        [moving_take(6)],
        threshold=0.03,
        cooldown_seconds=1.0,
        min_motion_energy=0.05,
        template_id="forward-swipe",
    )
    assert template is not None
    runtime = matcher.create_runtime_matcher([template])

    assert runtime.ingest(moving_take(6), active=True, now=0.0) == template
    assert runtime.ingest(moving_take(6), active=True, now=2.0) is None
    assert runtime.ingest([landmarks()] * 8, active=True, now=2.1) is None
    assert runtime.ingest(moving_take(6), active=True, now=2.2) == template


@pytest.mark.parametrize("invalid_now", [math.nan, math.inf])
def test_runtime_matcher_rejects_nonfinite_time_after_fire_without_retriggering(invalid_now):
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4, neutral_motion_energy=0.01)
    template = matcher.create_template(
        "Swipe right",
        "scroll_down",
        [moving_take(6)],
        threshold=0.03,
        cooldown_seconds=1.0,
        min_motion_energy=0.05,
        template_id="forward-swipe",
    )
    assert template is not None
    runtime = matcher.create_runtime_matcher([template])

    assert runtime.ingest(moving_take(6), active=True, now=0.0) == template
    assert runtime.ingest([landmarks()] * 8, active=True, now=0.1) is None
    assert runtime.ingest(moving_take(6), active=True, now=invalid_now) is None


def test_runtime_matcher_rejects_inactive_low_energy_and_different_sequences():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)
    template = matcher.create_template(
        "Swipe right", "scroll_down", [moving_take(6)], threshold=0.03, min_motion_energy=0.05
    )
    assert template is not None
    runtime = matcher.create_runtime_matcher([template])

    assert runtime.ingest(moving_take(6), active=False, now=0.0) is None
    assert runtime.ingest([landmarks()] * 8, active=True, now=1.0) is None
    vertical = [articulate(landmarks(), 0.0, index / 7) for index in range(8)]
    assert runtime.ingest(vertical, active=True, now=2.0) is None


def test_action_whitelist_is_exact_and_has_a_boolean_helper():
    assert ALLOWED_DYNAMIC_ACTIONS == frozenset(
        {"scroll_up", "scroll_down", "custom_hotkey"}
    )
    assert all(is_allowed_dynamic_action(action) for action in ALLOWED_DYNAMIC_ACTIONS)
    assert not is_allowed_dynamic_action("forward")
    assert not is_allowed_dynamic_action("delete")
    assert not is_allowed_dynamic_action(None)


def test_dynamic_template_rejects_semantic_actions_outside_the_persisted_allowlist():
    matcher = DynamicGestureMatcher(sequence_length=8, min_recording_frames=4)

    assert matcher.create_template("Unsafe swipe", "forward", [moving_take(6)]) is None

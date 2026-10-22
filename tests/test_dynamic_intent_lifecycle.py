from core.dynamic_intent_lifecycle import DynamicIntentLifecycle, DynamicIntentState


FRAME = [(0.0, 0.0, 0.0)] * 21


def test_dynamic_intent_records_one_non_pointer_motion_then_completes_after_stable_neutral():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=2, end_neutral_frames=2)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    armed = lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.1)
    started = lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.2)
    recording = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=0.3)
    ending = lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.4)
    completed = lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.5)

    assert armed.state is DynamicIntentState.ARMED
    assert started.state is DynamicIntentState.RECORDING
    assert recording.recording is True
    assert ending.completed_frames is None
    assert completed.completed_frames == (FRAME, FRAME)
    assert completed.state is DynamicIntentState.ARMED


def test_dynamic_lifecycle_requires_open_hand_start_boundary():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=1)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    ignored = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=0.1)
    started = lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.2)

    assert ignored.state is DynamicIntentState.ARMED
    assert ignored.recording is False
    assert started.state is DynamicIntentState.RECORDING


def test_dynamic_lifecycle_discards_an_overlong_or_timed_out_take_before_matching():
    lifecycle = DynamicIntentLifecycle(
        neutral_rearm_frames=1,
        max_recording_frames=2,
        max_duration_seconds=0.5,
    )

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.1)
    overflow = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=0.2)

    # An overflow resets to neutral, so a new take must rearm before it can
    # begin. Keep timeout independent of the discarded prior recording.
    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=1.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=1.1)
    timeout = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=1.7)

    assert overflow.state is DynamicIntentState.NEUTRAL
    assert overflow.completed_frames is None
    assert overflow.owns_frame is True
    assert timeout.state is DynamicIntentState.NEUTRAL
    assert timeout.completed_frames is None
    assert timeout.owns_frame is True


def test_dynamic_intent_aborts_its_partial_motion_when_pointer_lane_claims_a_frame():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=1)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.1)
    aborted = lifecycle.observe("pinch", FRAME, allowed=False, hand_present=True, now=0.2)

    assert aborted.state is DynamicIntentState.NEUTRAL
    assert aborted.recording is False
    assert aborted.completed_frames is None


def test_dynamic_lifecycle_keeps_the_overflow_frame_owned_while_discarding_the_take():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=1, max_recording_frames=2)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.1)
    overflow = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=0.2)

    assert overflow.state is DynamicIntentState.NEUTRAL
    assert overflow.recording is False
    assert overflow.completed_frames is None
    assert overflow.owns_frame is True


def test_dynamic_lifecycle_keeps_the_timeout_frame_owned_while_discarding_the_take():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=1, max_duration_seconds=0.1)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.1)
    timed_out = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=0.3)

    assert timed_out.state is DynamicIntentState.NEUTRAL
    assert timed_out.recording is False
    assert timed_out.completed_frames is None
    assert timed_out.owns_frame is True


def test_dynamic_lifecycle_keeps_an_invalid_recording_frame_owned_while_aborting():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=1)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.1)
    invalid = lifecycle.observe("peace", FRAME, allowed=True, hand_present=True, now=float("nan"))

    assert invalid.state is DynamicIntentState.NEUTRAL
    assert invalid.recording is False
    assert invalid.completed_frames is None
    assert invalid.owns_frame is True


def test_dynamic_lifecycle_keeps_a_missing_recording_frame_owned_while_aborting():
    lifecycle = DynamicIntentLifecycle(neutral_rearm_frames=1)

    lifecycle.observe("none", FRAME, allowed=True, hand_present=True, now=0.0)
    lifecycle.observe("open_hand", FRAME, allowed=True, hand_present=True, now=0.1)
    missing = lifecycle.observe("peace", [], allowed=True, hand_present=True, now=0.2)

    assert missing.state is DynamicIntentState.NEUTRAL
    assert missing.recording is False
    assert missing.completed_frames is None
    assert missing.owns_frame is True

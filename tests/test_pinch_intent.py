"""Deterministic geometry policies; real camera validation remains necessary."""

from math import cos, sin

import pytest

from core.pinch_intent import PinchIntentObserver


def hand(progress=0.0, *, x=0.0, y=0.0, rotation=0.0, scale=1.0,
         fist=False, curl=True):
    points = [(320.0, 330.0, 0.0)] * 21
    points[0] = (320.0, 400.0, 0.0)
    points[9] = (320.0, 300.0, 0.0)
    points[5] = (260.0, 300.0, 0.0)
    points[17] = (380.0, 310.0, 0.0)
    dx, dy = (25 * progress, 70 * progress) if curl else (0, 0)
    points[8] = (260.0 + dx, 160.0 + dy, 0.0)
    gap = 100 * (1 - progress) + 2 * progress
    points[4] = (points[8][0] + gap * 0.8, points[8][1] + gap * 0.6, 0.0)
    for i, offset in zip((12, 16, 20), (-10, 30, 60)):
        points[i] = (320.0 + offset, 300.0, 0.0)
        if fist:
            points[i] = (320.0 + offset * .2, 385.0, 0.0)
    c, s = cos(rotation), sin(rotation)
    return [(320 + x + scale * (c * (px - 320) - s * (py - 400)),
             400 + y + scale * (s * (px - 320) + c * (py - 400)), pz)
            for px, py, pz in points]


def observe(observer, now, progress=0.0, *, raw=None, pointing=None, **kwargs):
    raw = progress >= .8 if raw is None else raw
    pointing = progress < .25 if pointing is None else pointing
    return observer.update(hand(progress, **kwargs), now=now,
                           raw_pinching=raw, pointing=pointing)


def prime(observer, *, fps=30, speed=0.0, start=0.0):
    for i in range(int(fps * .4) + 1):
        t = start + i / fps
        observe(observer, t, x=speed * t)
    return t


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("speed", [0, 36, 600, 2400])
def test_abrupt_curl_uses_current_palm_and_last_flat_open_reference(fps, speed):
    observer = PinchIntentObserver()
    t = prime(observer, fps=fps, speed=speed)
    onset = t + 1 / fps
    candidate = observe(observer, onset, 1, x=speed * onset)
    assert candidate.phase == "candidate"
    assert candidate.new_episode and candidate.owns_pointer
    assert candidate.target_position == pytest.approx((260 + speed * onset, 160))
    assert candidate.reference_at == t
    assert candidate.target_at == onset
    assert candidate.corrections[0] == (t, pytest.approx((260 + speed * t, 160)))
    assert candidate.corrections[-1][1] == candidate.target_position
    result = candidate
    for i in range(1, int(fps * .1) + 2):
        now = onset + i / fps
        result = observe(observer, now, 1, x=speed * now)
    assert result.phase == "confirmed"
    assert not result.new_episode
    assert result.closed_at == onset
    assert result.target_position == candidate.target_position
    assert result.motion_position == pytest.approx((260 + speed * now, 160))


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_gradual_curl_reconstructs_first_closing_sample(fps):
    observer = PinchIntentObserver()
    t = prime(observer, fps=fps, speed=36)
    outputs = []
    for i in range(1, int(.18 * fps) + 2):
        now = t + i / fps
        progress = min(1, i / max(1, int(.18 * fps)))
        outputs.append(observe(observer, now, progress, x=36 * now))
    candidate = next(result for result in outputs if result.new_episode)
    assert candidate.reference_at == t
    assert candidate.target_at == pytest.approx(t + 1 / fps)
    assert candidate.target_position == pytest.approx((260 + 36 * candidate.target_at, 160))
    assert candidate.corrections[-1][0] - candidate.corrections[0][0] <= .2 + 1e-9
    for i in range(1, int(.12 * fps) + 2):
        now += 1 / fps
        result = observe(observer, now, 1, x=36 * now)
    assert result.phase == "confirmed"


def test_slow_candidate_lead_in_is_not_an_open_release():
    observer = PinchIntentObserver()
    prime(observer)
    candidate = observe(observer, .44, .3)
    assert candidate.phase == "candidate"
    for t, progress in ((.48, .4), (.52, .5), (.56, .65)):
        assert observe(observer, t, progress).phase == "candidate"
    for t in (.60, .63, .66):
        result = observe(observer, t, 1)
    assert result.phase == "confirmed"
    assert result.closed_at == .60


def test_rigid_rotation_and_scale_transport_clean_tip():
    observer = PinchIntentObserver()
    prime(observer)
    first = observe(observer, .44, 1, rotation=.15, scale=1.1)
    assert first.phase == "candidate"
    result = observe(observer, .50, 1, rotation=.30, scale=1.2)
    assert result.phase == "confirmed"
    assert result.motion_position == pytest.approx(hand(0, rotation=.30, scale=1.2)[8][:2])
    assert result.target_position == pytest.approx(hand(0, rotation=.15, scale=1.1)[8][:2])


@pytest.mark.parametrize("times", [[0, .02], [0, .04], [0, .1, .2]])
def test_already_pinched_start_never_arms(times):
    observer = PinchIntentObserver()
    for t in times:
        result = observe(observer, t, 1)
        assert result.phase == "cancelled" and result.owns_pointer
        assert result.closed_at is None


def test_open_qualification_needs_time_and_two_samples():
    observer = PinchIntentObserver()
    observe(observer, 0)
    observe(observer, .01)
    assert observe(observer, .02, 1).phase == "cancelled"


def test_old_pointing_cannot_qualify_after_nonpointing_hover():
    observer = PinchIntentObserver()
    prime(observer)
    for t in (.44, .48, .52, .56, .60, .64, .68):
        assert observe(observer, t, pointing=False).phase == "idle"
    result = observe(observer, .72, 1)
    assert result.phase == "cancelled"
    assert result.reason == "unqualified_onset"


def test_low_confidence_frames_preserve_physical_onset_without_earning_confirmation():
    observer = PinchIntentObserver()
    prime(observer)
    result = observer.update(hand(1), now=.44, raw_pinching=True,
                             pointing=False, pinch_confidence=.2)
    assert result.closed_at == .44 and result.phase == "candidate"
    assert observe(observer, .50, 1).phase == "candidate"
    result = observe(observer, .56, 1)
    assert result.phase == "confirmed" and result.closed_at == .44


def test_low_confidence_lead_in_cannot_shorten_physical_hold_into_click():
    from core.action_state_machine import ActionStateMachine, PinchActionEvidence

    observer = PinchIntentObserver()
    prime(observer)
    machine = ActionStateMachine()
    actions = []
    for now, raw, confidence in ((.44, True, .2), (.49, True, .2),
                                 (.54, True, .2), (.59, True, .2),
                                 (.60, True, 1), (.64, True, 1), (.68, True, 1),
                                 (.76, False, 1), (.81, False, 1)):
        result = observer.update(hand(1 if raw else 0), now=now,
                                 raw_pinching=raw, pointing=not raw,
                                 pinch_confidence=confidence)
        assert result.closed_at == .44
        if now == .64:
            assert result.phase == "candidate", "confidence dwell needs 55 ms"
        if now == .68:
            assert result.phase == "confirmed", "confirmation precedes candidate timeout"
        action = machine.update("pinch" if raw else "point", (260, 160),
                                pinch_info={"is_pinching": raw}, timestamp=now,
                                motion_pos=(260, 160),
                                pinch_evidence=PinchActionEvidence(
                                    phase=result.phase, target_pos=result.target_position,
                                    motion_anchor=(260, 160), closed_at=result.closed_at,
                                    opened_at=result.opened_at, new_episode=result.new_episode))
        actions.append(action["action"])
    assert result.phase == "released"
    assert result.opened_at - result.closed_at == pytest.approx(.32)
    assert "left_click" not in actions and "drag_start" not in actions


def test_physical_opening_before_confirmation_restarts_physical_and_confident_clocks():
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, 1)
    result = observe(observer, .46, 0)
    assert result.phase == "candidate" and result.closed_at is None
    assert observe(observer, .48, 1).closed_at == .48
    result = observe(observer, .54, 1)
    assert result.phase == "confirmed" and result.closed_at == .48


def test_short_closed_flash_cannot_become_a_click_release():
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, 1)
    observe(observer, .46, 0)
    result = observe(observer, .51, 0)
    assert result.phase == "cancelled"
    assert result.reason == "unconfirmed_release"


def test_open_chatter_preserves_episode_and_first_confirmed_open_timestamp():
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, 1)
    assert observe(observer, .50, 1).phase == "confirmed"
    first = observe(observer, .53, 0)
    assert first.phase == "confirmed" and first.opened_at == .53
    again = observe(observer, .55, 1)
    assert again.phase == "confirmed" and not again.new_episode
    assert again.opened_at is None and again.closed_at == .44
    observe(observer, .58, 0)
    result = observe(observer, .63, 0)
    assert result.phase == "released" and result.opened_at == .58
    assert observe(observer, .66).phase == "idle"
    assert observe(observer, .70).phase == "idle"


def test_cancelled_transition_latches_through_later_valid_pinch_labels():
    observer = PinchIntentObserver()
    prime(observer)
    result = observer.update(hand(1), now=.44, raw_pinching=True,
                             pointing=False, transition=True)
    assert result.phase == "cancelled"
    for t in (.48, .54, .60):
        assert observe(observer, t, 1).phase == "cancelled"
    assert observe(observer, .64).phase == "cancelled"
    assert observe(observer, .69).phase == "idle"
    assert observe(observer, .73, 1).new_episode


def test_other_finger_contraction_rejects_pass_through_fist():
    observer = PinchIntentObserver()
    prime(observer)
    result = observe(observer, .44, 1, fist=True)
    assert result.phase == "cancelled"
    assert result.reason == "other_fingers_contracting"
    assert observe(observer, .50, 1).phase == "cancelled"


@pytest.mark.parametrize("bad", ["gap", "backward", "nan", "scale", "shape", "teleport"])
def test_discontinuous_or_invalid_evidence_cannot_finish_an_episode(bad):
    observer = PinchIntentObserver()
    prime(observer, speed=36)
    observe(observer, .44, 1, x=36 * .44)
    points = hand(1, x=36 * .50)
    now = .50
    if bad == "gap":
        now = .70
    elif bad == "backward":
        now = .43
    elif bad == "nan":
        points[8] = (float("nan"), 0, 0)
    elif bad == "scale":
        points = hand(1, scale=2)
    elif bad == "shape":
        points[5] = (100, 300, 0)
    elif bad == "teleport":
        points = hand(1, x=220)
    result = observer.update(points, now=now, raw_pinching=True, pointing=False)
    assert result.phase == "cancelled"
    assert result.owns_pointer
    later = max(now, .50) + .06
    assert observe(observer, later, 1).phase == "cancelled"


def test_candidate_timeout_and_confidence_are_not_an_admission_bypass():
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, .3)
    for t in (.50, .56, .62, .70):
        result = observer.update(hand(.5), now=t, raw_pinching=True,
                                 pointing=False, pinch_confidence=.2)
    assert result.phase == "cancelled"
    assert result.reason == "candidate_timeout"


def test_known_competing_pose_excludes_idle_contraction_only_candidate():
    observer = PinchIntentObserver()
    prime(observer)
    # A thumb pose can reduce thumb-index separation without closing a pinch.
    result = observer.update(hand(.3), now=.44, raw_pinching=False,
                             pointing=False, competing_pose=True)
    assert result.phase == "idle" and not result.owns_pointer
    assert not observer._open_history and not observer._history
    # The old pointing baseline cannot qualify a later closed pose either.
    assert observe(observer, .50, 1).phase == "cancelled"


def test_competing_pose_cannot_override_physical_closed_admission():
    observer = PinchIntentObserver()
    prime(observer)
    result = observer.update(hand(1), now=.44, raw_pinching=True,
                             pointing=False, competing_pose=True)
    assert result.phase == "candidate" and result.new_episode
    assert result.owns_pointer


def test_competing_label_cannot_escape_an_active_candidate():
    observer = PinchIntentObserver()
    prime(observer)
    assert observe(observer, .44, .3).phase == "candidate"
    result = observer.update(hand(.4), now=.48, raw_pinching=False,
                             pointing=False, competing_pose=True)
    assert result.phase == "candidate" and result.owns_pointer
    assert not result.new_episode
    assert observe(observer, .52, 1).phase == "candidate"
    assert observe(observer, .58, 1).phase == "confirmed"


def test_two_natural_pinches_have_distinct_anchors_without_cooldown():
    observer = PinchIntentObserver()
    prime(observer)
    first = observe(observer, .44, 1)
    observe(observer, .50, 1)
    observe(observer, .53)
    assert observe(observer, .58).phase == "released"
    observe(observer, .61, x=10)
    observe(observer, .64, x=20)
    second = observe(observer, .67, 1, x=30)
    assert second.new_episode
    assert second.target_position == (290, 160)
    assert second.target_position != first.target_position


def test_15fps_release_baseline_admits_immediate_next_frame_pinch():
    observer = PinchIntentObserver()
    t = prime(observer, fps=15)
    step = 1 / 15
    first = observe(observer, t + step, 1)
    assert observe(observer, t + 2 * step, 1).phase == "confirmed"
    assert observe(observer, t + 3 * step).phase == "confirmed"
    assert observe(observer, t + 4 * step).phase == "released"
    second = observe(observer, t + 5 * step, 1)
    assert second.phase == "candidate" and second.new_episode
    assert second.reference_at == pytest.approx(t + 4 * step)
    assert second.closed_at != first.closed_at
    assert observe(observer, t + 6 * step, 1).phase == "confirmed"


@pytest.mark.parametrize("opening", ["nonpointing", "one_genuine", "too_short"])
def test_release_does_not_rearm_without_qualified_genuine_opening(opening):
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, 1)
    assert observe(observer, .50, 1).phase == "confirmed"
    if opening == "too_short":
        observe(observer, .53, pointing=False)
        observe(observer, .56)
        assert observe(observer, .58).phase == "released"
    else:
        observe(observer, .53, pointing=False)
        assert observe(observer, .60, pointing=opening == "one_genuine").phase == "released"
    result = observe(observer, .66, 1)
    assert result.phase == "cancelled" and not result.new_episode
    assert result.reason == "unqualified_onset"


def test_disabling_clears_every_episode_and_trace():
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, 1)
    result = observer.update(None, now=.5, raw_pinching=True, pointing=False, enabled=False)
    assert result.phase == "idle" and not result.owns_pointer
    assert result.target_position is None and not result.corrections


def test_history_is_bounded_even_at_extreme_frame_rates():
    observer = PinchIntentObserver()
    for i in range(1000):
        observe(observer, i / 1000)
    assert len(observer._history) <= 64
    assert observer._history[-1].now - observer._history[0].now <= .2


def test_cancelled_open_pointing_can_move_before_click_rearms():
    observer = PinchIntentObserver()
    prime(observer)
    observe(observer, .44, .3)
    for t in (.50, .56, .62, .70):
        cancelled = observe(observer, t, .5)
    assert cancelled.phase == 'cancelled'
    assert not cancelled.movement_allowed
    first_open = observe(observer, .73)
    assert first_open.phase == 'cancelled'
    assert first_open.movement_allowed
    # Moving safely is independent of accepting another click.
    early_close = observe(observer, .75, 1)
    assert early_close.phase == 'cancelled'
    assert not early_close.movement_allowed
    assert observe(observer, .78).movement_allowed
    assert observe(observer, .83).phase == 'idle'


@pytest.mark.parametrize('failure', ['timestamp', 'shape', 'transition', 'closed', 'not_pointing'])
def test_cancelled_movement_requires_current_coherent_open_pointing(failure):
    observer = PinchIntentObserver()
    prime(observer)
    observer.update(None, now=.44, raw_pinching=False, pointing=False)
    points = hand()
    now, transition, raw, pointing = .48, False, False, True
    if failure == 'timestamp':
        now = float('nan')
    elif failure == 'shape':
        points[5] = points[17]
    elif failure == 'transition':
        transition = True
    elif failure == 'closed':
        raw = True
    elif failure == 'not_pointing':
        pointing = False
    result = observer.update(points, now=now, raw_pinching=raw,
                             pointing=pointing, transition=transition)
    assert result.phase == 'cancelled'
    assert not result.movement_allowed


def test_unconfirmed_release_keeps_open_pointer_motion_on_cancellation_frame():
    observer = PinchIntentObserver()
    prime(observer)
    assert observe(observer, .44, .3).phase == 'candidate'
    assert observe(observer, .48).phase == 'candidate'
    cancelled = observe(observer, .54)
    assert cancelled.phase == 'cancelled'
    assert cancelled.reason == 'unconfirmed_release'
    assert cancelled.movement_allowed

"""Joint evidence owns pinch admission independently of legacy gesture labels."""

from dataclasses import FrozenInstanceError, replace

import pytest

from core.action_state_machine import ActionState, ActionStateMachine, PinchActionEvidence


TARGET = (100, 100)
ANCHOR = (10, 10)
CLOSED = {'is_pinching': True, 'is_approaching': True, 'distance': 5, 'velocity': -100}
OPEN = dict(CLOSED, is_pinching=False)


def evidence(phase, **kwargs):
    return PinchActionEvidence(phase, target_pos=TARGET, motion_anchor=ANCHOR, **kwargs)


def frame(machine, at, decision, *, gesture='pinch_hold', pos=TARGET, motion=ANCHOR, raw=CLOSED):
    return machine.update(gesture, pos, raw, timestamp=at, motion_pos=motion,
                          pinch_evidence=decision)


def test_admission_evidence_is_immutable():
    decision = evidence('candidate')
    with pytest.raises(FrozenInstanceError):
        decision.phase = 'confirmed'


def test_candidate_keeps_visible_motion_separate_from_target_without_down_or_timeout():
    machine = ActionStateMachine()
    decision = evidence('candidate')
    for index, at in enumerate((1.0, 1.1, 1.7, 2.5)):
        visible = (500 + index * 10, 500)
        result = frame(machine, at, decision, gesture='pinch', pos=visible, motion=(800, 800))
        assert result['action'] == 'move_cursor'
        assert result['pos'] == visible
        assert not result['is_locked']
        assert machine.locked_pos is None
        assert machine.state is ActionState.LOCKING
    assert machine.pinch_start_time is None


def test_cancelled_episode_can_move_on_explicit_open_evidence_without_rearming_click():
    machine = ActionStateMachine()
    frame(machine, 1.0, evidence('candidate'))
    safe_open = evidence('cancelled', movement_allowed=True)
    result = frame(machine, 1.1, safe_open, pos=(300, 400), raw=OPEN)
    assert result['action'] == 'move_cursor'
    assert result['pos'] == (300, 400)
    assert not result['is_locked']
    assert frame(machine, 1.2, evidence('confirmed', closed_at=1.15))['action'] == 'none'
    assert frame(machine, 1.3, safe_open, gesture='cancel')['action'] == 'none'


def test_open_movement_permission_cannot_skip_drag_release():
    machine = ActionStateMachine()
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    assert frame(machine, 1.4, confirmed, motion=(30, 30))['action'] == 'drag_start'
    cancelled = evidence('cancelled', movement_allowed=True)
    assert frame(machine, 1.5, cancelled, pos=(400, 400), raw=OPEN)['action'] == 'drag_end'
    assert frame(machine, 1.6, cancelled, pos=(410, 400), raw=OPEN)['action'] == 'move_cursor'


@pytest.mark.parametrize('phase', ['cancelled', 'released'])
def test_rejected_candidate_cannot_be_readmitted_by_raw_approach_or_late_label(phase):
    machine = ActionStateMachine()
    frame(machine, 1.0, evidence('candidate'))
    assert frame(machine, 1.1, evidence(phase))['action'] == 'none'
    for at in (1.2, 1.4, 2.0):
        assert frame(machine, at, evidence('confirmed', closed_at=1.05))['action'] == 'none'
        assert machine.state is ActionState.MOVING
    frame(machine, 2.1, PinchActionEvidence('idle'), gesture='point')
    assert frame(machine, 2.2, evidence('confirmed', closed_at=2.15))['is_locked']


def test_idle_ignores_raw_and_stable_pinch_but_allows_point_movement():
    machine = ActionStateMachine()
    idle = PinchActionEvidence('idle')
    for at, gesture in enumerate(('pinch', 'pinch_hold', 'open_hand'), 1):
        assert frame(machine, at, idle, gesture=gesture)['action'] == 'none'
        assert machine.state is ActionState.MOVING
    assert frame(machine, 4.0, idle, gesture='point')['action'] == 'move_cursor'


def test_original_physical_closure_does_not_turn_long_hold_into_short_click():
    machine = ActionStateMachine()
    frame(machine, 1.25, evidence('confirmed', closed_at=1.0))
    result = frame(machine, 1.5, evidence('released', closed_at=1.0, opened_at=1.4))
    assert result['action'] == 'none'


def test_short_click_uses_physical_opening_and_is_emitted_once():
    machine = ActionStateMachine()
    frame(machine, 1.1, evidence('confirmed', closed_at=1.0))
    released = evidence('released', closed_at=1.0, opened_at=1.2)
    assert frame(machine, 1.5, released)['action'] == 'left_click'
    assert frame(machine, 1.6, released)['action'] == 'none'
    assert frame(machine, 1.7, evidence('confirmed', closed_at=1.0))['action'] == 'none'


def test_pending_candidate_release_never_clicks():
    machine = ActionStateMachine()
    frame(machine, 1.0, evidence('candidate'))
    released = evidence('released', closed_at=1.05, opened_at=1.1)
    assert frame(machine, 1.2, released)['action'] == 'none'


def test_two_qualified_episodes_can_click_without_an_intervening_idle_frame():
    machine = ActionStateMachine()
    frame(machine, 1.1, evidence('confirmed', closed_at=1.0))
    assert frame(machine, 1.25, evidence('released', closed_at=1.0, opened_at=1.2))['action'] == 'left_click'
    candidate = evidence('candidate', new_episode=True)
    assert frame(machine, 1.3, candidate)['action'] == 'move_cursor'
    assert machine.state is ActionState.LOCKING
    frame(machine, 1.4, evidence('confirmed', closed_at=1.35))
    released = evidence('released', closed_at=1.35, opened_at=1.5)
    assert frame(machine, 1.55, released)['action'] == 'left_click'
    assert frame(machine, 1.6, released)['action'] == 'none'


def test_unmarked_candidate_and_marked_confirmation_cannot_revive_released_episode():
    machine = ActionStateMachine()
    frame(machine, 1.1, evidence('confirmed', closed_at=1.0))
    frame(machine, 1.25, evidence('released', closed_at=1.0, opened_at=1.2))
    assert frame(machine, 1.3, evidence('candidate'))['action'] == 'none'
    assert frame(machine, 1.4, evidence('confirmed', closed_at=1.35, new_episode=True))['action'] == 'none'
    assert machine.state is ActionState.MOVING


def test_new_episode_marker_cannot_bypass_cancelled_episode_latch():
    machine = ActionStateMachine()
    frame(machine, 1.0, evidence('candidate'))
    frame(machine, 1.1, evidence('cancelled'))
    assert frame(machine, 1.2, evidence('candidate', new_episode=True))['action'] == 'none'
    assert frame(machine, 1.3, evidence('confirmed', closed_at=1.25))['action'] == 'none'
    assert machine.state is ActionState.MOVING


def test_only_rigid_hand_motion_can_start_and_continue_admitted_drag():
    machine = ActionStateMachine()
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    # Curl changes the displayed/raw index position while the rigid anchor stays.
    assert frame(machine, 1.4, confirmed, pos=(400, 500))['action'] == 'none'
    assert frame(machine, 1.5, confirmed, motion=(20, 10))['action'] == 'drag_start'
    dragged = frame(machine, 1.6, confirmed, motion=(40, 30))
    assert dragged['action'] == 'drag'
    assert dragged['pos'] == (40, 30)
    released = evidence('released', closed_at=1.0, opened_at=1.65)
    assert frame(machine, 1.7, released, pos=None)['action'] == 'drag_end'
    assert frame(machine, 1.8, released, pos=None)['action'] == 'none'


def test_raw_opening_jump_cannot_start_drag_with_confirmed_pinch():
    machine = ActionStateMachine()
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    assert frame(machine, 1.4, confirmed, motion=(500, 500), raw=OPEN)['action'] == 'none'
    assert machine.state is ActionState.CLICKING


def test_pending_opening_evidence_preserves_short_click_through_release_debounce():
    machine = ActionStateMachine()
    frame(machine, 1.1, evidence('confirmed', closed_at=1.0))
    opening = evidence('confirmed', closed_at=1.0, opened_at=1.2)
    for at in (1.2, 1.25, 1.35):
        assert frame(machine, at, opening, raw=OPEN, motion=(500, 500))['action'] == 'none'
        assert machine.state is ActionState.CLICKING
    release = replace(opening, phase='released')
    assert frame(machine, 1.4, release, raw=OPEN)['action'] == 'left_click'
    assert frame(machine, 1.5, release, raw=OPEN)['action'] == 'none'


def test_opening_glitch_then_reclosed_keeps_original_hold_and_allows_deliberate_drag():
    machine = ActionStateMachine()
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    opening = replace(confirmed, opened_at=1.15)
    assert frame(machine, 1.15, opening, raw=OPEN, motion=(500, 500))['action'] == 'none'
    assert frame(machine, 1.2, confirmed)['action'] == 'none'
    assert machine._pinch_opened_at is None
    assert frame(machine, 1.4, confirmed, motion=(30, 30))['action'] == 'drag_start'
    assert frame(machine, 1.5, evidence('cancelled'))['action'] == 'drag_end'


def test_target_snaps_once_at_confirmation_and_motion_anchor_stays_unsnapped():
    machine = ActionStateMachine()
    calls = []

    def snap(pos):
        calls.append(pos)
        return (900, 900)

    machine.snap_provider = snap
    frame(machine, 1.0, evidence('candidate'))
    assert calls == []
    confirmed = evidence('confirmed', closed_at=1.05)
    assert frame(machine, 1.1, confirmed)['pos'] == (900, 900)
    assert frame(machine, 1.4, confirmed)['action'] == 'none'
    assert machine.lock_anchor == ANCHOR
    released = evidence('released', closed_at=1.05, opened_at=1.2)
    clicked = frame(machine, 1.5, released)
    assert clicked['action'] == 'left_click'
    assert clicked['pos'] == (900, 900)
    assert calls == [TARGET]


def test_zone_blocks_drag_down_and_cancellation_cannot_release_unstarted_drag():
    machine = ActionStateMachine()
    machine.add_zone_rule(50, 50, 100, 100, ['click'])
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    assert frame(machine, 1.4, confirmed, motion=(30, 30))['action'] == 'none'
    assert machine.state is ActionState.CLICKING
    assert frame(machine, 1.5, evidence('cancelled'))['action'] == 'none'


def test_blocked_drag_motion_still_allows_one_cancel_release_at_last_allowed_position():
    machine = ActionStateMachine()
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    assert frame(machine, 1.4, confirmed, motion=(30, 30))['action'] == 'drag_start'
    machine.add_zone_rule(150, 0, 100, 200, [])
    assert frame(machine, 1.5, confirmed, motion=(180, 100))['action'] == 'none'
    assert frame(machine, 1.6, evidence('cancelled'), pos=None)['action'] == 'drag_end'
    assert frame(machine, 1.7, evidence('cancelled'), pos=None)['action'] == 'none'


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 1.0, 0.9, True, '1.1'])
def test_invalid_or_nonincreasing_frame_time_cancels_admission_without_input(bad):
    machine = ActionStateMachine()
    frame(machine, 1.0, evidence('candidate'))
    assert frame(machine, bad, evidence('confirmed', closed_at=0.95))['action'] == 'none'
    assert frame(machine, 1.2, evidence('confirmed', closed_at=0.95))['action'] == 'none'
    assert machine.state is ActionState.MOVING


@pytest.mark.parametrize('bad', [
    evidence('unknown'), evidence('confirmed', closed_at=2.0),
    evidence('confirmed', closed_at=float('nan')),
    replace(evidence('confirmed', closed_at=1.0), target_pos=(float('inf'), 2)),
    replace(evidence('confirmed', closed_at=1.0), motion_anchor=None),
    replace(evidence('candidate'), phase=[]), object(),
    replace(evidence('cancelled'), movement_allowed='yes'),
])
def test_malformed_evidence_fails_closed_and_latches_until_idle(bad):
    machine = ActionStateMachine()
    assert frame(machine, 1.1, bad)['action'] == 'none'
    assert frame(machine, 1.2, evidence('confirmed', closed_at=1.0))['action'] == 'none'


def test_inconsistent_episode_timing_cancels_without_click():
    machine = ActionStateMachine()
    frame(machine, 1.1, evidence('confirmed', closed_at=1.0))
    result = frame(machine, 1.2, evidence('released', closed_at=1.0, opened_at=0.9))
    assert result['action'] == 'none'
    assert machine.state is ActionState.MOVING


@pytest.mark.parametrize('bad_pos', [(float('nan'), 1), (True, 2), (1,), 'bad'])
def test_invalid_motion_cancels_admitted_pinch_without_down(bad_pos):
    machine = ActionStateMachine()
    confirmed = evidence('confirmed', closed_at=1.0)
    frame(machine, 1.1, confirmed)
    assert frame(machine, 1.4, confirmed, motion=bad_pos)['action'] == 'none'
    assert machine.state is ActionState.MOVING
    assert frame(machine, 1.5, confirmed)['action'] == 'none'


def test_idle_releases_orphaned_legacy_drag_without_clicking():
    machine = ActionStateMachine()
    machine.update('pinch', TARGET, CLOSED, timestamp=1.0)
    assert machine.update('pinch_hold', (120, 100), CLOSED, timestamp=1.4)['action'] == 'drag_start'
    assert frame(machine, 1.5, PinchActionEvidence('idle'), gesture='point')['action'] == 'drag_end'

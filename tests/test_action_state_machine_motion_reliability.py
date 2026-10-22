from core.action_state_machine import ActionState, ActionStateMachine


APPROACHING = {"distance": 50, "velocity": -250, "is_approaching": True}
NOT_APPROACHING = {"distance": 100, "velocity": 0, "is_approaching": False}


def replay(machine, frames):
    return [
        machine.update(gesture, pos, pinch_info, timestamp=timestamp)
        for timestamp, gesture, pos, pinch_info in frames
    ]


def test_dwell_threshold_controls_click_boundary_with_replayed_timestamps():
    machine = ActionStateMachine(dwell_threshold=0.1)

    machine.update("pinch", (100, 100), timestamp=10.0)
    result = machine.update("point", (100, 100), timestamp=10.15)

    assert result["action"] == "none"


def test_injected_monotonic_clock_controls_click_timing_without_timestamp():
    timestamps = iter((20.0, 20.05))
    machine = ActionStateMachine(clock=lambda: next(timestamps), dwell_threshold=0.1)

    machine.update("pinch", (100, 100))
    result = machine.update("point", (100, 100))

    assert result["action"] == "left_click"


def test_single_noisy_approach_sample_does_not_lock():
    machine = ActionStateMachine(lock_confirmation_time=0.05)

    results = replay(
        machine,
        [
            (1.0, "point", (10, 10), APPROACHING),
            (1.02, "point", (12, 12), NOT_APPROACHING),
        ],
    )

    assert machine.state is ActionState.MOVING
    assert all(not result["is_locked"] for result in results)


def test_sustained_approach_locks_at_first_confirmed_position():
    machine = ActionStateMachine(lock_confirmation_time=0.05)

    results = replay(
        machine,
        [
            (1.0, "point", (10, 10), APPROACHING),
            (1.04, "point", (20, 20), APPROACHING),
            (1.05, "point", (30, 30), APPROACHING),
        ],
    )

    assert machine.state is ActionState.LOCKING
    assert results[-1]["is_locked"] is True
    assert results[-1]["pos"] == (10, 10)


def test_move_and_drag_thresholds_control_drag_boundary():
    below = ActionStateMachine(move_threshold=10, drag_threshold=0.2)
    below.update("pinch", (0, 0), timestamp=1.0)
    below_result = below.update("pinch_hold", (9, 0), timestamp=1.2)

    at_boundary = ActionStateMachine(move_threshold=10, drag_threshold=0.2)
    at_boundary.update("pinch", (0, 0), timestamp=1.0)
    boundary_result = at_boundary.update("pinch_hold", (10, 0), timestamp=1.2)

    assert below_result["action"] == "none"
    assert boundary_result["action"] == "drag_start"


def test_drag_release_is_emitted_exactly_once_after_replayed_release():
    machine = ActionStateMachine(move_threshold=5, drag_threshold=0.1)
    results = replay(
        machine,
        [
            (1.0, "pinch", (0, 0), NOT_APPROACHING),
            (1.1, "pinch_hold", (5, 0), NOT_APPROACHING),
            (1.2, "pinch_hold", (10, 0), NOT_APPROACHING),
            (1.3, "point", (10, 0), NOT_APPROACHING),
            (1.4, "point", (10, 0), NOT_APPROACHING),
        ],
    )

    assert [result["action"] for result in results].count("drag_end") == 1
    assert results[-1]["action"] == "move_cursor"

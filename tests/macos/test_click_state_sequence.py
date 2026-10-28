"""Two fast clicks must look like a double click to the OS.

macOS decides double-versus-single from ``kCGMouseEventClickState``, not from the
spacing of separate click events. Sending ``clickState = 1`` twice produces two
independent single clicks no matter how fast they arrive, so the natural gesture
(a quick re-pinch) could never produce a real double click. The second press has
to carry state 2, exactly as a physical mouse does.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from platform_services.contracts import ActionRequest
from platform_services.macos.input_controller import MacOSInputController


class _Recorder:
    def __init__(self):
        self.mouse: list[tuple] = []
        self.scrolls: list[tuple] = []
        self.hotkeys: list[tuple] = []

    def post_mouse(self, event_type, x, y, button, click_count=1):
        self.mouse.append((event_type, x, y, button, click_count))

    def post_scroll(self, *args):
        self.scrolls.append(args)

    def post_hotkey(self, *args):
        self.hotkeys.append(args)


class _Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def _controller():
    recorder = _Recorder()
    clock = _Clock()
    return MacOSInputController(recorder, clock=clock), recorder, clock


def _click(controller, x=100, y=200):
    return controller.execute(ActionRequest(action="left_click", x=x, y=y))


def _states(recorder):
    """Click state carried by each press event, in order."""
    return [entry[4] for entry in recorder.mouse if entry[0].endswith("_down")]


def test_two_fast_clicks_become_a_double_click():
    controller, recorder, clock = _controller()

    _click(controller)
    clock.now = 0.2
    _click(controller)

    assert _states(recorder) == [1, 2]


def test_a_third_fast_click_becomes_a_triple_click():
    controller, recorder, clock = _controller()

    _click(controller)
    clock.now = 0.15
    _click(controller)
    clock.now = 0.30
    _click(controller)

    assert _states(recorder) == [1, 2, 3]


def test_the_run_caps_at_triple():
    """macOS itself tracks no more than three."""
    controller, recorder, clock = _controller()

    for index in range(5):
        clock.now = index * 0.1
        _click(controller)

    assert _states(recorder) == [1, 2, 3, 3, 3]


def test_a_slow_second_click_stays_a_single_click():
    controller, recorder, clock = _controller()

    _click(controller)
    clock.now = 0.9  # past NSEvent.doubleClickInterval
    _click(controller)

    assert _states(recorder) == [1, 1]


def test_a_click_far_away_starts_a_new_run():
    """The OS only pairs clicks that land on the same spot."""
    controller, recorder, clock = _controller()

    _click(controller, x=100, y=200)
    clock.now = 0.1
    _click(controller, x=400, y=600)

    assert _states(recorder) == [1, 1]


def test_a_click_inside_the_slop_still_pairs():
    """A pixel or two of cursor jitter must not break a double click."""
    controller, recorder, clock = _controller()

    _click(controller, x=100, y=200)
    clock.now = 0.1
    _click(controller, x=102, y=201)

    assert _states(recorder) == [1, 2]


def test_the_release_carries_the_same_state_as_its_press():
    controller, recorder, clock = _controller()

    _click(controller)
    clock.now = 0.2
    _click(controller)

    down_states = [e[4] for e in recorder.mouse if e[0].endswith("_down")]
    up_states = [e[4] for e in recorder.mouse if e[0].endswith("_up")]
    assert down_states == up_states


def test_left_and_right_runs_do_not_mix():
    controller, recorder, clock = _controller()

    _click(controller, x=100, y=200)
    clock.now = 0.1
    controller.execute(ActionRequest(action="right_click", x=100, y=200))

    left_states = [
        e[4] for e in recorder.mouse if e[0] == "left_down"
    ]
    right_states = [
        e[4] for e in recorder.mouse if e[0] == "right_down"
    ]
    assert left_states == [1]
    assert right_states == [1]


def test_an_explicit_double_click_resets_the_run():
    """The composed pair already delivered a double click; do not continue it."""
    controller, recorder, clock = _controller()

    controller.execute(ActionRequest(action="double_click", x=100, y=200))
    clock.now = 0.1
    _click(controller)

    states = [e[4] for e in recorder.mouse if e[0] == "left_down"]
    # double_click sends state 2 then 1, then the fresh click starts at 1 again.
    assert states == [2, 1, 1]


def test_every_press_is_paired_with_a_release():
    controller, recorder, clock = _controller()

    for index in range(4):
        clock.now = index * 0.1
        _click(controller)

    downs = [e for e in recorder.mouse if e[0] == "left_down"]
    ups = [e for e in recorder.mouse if e[0] == "left_up"]
    assert len(downs) == len(ups) == 4

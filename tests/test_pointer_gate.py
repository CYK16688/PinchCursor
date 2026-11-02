"""Pointer jump gate: one implausible sample must not move the pointer."""

from core.pointer_gate import PointerJumpGate

FRAME = (640, 480)


def feed(gate, points, fps=30.0):
    flags = []
    now = 0.0
    for point in points:
        flags.append(gate.accept(point, FRAME, now))
        now += 1.0 / fps
    return flags


def test_a_straight_sweep_is_accepted():
    gate = PointerJumpGate()
    points = [(100.0 + 6.0 * i, 200.0) for i in range(20)]
    assert feed(gate, points) == [True] * 20


def test_one_far_sample_is_refused():
    gate = PointerJumpGate()
    points = [(100.0 + 6.0 * i, 200.0) for i in range(10)]
    assert all(feed(gate, points))
    assert gate.accept((600.0, 430.0), FRAME, 10.0 / 30.0) is False


def test_the_next_honest_frame_continues():
    gate = PointerJumpGate()
    points = [(100.0 + 6.0 * i, 200.0) for i in range(10)]
    assert all(feed(gate, points))
    assert gate.accept((600.0, 430.0), FRAME, 10.0 / 30.0) is False
    assert gate.accept((160.0, 200.0), FRAME, 11.0 / 30.0) is True
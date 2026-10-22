"""Unit tests for the pure-Python Bayesian target model."""

import ast
import math
from pathlib import Path

import pytest

from core.assist import target_model
from core.assist.target_model import SnapDecision, Target, TargetModel


def _rect(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    return (x, y, w, h)


# --- Fail-closed input handling ------------------------------------------------


def test_empty_target_list_returns_none():
    assert TargetModel().choose(10, 10, []) is None
    assert TargetModel().choose(10, 10, ()) is None


def test_none_targets_returns_none():
    assert TargetModel().choose(10, 10, None) is None


def test_malformed_inputs_return_none_without_raising():
    model = TargetModel()
    good = Target("good", _rect(0, 0, 20, 20))
    assert model.choose(None, 10, [good]) is None
    assert model.choose(10, float("nan"), [good]) is None
    assert model.choose(10, float("inf"), [good]) is None
    assert model.choose("10", 10, [good]) is None
    assert model.choose(10, True, [good]) is None
    assert model.choose(10, 10, 42) is None
    assert model.choose(10, 10, [object()]) is None
    assert model.choose(10, 10, [None]) is None


@pytest.mark.parametrize(
    "bounds",
    [
        (0, 0, 0, 40),
        (0, 0, 40, 0),
        (0, 0, -10, 40),
        (0, 0, 40, -1),
        (0, 0, float("nan"), 40),
        (0, 0, 40, float("inf")),
        (0, 0, float("inf"), 40),
        (0, 0, 40),
        (0, 0, 40, 40, 40),
        None,
        "abcd",
    ],
)
def test_illegal_bounds_are_ignored(bounds):
    assert TargetModel().choose(1, 1, [Target("bad", bounds)]) is None


def test_illegal_target_never_poisons_a_valid_candidate():
    decision = TargetModel().choose(
        95,
        120,
        [Target("bad", _rect(0, 0, 0, 0)), Target("good", _rect(100, 100, 60, 40))],
    )
    assert isinstance(decision, SnapDecision)
    assert decision.target_id == "good"


# --- Selection behaviour -------------------------------------------------------


def test_single_clear_target_snaps_with_full_confidence():
    target = Target("ok", _rect(100, 100, 60, 40))
    decision = TargetModel().choose(95, 120, [target])

    assert isinstance(decision, SnapDecision)
    assert decision.target_id == "ok"
    assert decision.confidence == pytest.approx(1.0)
    assert 0.0 < decision.confidence <= 1.0
    # Clamped to the rectangle and inset 2 px: x 95 -> 102, y stays 120.
    assert (decision.x, decision.y) == (102, 120)


def test_equidistant_identical_targets_are_rejected_as_ambiguous():
    # Two 40x40 buttons with a 2 px gap. The pointer sits 1 px from both, so the
    # posteriors are exactly 0.5/0.5 and both snap points are within reach.
    targets = [Target("left", _rect(100, 100, 40, 40)), Target("right", _rect(142, 100, 40, 40))]

    assert TargetModel().choose(141, 120, targets) is None

    # The rejection is the confidence floor, not the distance budget: lowering
    # the floor makes the very same geometry produce a decision.
    permissive = TargetModel(min_confidence=0.0).choose(141, 120, targets)
    assert permissive is not None
    assert permissive.confidence == pytest.approx(0.5)


def test_exact_tie_is_broken_by_target_id_not_input_order():
    beta = Target("beta", _rect(100, 100, 40, 40))
    alpha = Target("alpha", _rect(142, 100, 40, 40))
    model = TargetModel(min_confidence=0.4)

    forwards = model.choose(141, 120, [beta, alpha])
    backwards = model.choose(141, 120, [alpha, beta])

    assert forwards is not None and backwards is not None
    assert forwards.target_id == "alpha"
    assert backwards.target_id == "alpha"
    assert forwards == backwards


def test_disabled_targets_are_ignored():
    disabled = Target("off", _rect(100, 100, 40, 40), enabled=False)
    assert TargetModel(min_confidence=0.0).choose(141, 120, [disabled]) is None

    # The disabled button is nearer, yet the enabled one wins with certainty.
    closer_but_off = Target("off", _rect(100, 100, 40, 40), enabled=False)
    enabled = Target("on", _rect(150, 100, 40, 40))
    decision = TargetModel(min_confidence=0.4).choose(141, 120, [closer_but_off, enabled])
    assert decision is not None
    assert decision.target_id == "on"
    assert decision.confidence == pytest.approx(1.0)


def test_target_beyond_search_radius_is_ignored():
    far = Target("far", _rect(500, 500, 40, 40))
    # Edge-to-edge distance is hypot(400, 400) ~= 565.7 pt.
    assert TargetModel().choose(100, 100, [far]) is None

    wide = TargetModel(search_radius=1000.0, max_snap_distance=1000.0)
    decision = wide.choose(100, 100, [far])
    assert decision is not None
    assert (decision.x, decision.y) == (502, 502)


def test_cursor_already_inside_target_snaps_inside_without_centring():
    target = Target("inside", _rect(100, 100, 60, 40))
    decision = TargetModel().choose(101, 101, [target])

    assert decision is not None
    assert (decision.x, decision.y) == (102, 102)
    x, y, w, h = target.bounds
    assert x < decision.x < x + w
    assert y < decision.y < y + h
    # A centre jump would land on (130, 120); the assist must not do that.
    assert (decision.x, decision.y) != (x + w // 2, y + h // 2)


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        ((0, 0), (102, 202)),        # top-left overshoot clamps to the inset corner
        ((1000, 1000), (178, 258)),  # bottom-right overshoot clamps to the inset corner
        ((150, 230), (150, 230)),    # already inside the inset region: untouched
        ((100, 200), (102, 202)),    # exactly on the edge: nudged inside
        ((179, 259), (178, 258)),    # inside the rect but within 2 px of the border
    ],
)
def test_snap_point_is_always_inside_the_inset_region(cursor, expected):
    target = Target("button", _rect(100, 200, 80, 60))
    model = TargetModel(search_radius=5000.0, max_snap_distance=5000.0)

    decision = model.choose(cursor[0], cursor[1], [target])

    assert decision is not None
    assert (decision.x, decision.y) == expected
    assert 102 <= decision.x <= 178
    assert 202 <= decision.y <= 258


def test_max_snap_distance_blocks_a_certain_but_distant_snap():
    target = Target("edge", _rect(100, 100, 40, 40))
    # 60 pt away from the rectangle: a lone candidate is 100% probable, but the
    # cursor would have to travel ~62 pt, past the 24 pt budget.
    assert TargetModel().choose(40, 140, [target]) is None

    decision = TargetModel(max_snap_distance=80.0).choose(40, 140, [target])
    assert decision is not None
    assert (decision.x, decision.y) == (102, 138)
    assert math.hypot(decision.x - 40, decision.y - 140) == pytest.approx(math.hypot(62, 2))


def test_tiny_target_snaps_to_its_centre():
    # 4x4 pt: a 2 px inset would invert the rectangle, so the centre wins.
    target = Target("dot", _rect(100, 100, 4, 4))
    decision = TargetModel().choose(99, 99, [target])

    assert decision is not None
    assert (decision.x, decision.y) == (102, 102)


def test_sigma_scales_with_target_size_at_equal_distance():
    # The pointer is exactly hypot(100, 45) from both rectangles: the larger
    # target has the wider sigma, so it keeps the higher posterior.
    small = Target("small", _rect(100, 100, 10, 10))
    large = Target("large", _rect(100, 200, 100, 100))
    model = TargetModel(search_radius=120.0, max_snap_distance=120.0)

    assert math.isclose(math.hypot(100, 45), math.hypot(100, 45))
    decision = model.choose(0, 155, [small, large])

    assert decision is not None
    assert decision.target_id == "large"
    assert decision.confidence > 0.99


def test_confidence_is_a_bounded_probability():
    targets = [
        Target("a", _rect(100, 100, 40, 40)),
        Target("b", _rect(108, 100, 40, 40)),
        Target("c", _rect(116, 100, 40, 40)),
    ]
    decision = TargetModel(min_confidence=0.3).choose(150, 120, targets)

    assert decision is not None
    assert 0.0 < decision.confidence < 1.0
    assert math.isfinite(decision.confidence)


def test_float_cursor_coordinates_are_supported():
    target = Target("fractional", (100.5, 100.5, 40.0, 40.0))
    decision = TargetModel().choose(99.0, 120.5, [target])

    assert decision is not None
    assert isinstance(decision.x, int) and isinstance(decision.y, int)
    assert 102 <= decision.x <= 138
    assert 102 <= decision.y <= 138


# --- Determinism ---------------------------------------------------------------


def test_repeated_calls_return_identical_decisions():
    targets = [
        Target("a", _rect(100, 100, 40, 40)),
        Target("b", _rect(108, 100, 40, 40)),
        Target("c", _rect(116, 100, 40, 40)),
    ]
    model = TargetModel(min_confidence=0.3)

    first = model.choose(150, 120, targets)
    second = model.choose(150, 120, targets)

    assert first == second
    assert first is not None
    assert first.target_id == "c"


# --- Dependency hygiene --------------------------------------------------------


def test_module_imports_stdlib_only():
    source = Path(target_model.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "math", "collections", "dataclasses", "typing"}

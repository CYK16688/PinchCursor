"""Candidate features, the linear ranker, and the telemetry that trains it."""

import json

import pytest

from types import SimpleNamespace

from core.assist.features import FEATURE_COUNT, FEATURE_NAMES, build_features
from core.pointer_mapping import ScreenBounds
from gui.main_window import MainWindow
from platform_services.contracts import UIContext
from core.assist.ranker import LinearRanker
from core.assist.target_model import Target, TargetModel
from core.telemetry import TelemetryStore

SCREEN = (0, 0, 1000, 600)


def _target(target_id, bounds, role="AXButton"):
    return Target(target_id=target_id, bounds=bounds, role=role)


def test_features_have_a_fixed_width_and_order():
    targets = [_target("a", (100, 100, 80, 30)), _target("b", (300, 200, 40, 40), "AXSlider")]

    rows = build_features((120, 110), SCREEN, targets, {"a": 0.8, "b": 0.2})

    assert len(rows) == 2
    assert all(len(row) == FEATURE_COUNT == len(FEATURE_NAMES) for row in rows)


def test_features_describe_geometry_and_roles():
    inside = _target("in", (100, 100, 80, 30))
    slider = _target("sl", (140, 100, 40, 10), "AXSlider")

    rows = build_features((120, 110), SCREEN, [inside, slider], {"in": 0.9, "sl": 0.1})
    row, other = rows

    assert row[FEATURE_NAMES.index("inside")] == 1.0
    assert row[FEATURE_NAMES.index("role_button")] == 1.0
    assert other[FEATURE_NAMES.index("role_slider")] == 1.0
    # The nearer target has the best (lowest) distance rank.
    assert row[FEATURE_NAMES.index("dist_rank")] <= other[FEATURE_NAMES.index("dist_rank")]
    assert row[FEATURE_NAMES.index("bayes")] == 0.9


def test_ambiguous_point_is_not_inside_any_target():
    targets = [_target("a", (100, 100, 20, 20))]

    row = build_features((500, 500), SCREEN, targets, {})[0]

    assert row[FEATURE_NAMES.index("inside")] == 0.0


def test_ranker_round_trips_through_json(tmp_path):
    model = LinearRanker(weights=tuple(0.1 for _ in FEATURE_NAMES), intercept=-0.5)
    path = tmp_path / "m.json"
    path.write_text(json.dumps(model.to_dict()), encoding="utf-8")

    loaded = LinearRanker.load(str(path))

    assert loaded is not None
    assert loaded.weights == model.weights
    assert loaded.intercept == pytest.approx(-0.5)


def test_a_model_with_a_different_feature_set_is_rejected(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps({"feature_names": ["only_one"], "weights": [1.0], "intercept": 0.0}),
        encoding="utf-8",
    )

    assert LinearRanker.load(str(path)) is None


def test_a_missing_model_file_is_none(tmp_path):
    assert LinearRanker.load(str(tmp_path / "absent.json")) is None


def test_ranker_chooses_the_scored_winner_and_snaps_inside():
    weights = tuple(1.0 if name == "bayes" else 0.0 for name in FEATURE_NAMES)
    model = LinearRanker(weights=weights, intercept=0.0)
    targets = [_target("near", (100, 100, 40, 40)), _target("far", (400, 400, 40, 40))]

    decision = model.choose((110, 110), SCREEN, targets, {"near": 0.9, "far": 0.1})

    assert decision is not None
    assert decision.target_id == "near"
    assert 100 <= decision.x <= 140 and 100 <= decision.y <= 140


def test_ranker_declines_when_the_candidates_tie():
    weights = tuple(0.0 for _ in FEATURE_NAMES)
    model = LinearRanker(weights=weights, intercept=0.0)
    targets = [_target("a", (60, 100, 40, 30)), _target("b", (160, 100, 40, 30))]

    assert model.choose((110, 115), SCREEN, targets, {}) is None


def test_ranker_declines_when_the_snap_would_be_too_far():
    weights = tuple(0.0 for _ in FEATURE_NAMES)
    model = LinearRanker(weights=weights, intercept=0.0)
    targets = [_target("a", (140, 100, 40, 30))]

    assert model.choose((100, 115), SCREEN, targets, {}, max_snap_distance=4.0) is None


def test_posteriors_are_shared_between_decision_and_features():
    model = TargetModel()
    targets = [_target("a", (100, 100, 80, 30)), _target("b", (300, 100, 80, 30))]

    pairs = model.posteriors(110, 110, targets)
    decision = model.choose(110, 110, targets)

    assert pairs and decision is not None
    assert pairs[0][0].target_id == decision.target_id
    assert pairs[0][1] == pytest.approx(decision.confidence)


def _candidate_row(features, *, raw=False, bayes=False):
    return {
        "role": "AXButton",
        "x": 100,
        "y": 100,
        "w": 40,
        "h": 30,
        "dist": 5.0,
        "inside": raw,
        "bayes": 0.5,
        "features": features,
        "chosen_bayes": bayes,
        "chosen_raw": raw,
    }


def test_candidate_rows_round_trip_through_the_store(tmp_path):
    store = TelemetryStore(tmp_path / "t.sqlite3", enabled=True)
    features = tuple(0.5 for _ in FEATURE_NAMES)
    store.record_candidates(
        "lock-1",
        [_candidate_row(features, raw=True), _candidate_row(features)],
    )

    groups = store.candidate_groups()

    assert len(groups) == 1
    assert len(groups[0]["rows"]) == 2
    assert sum(row["chosen_raw"] for row in groups[0]["rows"]) == 1


def test_locks_without_a_single_physical_aim_are_dropped(tmp_path):
    store = TelemetryStore(tmp_path / "t.sqlite3", enabled=True)
    features = tuple(0.5 for _ in FEATURE_NAMES)

    store.record_candidates("ambiguous", [_candidate_row(features), _candidate_row(features)])
    store.record_candidates(
        "clear",
        [_candidate_row(features, raw=True), _candidate_row(features)],
    )

    groups = store.candidate_groups()

    assert [group["lock_id"] for group in groups] == ["clear"]


class _ProbeProvider:
    def __init__(self, contexts):
        self.contexts = contexts

    def probe_targets(self, x, y, radius=120):
        return list(self.contexts)


def _window(bounds, contexts, *, ranker=None, mode="bayesian"):
    window = MainWindow.__new__(MainWindow)
    window.target_model = TargetModel()
    window.ranker = ranker
    window.assist_mode = mode
    window.telemetry = None
    window.screen_bounds = ScreenBounds(*bounds)
    window.platform_services = SimpleNamespace(context_provider=_ProbeProvider(contexts))
    return window


def _context(x, y, w=40, h=30, role="AXButton"):
    return UIContext(category="clickable", native_role=role, bounds=(x, y, w, h))


def _dx_ranker():
    """A model that prefers targets to the left, not the closest one."""
    weights = [0.0] * FEATURE_COUNT
    # dx is signed: a large negative weight prefers targets to the right,
    # which is deliberately the wrong answer for this layout.
    weights[FEATURE_NAMES.index("dx")] = -1000.0
    return LinearRanker(weights=tuple(weights), intercept=0.0)


def test_shadow_mode_never_moves_the_cursor():
    # A sits under the cursor; B is 15 px to the right and still snappable.
    contexts = [_context(60, 95), _context(110, 95)]
    window = _window((0, 0, 1000, 600), contexts, ranker=_dx_ranker(), mode="shadow")

    result = MainWindow._snap_cursor_position(window, (95, 95))

    # The deterministic policy wins in shadow mode: A, inset 2 px on y.
    assert result == (95, 97)


def test_ranker_mode_uses_the_model_choice():
    contexts = [_context(60, 95), _context(110, 95)]
    window = _window((0, 0, 1000, 600), contexts, ranker=_dx_ranker(), mode="ranker")

    result = MainWindow._snap_cursor_position(window, (95, 95))

    # The tailored model prefers B, and B is within the snap distance.
    assert result is not None
    assert result[0] >= 110


def test_a_chaos_ranker_falls_back_to_the_raw_position():
    class Exploding:
        def choose(self, *args, **kwargs):
            raise RuntimeError("model went away")

    contexts = [_context(60, 95)]
    window = _window((0, 0, 1000, 600), contexts, ranker=Exploding(), mode="ranker")

    # The exception must not escape; the deterministic path still answers.
    assert MainWindow._snap_cursor_position(window, (95, 95)) == (95, 97)


def test_candidates_are_disabled_with_the_rest_of_telemetry(tmp_path):
    store = TelemetryStore(tmp_path / "t.sqlite3", enabled=False)
    store.record_candidates("lock", [_candidate_row((0.0,) * FEATURE_COUNT, raw=True)])

    assert store.candidate_groups() == []
    assert not (tmp_path / "t.sqlite3").exists()

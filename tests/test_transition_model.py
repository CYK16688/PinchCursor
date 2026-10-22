"""Feature and model contracts: one order, strict loading, no guessing."""

import json

from core.hand_dynamics import DynamicAssessment
from core.transition_features import FEATURE_COUNT, FEATURE_NAMES, build_features, validate_vector
from core.transition_model import TransitionModel


def _assessment(**overrides):
    values = dict(
        pinch_ratio=0.22,
        pinch_confidence=0.7,
        transition=False,
        others_rate=-0.4,
        wrist_speed=0.9,
        others_distance=2.6,
        pinch_slope=-1.2,
    )
    values.update(overrides)
    return DynamicAssessment(**values)


def test_the_vector_follows_the_declared_feature_order():
    vector = build_features(_assessment())

    assert len(vector) == FEATURE_COUNT == len(FEATURE_NAMES)
    assert vector == (0.22, 0.7, 2.6, -0.4, 0.9, -1.2)


def test_out_of_range_values_are_clamped_not_dropped():
    vector = build_features(_assessment(pinch_ratio=9.0, others_rate=-40.0))

    assert vector[0] == 3.0
    assert vector[3] == -12.0


def test_a_non_finite_assessment_is_no_evidence():
    assert build_features(_assessment(pinch_ratio=float("nan"))) is None
    assert build_features(None) is None


def test_stored_vectors_are_validated_on_the_way_back():
    assert validate_vector([0.2, 0.7, 2.6, -0.4, 0.9, -1.2]) == (0.2, 0.7, 2.6, -0.4, 0.9, -1.2)
    assert validate_vector([0.2, 0.7]) is None
    assert validate_vector(["0.2"] * FEATURE_COUNT) is None


def _write_model(tmp_path, **overrides):
    payload = {
        "version": 1,
        "feature_names": list(FEATURE_NAMES),
        "mean": [0.0] * FEATURE_COUNT,
        "scale": [1.0] * FEATURE_COUNT,
        "weights": [0.0] * FEATURE_COUNT,
        "intercept": 0.0,
    }
    payload.update(overrides)
    path = tmp_path / "transition_model.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_model_loads_and_scores(tmp_path):
    path = _write_model(tmp_path, weights=[4.0, 0.0, 0.0, 0.0, 0.0, 0.0], intercept=-1.0)

    model = TransitionModel.load(str(path))

    assert model is not None
    assert model.probability([0.5, 0.7, 2.6, -0.4, 0.9, -1.2]) > 0.5
    assert model.probability([0.1, 0.7, 2.6, -0.4, 0.9, -1.2]) < 0.5
    assert model.probability(None) is None


def test_a_model_with_a_different_feature_order_is_refused(tmp_path):
    path = _write_model(tmp_path, feature_names=["pinch_ratio"])

    assert TransitionModel.load(str(path)) is None


def test_a_model_with_a_degenerate_scale_is_refused(tmp_path):
    path = _write_model(tmp_path, scale=[1.0] * (FEATURE_COUNT - 1) + [0.0])

    assert TransitionModel.load(str(path)) is None


def test_a_missing_or_corrupt_file_is_refused(tmp_path):
    assert TransitionModel.load(str(tmp_path / "nope.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert TransitionModel.load(str(bad)) is None


def test_agreement_with_the_rule_is_a_comparison_not_a_decision(tmp_path):
    path = _write_model(tmp_path, weights=[4.0, 0.0, 0.0, 0.0, 0.0, 0.0], intercept=-1.0)
    model = TransitionModel.load(str(path))

    assert model.agrees_with_rule([0.5, 0.7, 2.6, -0.4, 0.9, -1.2], rule_rejected=False) is True
    assert model.agrees_with_rule([0.5, 0.7, 2.6, -0.4, 0.9, -1.2], rule_rejected=True) is False

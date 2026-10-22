from math import inf, nan

from core.static_gesture_template import StaticGestureMatcher
from utils.config_manager import ConfigManager


def test_template_features_ignore_translation_and_scale():
    matcher = StaticGestureMatcher()
    original = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    translated_scaled = [(100 + i * 6.0, 50 + i * 9.0, 0.0) for i in range(21)]

    assert matcher.normalize(original) == matcher.normalize(translated_scaled)


def test_incomplete_landmarks_are_rejected():
    assert StaticGestureMatcher().normalize([(0, 0, 0)] * 20) is None


def test_static_matcher_rejects_non_contract_landmark_frames_without_raising():
    matcher = StaticGestureMatcher()
    invalid_frames = (
        [(0.0, 0.0, 0.0)] * 22,
        [(nan, 0.0, 0.0)] * 21,
        [(inf, 0.0, 0.0)] * 21,
        [("bad", 0.0, 0.0)] * 21,
        [(True, 0.0, 0.0)] * 21,
        [(0.0, 0.0)] * 21,
    )

    for frame in invalid_frames:
        assert matcher.normalize(frame) is None


def test_template_matches_its_source_pose_but_rejects_a_different_pose():
    matcher = StaticGestureMatcher()
    source = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    different = [(i * 2.0, i * 30.0, 0.0) for i in range(21)]
    template = matcher.create_template("my trigger", [source], threshold=0.05)

    assert matcher.match(source, template)
    assert not matcher.match(different, template)


def test_custom_static_template_configuration_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    config = ConfigManager(config_path=path)
    template = {"template_id": "trigger-1", "name": "My trigger", "feature_vector": [0.0] * 63}
    config.set("control_session", "custom_static_templates", [template])
    config.save()

    assert ConfigManager(config_path=path).get("control_session", "custom_static_templates") == [template]

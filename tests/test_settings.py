"""Settings is the single read path, so its defaults must be the schema's."""

from utils.config_manager import DEFAULT_CONFIG
from utils.settings import read


def test_an_empty_document_reads_the_documented_defaults():
    snapshot = read({})
    assert snapshot.mapping.mode == DEFAULT_CONFIG["pointer_mapping"]["mode"]
    assert snapshot.mapping.gain == DEFAULT_CONFIG["pointer_mapping"]["gain"]
    assert snapshot.sensitivity.dead_zone == DEFAULT_CONFIG["global_sensitivity"]["dead_zone"]
    assert snapshot.assist.max_snap_distance == DEFAULT_CONFIG["pointer_assist"]["max_snap_distance"]
    assert snapshot.scroll.dwell_seconds == DEFAULT_CONFIG["pointer_scroll"]["dwell_seconds"]
    assert snapshot.stability.enabled is True


def test_configured_values_are_read_back():
    snapshot = read(
        {
            "pointer_mapping": {"mode": "relative", "gain": 3.0},
            "pointer_assist": {"enabled": False, "max_snap_distance": 40.0},
            "global_sensitivity": {"scroll_speed": 80, "dead_zone": 16.0},
            "stabilization": {"confirm_threshold": 5, "exit_threshold": 7},
            "pointer_scroll": {"enabled": False, "repeat_seconds": 0.2},
            "pointer_stability": {"enabled": False},
        }
    )
    assert snapshot.mapping.mode == "relative"
    assert snapshot.mapping.gain == 3.0
    assert snapshot.assist.enabled is False
    assert snapshot.assist.max_snap_distance == 40.0
    assert snapshot.sensitivity.scroll_speed == 80
    assert snapshot.sensitivity.dead_zone == 16.0
    assert snapshot.stabilization.confirm_threshold == 5
    assert snapshot.stabilization.exit_threshold == 7
    assert snapshot.scroll.enabled is False
    assert snapshot.scroll.repeat_seconds == 0.2
    assert snapshot.stability.enabled is False


def test_an_unusable_gate_flag_cannot_switch_the_gate_off():
    """Only a real bool counts; malformed input keeps the gate at its default.

    The control engine builds its pointer plausibility gate from this value, so
    a string or a number written by hand must not silently disable the check
    that stops one bad sample from teleporting the cursor.
    """
    for value in ("yes", 1, 0.0, None, []):
        snapshot = read({"pointer_stability": {"enabled": value}})
        assert snapshot.stability.enabled is True
    assert read({"pointer_stability": {}}).stability.enabled is True
    assert read({"pointer_stability": {"enabled": False}}).stability.enabled is False

def test_context_aware_and_temporal_read_back():
    snapshot = read({
        "context_aware": {"enabled": False, "intent_actions_enabled": False},
        "temporal": {"transition_guard": False, "transition_model": "/tmp/模型.json".replace("模型", "model")},
    })
    assert snapshot.context_aware.enabled is False
    assert snapshot.context_aware.intent_actions_enabled is False
    assert snapshot.temporal.transition_guard is False
    assert snapshot.temporal.transition_model.endswith("model.json")


def test_context_and_temporal_defaults():
    snapshot = read({})
    assert snapshot.context_aware.enabled is True
    assert snapshot.context_aware.intent_actions_enabled is True
    assert snapshot.temporal.transition_guard is True
    assert snapshot.temporal.transition_model == ""


def test_action_mode_and_performance_read_back():
    snapshot = read({
        "action_mode": {"dwell_threshold": 0.5, "move_threshold": 12, "drag_threshold": 0.4},
        "performance": {"mode": "performance"},
    })
    assert snapshot.action_mode.dwell_threshold == 0.5
    assert snapshot.action_mode.move_threshold == 12.0
    assert snapshot.action_mode.drag_threshold == 0.4
    assert snapshot.performance.mode == "performance"


def test_action_mode_and_performance_defaults():
    snapshot = read({})
    assert snapshot.action_mode.dwell_threshold == 0.3
    assert snapshot.action_mode.move_threshold == 8.0
    assert snapshot.action_mode.drag_threshold == 0.3
    assert snapshot.performance.mode == "standard"


def test_pinch_calibration_reads_only_a_usable_window():
    from utils.settings import read_pinch_calibration

    assert read_pinch_calibration({}) is None
    assert read_pinch_calibration({"pinch_calibration": {}}) is None
    assert read_pinch_calibration({"pinch_calibration": {"enter_ratio": 0.4}}) is None
    assert read_pinch_calibration({"pinch_calibration": {"enter_ratio": "x", "exit_ratio": 0.5}}) is None
    assert read_pinch_calibration({"pinch_calibration": {"enter_ratio": 0.4, "exit_ratio": 0.0}}) is None
    usable = read_pinch_calibration({"pinch_calibration": {"enter_ratio": 0.4, "exit_ratio": 0.55}})
    assert usable is not None and usable.exit_ratio == 0.55


def test_context_and_temporal_defaults_have_one_source():
    """The schema, the typed reader and the constants must agree."""
    from utils.config_manager import (
        DEFAULT_CONFIG,
        DEFAULT_CONTEXT_ENABLED,
        DEFAULT_INTENT_ACTIONS_ENABLED,
        DEFAULT_TRANSITION_GUARD,
    )

    assert DEFAULT_CONFIG["context_aware"]["enabled"] is DEFAULT_CONTEXT_ENABLED
    assert (
        DEFAULT_CONFIG["context_aware"]["intent_actions_enabled"]
        is DEFAULT_INTENT_ACTIONS_ENABLED
    )
    assert DEFAULT_CONFIG["temporal"]["transition_guard"] is DEFAULT_TRANSITION_GUARD

    snapshot = read({})
    assert snapshot.context_aware.enabled is DEFAULT_CONTEXT_ENABLED
    assert snapshot.context_aware.intent_actions_enabled is DEFAULT_INTENT_ACTIONS_ENABLED
    assert snapshot.temporal.transition_guard is DEFAULT_TRANSITION_GUARD

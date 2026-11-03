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
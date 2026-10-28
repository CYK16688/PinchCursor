import json

from utils.config_manager import ConfigManager


def test_legacy_null_keyed_zone_rules_are_normalized_to_an_empty_list(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"zone_rules": {"null": []}}), encoding="utf-8")

    manager = ConfigManager(config_path=path)

    assert manager.get("zone_rules") == []


def test_a_zone_on_a_display_with_a_negative_origin_is_kept():
    """A display left of or above the main one has negative global coordinates.

    Those rules used to be rejected outright, so a zone configured on a second
    monitor silently stopped working the moment the app restarted.
    """
    from core.action_state_machine import ActionStateMachine

    machine = ActionStateMachine()
    machine.set_zone_rules([
        {"x": -1920, "y": -300, "w": 400, "h": 300, "allowed": ["click"]},
    ])

    assert len(machine.zone_rules) == 1
    rect = machine.zone_rules[0]["rect"]
    assert rect == (-1920, -300, 400, 300)


def test_a_zone_with_a_non_positive_size_is_still_rejected():
    from core.action_state_machine import ActionStateMachine

    machine = ActionStateMachine()
    machine.set_zone_rules([
        {"x": 0, "y": 0, "w": 0, "h": 100, "allowed": ["click"]},
        {"x": 0, "y": 0, "w": 100, "h": -5, "allowed": ["drag"]},
    ])

    assert machine.zone_rules == []

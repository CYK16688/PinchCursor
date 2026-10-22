import json

from utils.config_manager import ConfigManager


def test_legacy_null_keyed_zone_rules_are_normalized_to_an_empty_list(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"zone_rules": {"null": []}}), encoding="utf-8")

    manager = ConfigManager(config_path=path)

    assert manager.get("zone_rules") == []

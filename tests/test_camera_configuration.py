from utils.config_manager import ConfigManager


def test_camera_device_id_round_trips_without_using_open_cv_index(tmp_path):
    path = tmp_path / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("camera", "device_id", "usb-001")
    manager.save()

    reloaded = ConfigManager(config_path=path)

    assert reloaded.get("camera", "device_id") == "usb-001"


def test_missing_camera_device_id_defaults_to_empty_string(tmp_path):
    manager = ConfigManager(config_path=tmp_path / "settings.json")

    assert manager.get("camera", "device_id") == ""

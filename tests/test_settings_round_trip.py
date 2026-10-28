"""Settings must round-trip without drifting, and the file must stay clean.

Two classes of defect are pinned here:

* ``int(value * 100)`` truncates. ``0.29 * 100`` is ``28.999...``, so the user's
  calibration came back as ``0.28`` and drifted one point on every reopen/save.
* Keys with no reader survived in the file forever. ``camera.type`` and
  ``gestures.*.description`` were written by earlier builds and never read, and
  the description duplicated a label that lives in the i18n catalogue.
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from utils.config_manager import ConfigManager


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _dialog(config, tmp_path):
    from gui import settings_dialog

    return settings_dialog.SettingsDialog(config)


# Inside the slider range (30–95 percent): outside it the widget clamps,
# which is a separate, deliberate constraint.
@pytest.mark.parametrize("value", [0.57, 0.58, 0.71, 0.93])
def test_percent_fields_round_to_the_nearest_step_instead_of_down(app, tmp_path, value):
    """A percent field is quantised; it must not be systematically biased down."""
    config = ConfigManager(config_path=tmp_path / "settings.json")
    # Set before the dialog is built: the widgets are populated from the config
    # at construction, and Save writes back what the widgets show.
    config.set("detection", "confidence", value)
    dialog = _dialog(config, tmp_path)
    try:
        dialog.save_settings()
        stored = config.get("detection", "confidence")
        # Truncation always lands on or below the input: 0.29 -> 0.28, 0.57 ->
        # 0.56. Rounding lands on the nearest step, which may be above.
        assert stored >= round(value * 100) / 100 - 1e-9, f"{value} drifted down to {stored}"
        assert abs(stored - value) <= 0.005 + 1e-9, f"{value} drifted to {stored}"
    finally:
        dialog.deleteLater()


def test_the_specific_truncation_case_now_rounds_up(app, tmp_path):
    """0.57 used to be truncated to 56 percent, i.e. 0.56."""
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("detection", "tracking_confidence", 0.57)
    dialog = _dialog(config, tmp_path)
    try:
        dialog.save_settings()
        assert config.get("detection", "tracking_confidence") == pytest.approx(0.57, abs=0.005)
    finally:
        dialog.deleteLater()


def test_repeated_open_and_save_is_stable(app, tmp_path):
    """A value must survive many save cycles unchanged, not creep downward."""
    config = ConfigManager(config_path=tmp_path / "settings.json")
    config.set("detection", "tracking_confidence", 0.57)
    for _ in range(5):
        dialog = _dialog(config, tmp_path)
        try:
            dialog.save_settings()
        finally:
            dialog.deleteLater()
    assert config.get("detection", "tracking_confidence") == pytest.approx(0.57, abs=0.005)


def test_keys_without_a_reader_are_not_persisted(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "camera": {"id": 1, "type": "ir", "width": 1280, "height": 720},
        "gestures": {
            "pinch": {
                "enabled": True,
                "action": "left_click",
                "hotkey": "",
                "description": "捏合 - 左键点击",
            }
        },
    }), encoding="utf-8")

    manager = ConfigManager(config_path=path)
    manager.save()
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert "type" not in stored["camera"]
    assert "description" not in stored["gestures"]["pinch"]
    # Scrubbing the dead keys must not disturb anything the user actually set.
    assert stored["camera"]["id"] == 1
    assert stored["camera"]["width"] == 1280
    assert stored["gestures"]["pinch"]["action"] == "left_click"

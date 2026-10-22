import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.i18n import set_locale
from gui.main_window import MainWindow


def test_runtime_status_uses_static_localized_labels_without_unknown_value_leakage():
    set_locale("en_US")
    window = MainWindow.__new__(MainWindow)
    window.power_mode = "mystery_mode"

    assert window._get_status_text(True) == "Detecting"
    assert window._get_status_text(False) == "Predicting"
    assert window._gesture_status_label("pinch_hold") == "Pinch and hold"
    assert window._gesture_status_label("untrusted_runtime_value") == "Unavailable gesture"
    assert window._status_override_label("main.camera_open_failed") == "Unable to open camera"
    assert window._status_override_label("untrusted_runtime_value") == "Control unavailable"

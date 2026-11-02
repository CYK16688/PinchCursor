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


def test_action_errors_offer_specific_recovery_without_exposing_raw_messages():
    from types import SimpleNamespace

    from platform_services.contracts import ActionResult

    for locale in ("zh_CN", "en_US"):
        set_locale(locale)
        messages = []
        window = MainWindow.__new__(MainWindow)
        window.hud = SimpleNamespace(show_error=lambda message, now, messages=messages: messages.append(message))
        for code in ("accessibility_permission_required", "missing_hotkey", "context_target_changed", "stale_frame", "release_pending"):
            window._update_hud_after_dispatch("left_click", ActionResult(False, "private app content", code), (10, 20), now=10)
        assert len(set(messages)) == 5
        assert all("private" not in message and not message.startswith("main.") for message in messages)

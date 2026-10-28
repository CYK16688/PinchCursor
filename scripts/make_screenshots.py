"""Render the README screenshots from the real widgets (offscreen)."""

"""Regenerate docs/screenshots/*.png from the real widgets (offscreen).

Run from anywhere: the script resolves the repository root itself. It uses fake
platform services, so no camera or accessibility permission is required.
"""

import sys
import tempfile
import pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtWidgets import QApplication

app = QApplication([])
app.setStyle("Fusion")

from gui import icons                       # noqa: E402
from utils.config_manager import ConfigManager  # noqa: E402
from gui.theme import DARK_THEME, apply_dark_palette  # noqa: E402
from gui.i18n import set_locale                          # noqa: E402

apply_dark_palette(app)
app.setStyleSheet(DARK_THEME)
app.setWindowIcon(icons.app_icon())

OUT = BASE / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


# ---- main window fixtures -------------------------------------------------
from gui import main_window as mw           # noqa: E402
from platform_services.contracts import (   # noqa: E402
    ActionResult,
    AuthorizationState,
    CameraDevice,
    PermissionSnapshot,
    PlatformCapabilities,
    PlatformServices,
    UIContext,
)
from platform_services.null import (        # noqa: E402
    GenericUIContextProvider,
    UnavailableCameraService,
    UnavailableInputController,
)


class Perms:
    def __init__(self, camera, accessibility):
        self._snapshot = PermissionSnapshot(camera=camera, accessibility=accessibility)

    def snapshot(self):
        return self._snapshot

    def request_camera_access(self, callback=None):
        return None

    def request_accessibility_prompt(self):
        return False

    def request_input_monitoring_prompt(self):
        return False


class Camera:
    def list_devices(self):
        return [CameraDevice(device_id="builtin", display_name="MacBook Pro Camera",
                             kind="camera", available=True)]

    def open_selected(self, *args, **kwargs):
        raise RuntimeError("preview only")


class Context:
    def get_context(self, x=None, y=None):
        return UIContext(category="clickable", native_role="AXButton", source="demo")

    def is_gesture_allowed(self, *args):
        return True

    def is_action_allowed(self, *args):
        return True


def services(camera, accessibility):
    perms = Perms(camera, accessibility)
    return PlatformServices(
        capabilities=PlatformCapabilities(
            platform="macos", architecture="arm64", permissions=perms.snapshot()
        ),
        input_controller=UnavailableInputController("screenshot"),
        context_provider=Context(),
        permission_provider=perms,
        camera_service=Camera(),
    )


def shot_main(name, camera, accessibility, *, locale="zh_CN", size=(1200, 720), phase=None):
    # Force a clean configuration so the screenshots show first-run defaults
    # instead of whatever the developer's settings file happens to contain.
    fresh = pathlib.Path(tempfile.mkdtemp()) / "settings.json"
    config = ConfigManager(config_path=fresh)
    config.set("ui", "language", locale)
    mw.ConfigManager = lambda: config
    mw.create_platform_services = lambda **_kwargs: services(camera, accessibility)
    window = mw.MainWindow()
    window.resize(*size)
    window.show()
    if phase is not None:
        # A clearly labelled synthetic state illustrates the real feedback
        # widgets without starting a camera or posting native input.
        from core.action_state_machine import ActionState
        from core.control_engine import ControlSnapshot
        from core.control_session import SessionState
        from PySide6.QtGui import QColor, QPainter, QPixmap
        from PySide6.QtCore import Qt
        import time

        window.is_running = True
        window._refresh_precision_console()
        window._present_control_snapshot(ControlSnapshot(
            time.monotonic(), "pinch", "pinch", SessionState.POINTER,
            ActionState.CLICKING, True, (600, 300), (600, 300), pinch_phase=phase,
        ))
        preview = QPixmap(640, 400)
        preview.fill(QColor("#090A0D"))
        painter = QPainter(preview)
        glyph = window._placeholder_pixmap(96, "#AFC5FF")
        painter.drawPixmap(272, 120, glyph)
        painter.setPen(QColor("#969DAA"))
        painter.drawText(preview.rect().adjusted(0, 230, 0, -100), Qt.AlignCenter,
                         "模拟手势回放 / Gesture replay")
        painter.end()
        window.video_label.setPixmap(preview)
    for _ in range(4):
        app.processEvents()
    window.grab().save(str(OUT / name))
    window.is_running = False
    window.close()


shot_main("main-ready.png", AuthorizationState.GRANTED, AuthorizationState.GRANTED)
shot_main("main-permissions.png", AuthorizationState.GRANTED, AuthorizationState.DENIED)
shot_main("main-compact-en.png", AuthorizationState.GRANTED, AuthorizationState.GRANTED,
          locale="en_US", size=(1000, 660))
shot_main("main-pinch-confirmed.png", AuthorizationState.GRANTED, AuthorizationState.GRANTED,
          phase="confirmed")


# ---- settings pages -------------------------------------------------------
from gui.settings_dialog import SettingsDialog              # noqa: E402
from core.telemetry import TelemetryStore, default_path      # noqa: E402
import time                                                  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp())
config = ConfigManager(config_path=tmp / "settings.json")
set_locale("zh_CN")

store = TelemetryStore(default_path(config.config_path), enabled=True)
now = time.time() - 600
for index in range(14):
    store.record("action", action="left_click", executed=True,
                 latency_ms=9.0 + index * 0.4, timestamp=now + index * 4)
store.record("action", action="right_click", executed=True, latency_ms=11.0, timestamp=now + 70)
for index in range(3):
    store.record("assist", snap_distance=6.0 + index, confidence=0.82, timestamp=now + 80 + index)
store.close()

dialog = SettingsDialog(config, None)
dialog.resize(1040, 760)
dialog.show()
for _ in range(4):
    app.processEvents()

dialog.open_section("control")
for _ in range(3):
    app.processEvents()
dialog.grab().save(str(OUT / "settings-control.png"))

dialog.open_section("activation")
for _ in range(3):
    app.processEvents()
dialog.grab().save(str(OUT / "settings-activation.png"))

dialog.open_section("gestures")
for _ in range(3):
    app.processEvents()
dialog.grab().save(str(OUT / "settings-gestures.png"))

dialog.open_section("advanced")
for _ in range(3):
    app.processEvents()
tabs = dialog.advanced_tabs
tabs.setCurrentIndex(tabs.count() - 1)
for _ in range(3):
    app.processEvents()
dialog.grab().save(str(OUT / "settings-stats.png"))
dialog.close()


# ---- calibration dialog ---------------------------------------------------
from PySide6.QtCore import QObject, Signal                  # noqa: E402


class FakeWorker(QObject):
    landmark_frame_ready = Signal(object)
    worker_ready = Signal()
    worker_error = Signal(str)

    def start(self):
        pass

    def isRunning(self):
        return True

    def stop(self):
        pass

    def wait(self, ms=0):
        return True


from gui.pinch_calibration_dialog import PinchCalibrationDialog  # noqa: E402

calibration = PinchCalibrationDialog(
    camera_config={}, config=config, worker_factory=lambda: FakeWorker()
)
calibration.resize(520, 640)
calibration.show()
for _ in range(4):
    app.processEvents()
calibration.grab().save(str(OUT / "calibration.png"))
calibration.close()

print("written:", sorted(path.name for path in OUT.iterdir()))

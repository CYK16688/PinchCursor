import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.i18n import set_locale
from gui.static_gesture_record_dialog import RecordingState, StaticGestureRecordDialog


def _valid_landmarks():
    return [(i * 2.0, i * 3.0, 0.0) for i in range(21)]


def test_dialog_requires_enough_valid_frames_before_confirmation():
    app = QApplication.instance() or QApplication([])
    dialog = StaticGestureRecordDialog(required_frames=3)
    try:
        assert dialog.state is RecordingState.WAITING
        dialog.accept_landmarks(_valid_landmarks())
        dialog.accept_landmarks(_valid_landmarks())
        assert dialog.can_confirm is False

        dialog.accept_landmarks(_valid_landmarks())
        assert dialog.state is RecordingState.READY_TO_CONFIRM
        assert dialog.can_confirm is True
    finally:
        dialog.close()


def test_static_recording_dialog_retranslates_fixed_copy_and_progress():
    app = QApplication.instance() or QApplication([])
    dialog = StaticGestureRecordDialog(required_frames=3)
    try:
        assert dialog.windowTitle() == "录制自定义触发手势"
        assert dialog.preview.text() == "录制打开后将启动摄像头预览"
        dialog.accept_landmarks(_valid_landmarks())
        assert dialog.status.text() == "1 / 3 个稳定样本"

        set_locale("en_US")
        dialog.retranslate_ui()

        assert dialog.windowTitle() == "Record custom trigger"
        assert dialog.preview.text() == "Camera preview starts when recording opens"
        assert dialog.status.text() == "1 / 3 stable samples"
    finally:
        dialog.close()


def test_retry_clears_samples_and_confirm_creates_named_template():
    app = QApplication.instance() or QApplication([])
    dialog = StaticGestureRecordDialog(required_frames=1)
    try:
        dialog.accept_landmarks(_valid_landmarks())
        dialog.retry()
        assert dialog.state is RecordingState.WAITING
        assert dialog.sample_count == 0

        dialog.accept_landmarks(_valid_landmarks())
        dialog.name_input.setText("Open palm start")
        template = dialog.confirm_template()
        assert template is not None
        assert template.name == "Open palm start"
        assert dialog.state is RecordingState.SAVED
    finally:
        dialog.close()

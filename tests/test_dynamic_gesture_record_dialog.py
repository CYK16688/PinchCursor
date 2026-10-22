import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.mediapipe_worker import LandmarkFrame
from gui.i18n import set_locale
from gui.dynamic_gesture_record_dialog import DynamicRecordingState, DynamicGestureRecordDialog


def landmarks():
    points = []
    for index in range(21):
        points.append(((index % 5) * 0.11, (index // 5) * 0.09, (index % 3) * 0.03))
    points[0] = (0.0, 0.0, 0.0)
    points[9] = (0.0, 0.25, 0.0)
    return points


def moving_take(count=8):
    result = []
    for position in range(count):
        frame = list(landmarks())
        for index in (4, 8, 12, 16, 20):
            x, y, z = frame[index]
            frame[index] = (x + position / (count - 1), y, z)
        result.append(frame)
    return result


def test_dialog_requires_explicit_record_and_valid_name_action_and_hotkey():
    app = QApplication.instance() or QApplication([])
    dialog = DynamicGestureRecordDialog(matcher_kwargs={"sequence_length": 8, "min_recording_frames": 4})
    try:
        for frame in moving_take():
            dialog.accept_landmarks(frame)
        assert dialog.take_count == 0
        assert dialog.state is DynamicRecordingState.READY

        dialog.start_recording()
        for frame in moving_take():
            dialog.accept_landmarks(frame)
        dialog.finish_recording()
        assert dialog.state is DynamicRecordingState.TAKE_READY
        assert dialog.confirm_template() is None

        dialog.name_input.setText("Swipe up")
        custom_index = dialog.action_selector.findData("custom_hotkey")
        dialog.action_selector.setCurrentIndex(custom_index)
        assert dialog.confirm_template() is None
        dialog.hotkey_input.setText("cmd+bogus+p")
        assert dialog.confirm_template() is None
        assert dialog.saved_record is None
        dialog.hotkey_input.setText("command + shift + P")
        template = dialog.confirm_template()
        assert template is not None
        assert template.action == "custom_hotkey"
        assert dialog.saved_record["hotkey"] == "cmd+shift+p"
        assert "frame" not in dialog.saved_record
    finally:
        dialog.close()


def test_dynamic_recording_dialog_retranslates_static_copy_without_changing_take_state():
    app = QApplication.instance() or QApplication([])
    dialog = DynamicGestureRecordDialog(matcher_kwargs={"sequence_length": 8, "min_recording_frames": 4})
    try:
        assert dialog.windowTitle() == "录制动态快捷手势"
        assert dialog.preview.text() == "点击录制后启动预览"
        assert dialog.record_button.text() == "录制"
        dialog.start_recording()
        dialog.accept_landmarks(moving_take()[0])
        dialog.name_input.setText("用户输入名称")
        dialog.hotkey_input.setText("ctrl+shift+p")

        set_locale("en_US")
        dialog.retranslate_ui()

        assert dialog.windowTitle() == "Record dynamic shortcut"
        assert dialog.preview.text() == "Preview starts after Record"
        assert dialog.record_button.text() == "Record"
        assert dialog.current_frame_count == 1
        assert dialog.name_input.text() == "用户输入名称"
        assert dialog.hotkey_input.text() == "ctrl+shift+p"
        assert dialog.action_selector.currentData() == "scroll_up"
    finally:
        dialog.close()


def test_dialog_retries_only_current_take_and_retains_accepted_takes():
    app = QApplication.instance() or QApplication([])
    dialog = DynamicGestureRecordDialog(matcher_kwargs={"sequence_length": 8, "min_recording_frames": 4})
    try:
        dialog.start_recording()
        for frame in moving_take():
            dialog.accept_landmarks(frame)
        dialog.finish_recording()
        assert dialog.accept_current_take() is True
        assert dialog.take_count == 1

        dialog.start_recording()
        for frame in moving_take(4):
            dialog.accept_landmarks(frame)
        dialog.retry_current_take()
        assert dialog.take_count == 1
        assert dialog.current_frame_count == 0
    finally:
        dialog.close()


def test_dialog_previews_worker_landmarks_without_persisting_rgb():
    app = QApplication.instance() or QApplication([])
    dialog = DynamicGestureRecordDialog(matcher_kwargs={"sequence_length": 8, "min_recording_frames": 4})
    try:
        dialog.start_recording()
        for index, frame in enumerate(moving_take()):
            dialog.accept_landmark_frame(LandmarkFrame(frame=None, landmarks=frame, timestamp_ms=index))
        dialog.finish_recording()
        assert dialog.state is DynamicRecordingState.TAKE_READY
        assert dialog.preview.text() != ""
    finally:
        dialog.close()

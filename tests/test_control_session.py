from core.control_session import ActivationMode, ControlSession, SessionState
from core.static_gesture_template import StaticGestureMatcher
from utils.config_manager import ConfigManager


def test_gesture_mode_requires_stable_activation_before_pointer_control():
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.3,
        no_hand_timeout_seconds=2.0,
    )

    assert session.update("open_hand", True, False, 0.0) is SessionState.INACTIVE
    assert session.update("open_hand", True, False, 0.31) is SessionState.ARMED
    assert session.update("point", True, False, 0.32) is SessionState.POINTER
    assert session.allows_pointer_actions() is True


def test_hold_shortcut_exits_when_key_is_released():
    session = ControlSession(
        mode=ActivationMode.HOLD_SHORTCUT,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.3,
        no_hand_timeout_seconds=2.0,
    )

    assert session.update("none", True, True, 0.0) is SessionState.ARMED
    assert session.update("point", True, True, 0.1) is SessionState.POINTER
    assert session.update("point", True, False, 0.2) is SessionState.INACTIVE


def test_no_hand_timeout_exits_gesture_session():
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.0,
        no_hand_timeout_seconds=2.0,
    )

    session.update("open_hand", True, False, 0.0)
    assert session.update("point", True, False, 0.1) is SessionState.POINTER
    assert session.update("none", False, False, 2.2) is SessionState.INACTIVE


def test_new_configuration_exposes_control_session_defaults(tmp_path):
    config = ConfigManager(config_path=tmp_path / "settings.json")

    assert config.get("control_session", "mode") == "gesture"
    assert config.get("control_session", "activation_gesture") == "open_hand"


def test_static_template_match_can_arm_session():
    source = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    matcher = StaticGestureMatcher()
    template = matcher.create_template("custom", [source], threshold=0.05, template_id="custom-1")
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.0,
        no_hand_timeout_seconds=2.0,
        activation_template=template,
        matcher=matcher,
    )

    assert session.update("none", True, False, 0.0, landmarks=source) is SessionState.ARMED


def test_custom_activation_template_does_not_fall_back_to_builtin_gesture():
    source = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    nonmatching_pose = [(float(i * i), float((i % 4) * 11), float(i % 3)) for i in range(21)]
    matcher = StaticGestureMatcher()
    template = matcher.create_template("custom", [source], threshold=0.05, template_id="custom-1")
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.0,
        no_hand_timeout_seconds=2.0,
        activation_template=template,
        matcher=matcher,
    )

    assert session.update(
        "open_hand", True, False, 0.0, landmarks=nonmatching_pose
    ) is SessionState.INACTIVE


def test_selected_activation_template_ignores_builtin_activation_after_stability_period():
    source = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    nonmatching_pose = [(float(i * i), float((i % 4) * 11), float(i % 3)) for i in range(21)]
    matcher = StaticGestureMatcher()
    template = matcher.create_template("custom", [source], threshold=0.05, template_id="custom-1")
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.3,
        no_hand_timeout_seconds=2.0,
        activation_template=template,
        matcher=matcher,
    )

    assert session.update(
        "open_hand", True, False, 0.0, landmarks=nonmatching_pose
    ) is SessionState.INACTIVE
    assert session.update(
        "open_hand", True, False, 0.31, landmarks=nonmatching_pose
    ) is SessionState.INACTIVE



def test_custom_exit_template_does_not_fall_back_to_builtin_gesture():
    source = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    nonmatching_pose = [(float(i * i), float((i % 4) * 11), float(i % 3)) for i in range(21)]
    matcher = StaticGestureMatcher()
    template = matcher.create_template("custom", [source], threshold=0.05, template_id="custom-1")
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.0,
        no_hand_timeout_seconds=2.0,
        exit_template=template,
        matcher=matcher,
    )

    assert session.update("open_hand", True, False, 0.0, landmarks=source) is SessionState.ARMED
    assert session.update("fist", True, False, 0.1, landmarks=nonmatching_pose) is SessionState.ARMED

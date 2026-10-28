"""捏合阈值的手掌尺度归一化与一次性校准。"""

import math

import pytest

from core.gesture_classifier import (
    PINCH_RATIO_MAX,
    PINCH_RATIO_MIN,
    GestureClassifier,
    PinchCalibrator,
    palm_scale_from_landmarks,
)


# ---------------------------------------------------------------------------
# 合成手型：640x480 像素坐标，palm_scale = 120 px
# ---------------------------------------------------------------------------

def _base_hand():
    """21 个 landmark，食指伸出、中指/无名指/小指弯曲。"""
    return [
        (320.0, 400.0),  # 0 wrist
        (302.0, 372.0),  # 1 thumb cmc
        (288.0, 352.0),  # 2 thumb mcp
        (274.0, 330.0),  # 3 thumb ip
        (0.0, 0.0),      # 4 thumb tip (由 _pinch_hand 放置)
        (292.0, 282.0),  # 5 index mcp
        (286.0, 250.0),  # 6 index pip
        (283.0, 228.0),  # 7 index dip
        (281.0, 208.0),  # 8 index tip
        (320.0, 280.0),  # 9 middle mcp -> 与 wrist 相距 120 px
        (320.0, 250.0),  # 10 middle pip
        (320.0, 290.0),  # 11 middle dip
        (320.0, 330.0),  # 12 middle tip (弯曲)
        (348.0, 284.0),  # 13 ring mcp
        (352.0, 254.0),  # 14 ring pip
        (350.0, 292.0),  # 15 ring dip
        (348.0, 330.0),  # 16 ring tip (弯曲)
        (374.0, 294.0),  # 17 pinky mcp
        (378.0, 268.0),  # 18 pinky pip
        (377.0, 304.0),  # 19 pinky dip
        (376.0, 338.0),  # 20 pinky tip (弯曲)
    ]


def _scaled(points, scale):
    return [(x * scale, y * scale) for x, y in points]


def _pinch_hand(scale=1.0, gap=6.0):
    """拇指尖放在食指尖右侧 gap 像素处；gap/120 即捏合比值。"""
    points = _base_hand()
    tip_x, tip_y = points[8]
    points[4] = (tip_x + gap, tip_y)
    return _scaled(points, scale)


def _point_hand(scale=1.0):
    return _pinch_hand(scale, gap=120.0)


def _ok_hand(scale=1.0):
    """拇指食指成圈，其余三指伸直。"""
    points = _pinch_hand(1.0, gap=2.0)
    points[12] = (320.0, 185.0)
    points[16] = (352.0, 190.0)
    points[20] = (376.0, 196.0)
    return _scaled(points, scale)


def _fist_hand(scale=1.0):
    """所有手指弯曲，且拇指-食指距离大于退出阈值（0.5 掌尺）。"""
    points = _base_hand()
    points[4] = (300.0, 290.0)
    points[8] = (300.0, 350.0)
    return _scaled(points, scale)


def _stable_label(hand, frames=4):
    classifier = GestureClassifier()
    label = "none"
    for index in range(frames):
        label = classifier.classify(hand, timestamp=index * 0.02)
    return label


# ---------------------------------------------------------------------------
# 手掌尺度辅助函数
# ---------------------------------------------------------------------------

def test_palm_scale_is_wrist_to_middle_mcp_distance():
    assert palm_scale_from_landmarks(_base_hand()) == pytest.approx(120.0)
    assert palm_scale_from_landmarks(_scaled(_base_hand(), 2.0)) == pytest.approx(240.0)


def test_palm_scale_rejects_missing_degenerate_and_non_finite_input():
    assert palm_scale_from_landmarks(None) is None
    assert palm_scale_from_landmarks([(0.0, 0.0)] * 5) is None

    collapsed = _base_hand()
    collapsed[9] = collapsed[0]
    assert palm_scale_from_landmarks(collapsed) is None

    non_finite = _base_hand()
    non_finite[9] = (math.nan, 280.0)
    assert palm_scale_from_landmarks(non_finite) is None


# ---------------------------------------------------------------------------
# 分辨率不变性
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "builder, expected",
    [
        (lambda scale: _pinch_hand(scale, gap=6.0), "pinch"),
        (lambda scale: _pinch_hand(scale, gap=72.0), "none"),
        (_point_hand, "point"),
        (_ok_hand, "ok"),
        (_fist_hand, "fist"),
    ],
)
def test_same_pose_classifies_identically_at_640_and_1280(builder, expected):
    assert _stable_label(builder(1.0)) == expected
    assert _stable_label(builder(2.0)) == expected


def test_pinch_hysteresis_is_expressed_in_palm_scale_ratio():
    # 0.35 位于默认 enter(0.29) 与 exit(0.42) 之间，因此只对已在捏合状态的
    # 分类器保持捏合，不会让空闲分类器进入捏合。
    for scale in (1.0, 2.0):
        classifier = GestureClassifier()
        assert classifier._detect_raw_gesture(_pinch_hand(scale, 6.0), 0.0) == "pinch"
        assert classifier._detect_raw_gesture(_pinch_hand(scale, 42.0), 0.1) == "pinch"
        assert classifier._detect_raw_gesture(_pinch_hand(scale, 60.0), 0.2) == "none"

        fresh = GestureClassifier()
        assert fresh._detect_raw_gesture(_pinch_hand(scale, 42.0), 0.0) == "none"


def test_degenerate_palm_scale_falls_back_to_absolute_pixel_threshold():
    def collapsed_hand(gap):
        points = _base_hand()
        points[9] = points[0]  # 掌尺为零
        points[4] = (points[8][0] + gap, points[8][1])
        return points

    assert palm_scale_from_landmarks(collapsed_hand(30.0)) is None

    close = GestureClassifier()
    assert close._detect_raw_gesture(collapsed_hand(30.0), 0.0) == "pinch"

    far = GestureClassifier()
    assert far._detect_raw_gesture(collapsed_hand(40.0), 0.0) != "pinch"


# ---------------------------------------------------------------------------
# 校准器
# ---------------------------------------------------------------------------

def _feed_ratios(calibrator, ratios):
    for ratio in ratios:
        calibrator.add_sample([ratio * 100.0], [100.0])


def test_calibrator_requires_ten_valid_samples():
    calibrator = PinchCalibrator()
    for _ in range(9):
        calibrator.add_sample([30.0], [120.0])

    assert calibrator.thresholds() is None

    calibrator.add_sample([30.0], [120.0])
    assert calibrator.thresholds() is not None


def test_calibrator_ignores_invalid_samples():
    calibrator = PinchCalibrator()
    calibrator.add_sample(
        [math.nan, 30.0, -5.0, math.inf, 20.0],
        [120.0, 0.0, 120.0, 120.0, math.nan],
    )

    assert calibrator.sample_count == 0
    assert calibrator.thresholds() is None


def test_calibrator_uses_p25_and_p75_of_the_ratio_distribution():
    calibrator = PinchCalibrator()
    _feed_ratios(calibrator, [0.20 + 0.01 * index for index in range(40)])

    result = calibrator.thresholds()

    assert result is not None
    assert result.sample_count == 40
    # 40 个样本的 p25 / p75 位置分别是 9.75 / 29.25。
    assert result.enter_ratio == pytest.approx(0.2975)
    assert result.exit_ratio == pytest.approx(0.4925)
    assert result.enter_ratio < result.exit_ratio


def test_calibrator_clamps_extreme_ratios_and_keeps_hysteresis():
    high = PinchCalibrator()
    _feed_ratios(high, [2.0] * 10)
    high_result = high.thresholds()

    assert high_result is not None
    assert PINCH_RATIO_MIN <= high_result.enter_ratio < high_result.exit_ratio
    assert high_result.exit_ratio == pytest.approx(PINCH_RATIO_MAX)
    assert high_result.enter_ratio == pytest.approx(
        PINCH_RATIO_MAX - PinchCalibrator.MIN_HYSTERESIS
    )

    low = PinchCalibrator()
    _feed_ratios(low, [0.001] * 10)
    low_result = low.thresholds()

    assert low_result is not None
    assert low_result.enter_ratio == pytest.approx(PINCH_RATIO_MIN)
    assert low_result.exit_ratio == pytest.approx(
        PINCH_RATIO_MIN + PinchCalibrator.MIN_HYSTERESIS
    )
    assert low_result.enter_ratio < low_result.exit_ratio


def test_calibrated_thresholds_can_be_injected_into_the_classifier():
    calibrator = PinchCalibrator()
    _feed_ratios(calibrator, [0.30] * 5 + [0.50] * 5)
    result = calibrator.thresholds()
    assert result is not None

    classifier = GestureClassifier()
    classifier.set_pinch_calibration(result.enter_ratio, result.exit_ratio)

    assert classifier.pinch_enter_ratio == pytest.approx(result.enter_ratio)
    assert classifier.pinch_exit_ratio == pytest.approx(result.exit_ratio)
    assert classifier.pinch_threshold == pytest.approx(
        result.enter_ratio * GestureClassifier.NOMINAL_PALM_SCALE_PX
    )

    with pytest.raises(ValueError):
        classifier.set_pinch_calibration(0.5, 0.4)
    with pytest.raises(ValueError):
        classifier.set_pinch_calibration(math.nan, 0.4)


def test_injected_calibration_controls_the_ratio_decision():
    # 0.35 的捏合比：默认阈值判定为未捏合，校准到 0.40/0.55 后判定为捏合。
    assert (
        GestureClassifier()._detect_raw_gesture(_pinch_hand(1.0, 42.0), 0.0)
        == "none"
    )

    calibrated = GestureClassifier()
    calibrated.set_pinch_calibration(0.40, 0.55)
    assert calibrated._detect_raw_gesture(_pinch_hand(1.0, 42.0), 0.0) == "pinch"


def test_legacy_pixel_threshold_assignment_is_migrated_to_ratios():
    # GUI 仍按像素配置阈值（默认 35），赋值后应换算成 35/120 与 50/120。
    classifier = GestureClassifier()
    classifier.pinch_threshold = 35.0

    assert classifier.pinch_threshold == pytest.approx(35.0)
    assert classifier.pinch_enter_ratio == pytest.approx(35.0 / 120.0)
    assert classifier.pinch_exit_ratio == pytest.approx(50.0 / 120.0)


def test_a_measured_calibration_is_staged_until_save(tmp_path):
    """Cancel must leave the live thresholds alone, like every other control."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from gui.settings_dialog import SettingsDialog
    from utils.config_manager import ConfigManager

    application = QApplication.instance() or QApplication([])
    config = ConfigManager(config_path=tmp_path / "settings.json")
    dialog = SettingsDialog(config)
    try:
        dialog._staged_calibration = {
            "enter_ratio": 0.30,
            "exit_ratio": 0.42,
            "sample_count": 11,
        }
        # Nothing is written merely because a calibration was measured.
        assert config.get("pinch_calibration") is None

        dialog.save_settings()
        application.processEvents()

        stored = config.get("pinch_calibration")
        assert stored["enter_ratio"] == 0.30
        assert stored["exit_ratio"] == 0.42
        assert stored["sample_count"] == 11
        assert dialog._staged_calibration is None
    finally:
        dialog.deleteLater()

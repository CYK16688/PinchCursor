"""手势分类模块 - 基于距离比例，更稳定"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Sequence

# MediaPipe 手部关键点索引（模块级辅助函数也需要）
WRIST_INDEX = 0
THUMB_TIP_INDEX = 4
INDEX_TIP_INDEX = 8
MIDDLE_MCP_INDEX = 9

# 捏合比值 = 拇指-食指指尖距离 / 手掌尺度。
# 捏合阈值必须钳制在有物理意义的区间内，避免坏样本把分类器推到极端。
PINCH_RATIO_MIN = 0.05
PINCH_RATIO_MAX = 0.9

# 手掌尺度失效时的回退阈值（像素），沿用旧版绝对阈值。
PINCH_FALLBACK_ENTER_PX = 35.0
PINCH_FALLBACK_EXIT_PX = 50.0


def palm_scale_from_landmarks(landmarks) -> float | None:
    """返回手掌尺度：手腕(0)到中指 MCP(9)的欧氏距离。

    管线传入的 landmark 已换算为像素坐标（x * 帧宽, y * 帧高），因此结果
    也是像素；但后续所有判定都以“捏合距离 / 手掌尺度”的比值进行，所以该
    量只用于归一化，分辨率与手掌远近会被自动抵消。

    非法或退化输入（landmark 数量不足、坐标非数值、坐标非有限值、手腕与
    中指 MCP 重合导致尺度为 0）返回 ``None``，调用方应回退到绝对像素阈值。
    """
    if landmarks is None:
        return None
    try:
        if len(landmarks) <= MIDDLE_MCP_INDEX:
            return None
        wrist = landmarks[WRIST_INDEX]
        middle_mcp = landmarks[MIDDLE_MCP_INDEX]
        dx = float(middle_mcp[0]) - float(wrist[0])
        dy = float(middle_mcp[1]) - float(wrist[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None

    scale = math.hypot(dx, dy)
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    return scale


def _coerce_positive_float(value) -> float | None:
    """把输入转成有限正浮点数；非法值返回 None。"""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result <= 0.0:
        return None
    return result


def _clamp_pinch_ratio(value: float) -> float:
    """把捏合比值钳制在 [PINCH_RATIO_MIN, PINCH_RATIO_MAX]。"""
    return min(max(value, PINCH_RATIO_MIN), PINCH_RATIO_MAX)


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """线性插值分位数，输入必须已升序排序；纯标准库且确定性。"""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


@dataclass(frozen=True)
class PinchCalibration:
    """一次性校准得到的捏合比值阈值。

    ``enter_ratio`` / ``exit_ratio`` 的单位都是“捏合距离 / 手掌尺度”，
    与摄像头分辨率和手到镜头距离无关。
    """

    enter_ratio: float
    exit_ratio: float
    sample_count: int = 0


class PinchCalibrator:
    """从若干帧观测中估计捏合阈值（比值空间，纯标准库、确定性）。

    用法：让用户做几次捏合/松开，逐帧调用 ``add_sample`` 收集“拇指-食指
    指尖距离”和对应“手掌尺度”；样本足够后调用 ``thresholds()``，把结果交给
    ``GestureClassifier.set_pinch_calibration``。

    进入阈值取比值分布的 p25（较容易触发），退出阈值取 p75（较难退出），
    两者之间形成滞后区，避免边界抖动。
    """

    MIN_SAMPLES = 10
    ENTER_PERCENTILE = 0.25
    EXIT_PERCENTILE = 0.75
    # 分布退化（所有样本相同）时强制拉开的最小滞后量。
    MIN_HYSTERESIS = 0.02

    def __init__(self):
        self._ratios: list[float] = []

    def add_sample(
        self,
        pinches: Sequence[float],
        palm_scales: Sequence[float],
    ) -> None:
        """收集一帧或多帧观测；非法样本被静默忽略。"""
        try:
            pairs = list(zip(pinches, palm_scales))
        except TypeError:
            return
        for pinch, palm_scale in pairs:
            try:
                pinch_value = float(pinch)
                scale_value = float(palm_scale)
            except (TypeError, ValueError):
                continue
            # 捏合距离可以为 0（两指尖完全贴合），掌尺必须严格为正。
            if not math.isfinite(pinch_value) or pinch_value < 0.0:
                continue
            if not math.isfinite(scale_value) or scale_value <= 0.0:
                continue
            self._ratios.append(pinch_value / scale_value)

    @property
    def sample_count(self) -> int:
        """已收集的有效样本数。"""
        return len(self._ratios)

    def thresholds(self) -> PinchCalibration | None:
        """返回校准阈值；有效样本少于 10 个时返回 None。"""
        if len(self._ratios) < self.MIN_SAMPLES:
            return None

        ordered = sorted(self._ratios)
        enter = _clamp_pinch_ratio(_percentile(ordered, self.ENTER_PERCENTILE))
        exit_ = _clamp_pinch_ratio(_percentile(ordered, self.EXIT_PERCENTILE))

        # 退化分布下 p25 == p75：优先抬高退出阈值，若已到上限则压低进入阈值。
        if exit_ <= enter:
            exit_ = _clamp_pinch_ratio(enter + self.MIN_HYSTERESIS)
        if exit_ <= enter:
            enter = _clamp_pinch_ratio(exit_ - self.MIN_HYSTERESIS)
        if exit_ <= enter:
            return None

        return PinchCalibration(
            enter_ratio=enter,
            exit_ratio=exit_,
            sample_count=len(self._ratios),
        )


class GestureClassifier:
    """手势分类器 - 使用距离比例判断，对旋转更鲁棒。

    捏合判定不再使用绝对像素阈值，而是用“捏合距离 / 手掌尺度”的比值：

        ratio = ||THUMB_TIP - INDEX_TIP|| / ||WRIST - MIDDLE_MCP||

    因此同一动作在 640x480 与 1280x960、或手离镜头远近变化时判定一致。
    默认阈值按 640x480 常见手型推算：``palm_scale`` 约 120 px，旧版 35 px /
    50 px 的进入/退出阈值分别对应 ``35/120≈0.29`` 与 ``50/120≈0.42``，所以
    在原始分辨率、原始手型下行为与旧版基本一致。需要适配个人手型时，可用
    :class:`PinchCalibrator` 采样后调用 :meth:`set_pinch_calibration` 注入。

    当手掌尺度不可用（退化或非法 landmark）时，回退到旧版绝对像素阈值
    （``pinch_threshold`` / ``pinch_exit_threshold``），保证不会崩溃。
    """

    # MediaPipe 手部关键点索引
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20

    # ---- 捏合归一化参数 ----
    # 默认比值来源假设：640x480 画面中，手腕到中指 MCP 约 120 px，
    # 旧版绝对阈值 35 px（进入）/ 50 px（退出）→ 0.29 / 0.42。
    NOMINAL_PALM_SCALE_PX = 120.0
    DEFAULT_PINCH_ENTER_RATIO = 0.29
    DEFAULT_PINCH_EXIT_RATIO = 0.42
    # 旧版退出/进入阈值的比例（50/35），用于让 GUI 传入的像素阈值仍按
    # 原有滞后宽度换算成比值。
    LEGACY_EXIT_ENTER_RATIO = 50.0 / 35.0
    # point 判定要求捏合距离足够远，旧版为 80 px → 80/120。
    POINT_MIN_PINCH_RATIO = 80.0 / 120.0

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        # 扩展手势列表 - 参考MediaPipe/Vision Pro/Android XR
        self.gestures = [
            "none",
            # 基础手势
            "point",        # 指向 - 食指伸出
            "pinch",        # 捏合 - 拇指食指捏合
            "pinch_hold",   # 捏合长按
            "open_hand",    # 张开手掌
            "fist",         # 握拳
            "peace",        # 剪刀手/胜利
            "ilove_you",    # 我爱你手势 - 拇指、食指、小指伸出
            # 新增手势
            "thumb_up",     # 拇指向上（点赞）
            "thumb_down",   # 拇指向下
            "ok",           # OK手势
            "rock",         # 摇滚手势（拇指+小指）
            "three",        # 三指
        ]
        # 捏合状态跟踪
        self.pinch_start_time = None
        # 归一化阈值（无量纲，ratio = 捏合距离 / 手掌尺度）。
        self._pinch_enter_ratio = self.DEFAULT_PINCH_ENTER_RATIO
        self._pinch_exit_ratio = self.DEFAULT_PINCH_EXIT_RATIO
        # 回退阈值（像素）：仅当 palm_scale 不可用时使用，保持旧行为。
        self._pinch_threshold_px = PINCH_FALLBACK_ENTER_PX
        self._pinch_exit_threshold_px = PINCH_FALLBACK_EXIT_PX
        # 退出阈值是否被显式校准过；未被显式校准时跟随进入阈值按 50/35 缩放。
        self._pinch_exit_explicit = False
        self.hold_threshold = 0.3  # 长按阈值(秒)
        self.in_pinch_state = False  # 当前是否处于捏合状态

        # 双击检测
        self.last_pinch_time = None
        self.double_tap_threshold = 0.35  # 双击时间窗口
        self.was_pinching = False
        # Set on the frame the pinch physically opens. The hysteresis band
        # (enter 0.29, exit 0.42) already makes that a decisive signal, so the
        # stabiliser may leave the pinch immediately instead of also waiting out
        # exit_threshold frames of a different label.
        self._pinch_release_streak = 0
        self._release_measure = None
        self._release_threshold = None

        # 捏合预测 - 通过监测距离变化速度
        self.pinch_dist_history = []  # 捏合距离历史
        self.pinch_time_history = []  # 对应的时间戳
        self.pinch_history_size = 5   # 历史大小
        self.last_pinch_dist = None   # 上一帧的捏合距离
        self.pinch_velocity = 0       # 捏合速度（负值表示正在捏合）

        # 手势稳定化参数 - 防抖动
        self.confirm_threshold = 3  # 确认阈值(需要N帧相同才能进入新手势)
        self.exit_threshold = 4  # 退出阈值(需要N帧不同才能离开当前手势)
        self.current_stable_gesture = "none"  # 当前稳定手势
        self.gesture_switch_time = None  # 上次切换时间
        self.min_switch_interval = 0.15  # 最小切换间隔(秒)
        self.cooldown_time = 0.2  # 切换后冷却时间(秒)
        self.consecutive_count = 0  # 连续相同手势计数
        self.last_raw_gesture = "none"  # 上一帧原始手势
        self.none_count = 0  # 连续none计数(用于快速退出)

    # ------------------------------------------------------------------
    @property
    def pinch_enter_ratio(self) -> float:
        """Current entering threshold as pinch-distance / palm-scale."""
        return self._pinch_enter_ratio

    @property
    def pinch_exit_ratio(self) -> float:
        """Current exit threshold as pinch-distance / palm-scale."""
        return self._pinch_exit_ratio

    # 捏合阈值：对外保留 pinch_threshold / pinch_exit_threshold 像素属性，
    # 内部判定统一使用比值；像素属性同时作为 palm_scale 不可用时的回退。
    # ------------------------------------------------------------------

    @property
    def pinch_threshold(self) -> float:
        """捏合进入阈值的像素表示（旧 API / 回退值）。

        赋值（GUI 配置路径）会按 ``NOMINAL_PALM_SCALE_PX`` 反推进入比值，
        从而让持久化的像素阈值在标称构图中保持原意；若退出阈值没有被显式
        校准，则按旧版 50/35 的比例同步缩放，维持滞后宽度。
        """
        return self._pinch_threshold_px

    @pinch_threshold.setter
    def pinch_threshold(self, value) -> None:
        pixels = _coerce_positive_float(value)
        if pixels is None:
            return
        self._pinch_threshold_px = pixels
        self._pinch_enter_ratio = _clamp_pinch_ratio(
            pixels / self.NOMINAL_PALM_SCALE_PX
        )
        if not self._pinch_exit_explicit:
            exit_pixels = pixels * self.LEGACY_EXIT_ENTER_RATIO
            self._pinch_exit_threshold_px = exit_pixels
            self._pinch_exit_ratio = _clamp_pinch_ratio(
                exit_pixels / self.NOMINAL_PALM_SCALE_PX
            )

    @property
    def pinch_exit_threshold(self) -> float:
        """捏合退出阈值的像素表示（旧 API / 回退值）。"""
        return self._pinch_exit_threshold_px

    @pinch_exit_threshold.setter
    def pinch_exit_threshold(self, value) -> None:
        pixels = _coerce_positive_float(value)
        if pixels is None:
            return
        self._pinch_exit_threshold_px = pixels
        self._pinch_exit_ratio = _clamp_pinch_ratio(
            pixels / self.NOMINAL_PALM_SCALE_PX
        )
        self._pinch_exit_explicit = True

    @property
    def pinch_enter_ratio(self) -> float:
        """进入捏合的归一化阈值（捏合距离 / 手掌尺度）。"""
        return self._pinch_enter_ratio

    @property
    def pinch_exit_ratio(self) -> float:
        """退出捏合的归一化阈值（必须大于进入阈值以保留滞后）。"""
        return self._pinch_exit_ratio

    def set_pinch_calibration(self, enter_ratio: float, exit_ratio: float) -> None:
        """注入一次性校准得到的归一化捏合阈值。

        :param enter_ratio: 进入阈值，ratio = 拇指-食指指尖距离 / 手掌尺度
        :param exit_ratio: 退出阈值，必须严格大于 ``enter_ratio``
        :raises ValueError: 参数非有限正数，或钳制后不满足 enter < exit
        """
        enter = _coerce_positive_float(enter_ratio)
        exit_ = _coerce_positive_float(exit_ratio)
        if enter is None or exit_ is None:
            raise ValueError("pinch ratios must be finite positive numbers")

        enter = _clamp_pinch_ratio(enter)
        exit_ = _clamp_pinch_ratio(exit_)
        if exit_ <= enter:
            raise ValueError("exit_ratio must be greater than enter_ratio")

        self._pinch_enter_ratio = enter
        self._pinch_exit_ratio = exit_
        # 同步像素表示，使 palm_scale 不可用时的回退也遵循同一校准。
        self._pinch_threshold_px = enter * self.NOMINAL_PALM_SCALE_PX
        self._pinch_exit_threshold_px = exit_ * self.NOMINAL_PALM_SCALE_PX
        self._pinch_exit_explicit = True

    def _pinch_thresholds_for(
        self, palm_scale: float | None
    ) -> tuple[float, float]:
        """返回与当前测量值同单位的 (进入阈值, 退出阈值)。"""
        if palm_scale is None:
            return self._pinch_threshold_px, self._pinch_exit_threshold_px
        return self._pinch_enter_ratio, self._pinch_exit_ratio

    def _pinch_measure(self, landmarks, pinch_distance: float) -> tuple[float, float | None]:
        """返回 (归一化捏合量, 手掌尺度)；掌尺不可用时退回像素距离。"""
        palm_scale = palm_scale_from_landmarks(landmarks)
        if palm_scale is None:
            return pinch_distance, None
        return pinch_distance / palm_scale, palm_scale

    def classify(self, landmarks, timestamp=None):
        """Classify one frame using the supplied monotonic frame timestamp."""
        if not landmarks:
            self._reset_pinch_state()
            raw_gesture = "none"
        else:
            raw_gesture = self._detect_raw_gesture(landmarks, timestamp)

        return self._stabilize_gesture(raw_gesture, timestamp)

    def _detect_raw_gesture(self, landmarks, timestamp=None):
        """Detect the unstabilized gesture for one frame."""
        now = self._clock() if timestamp is None else timestamp
        fingers = self._get_finger_states(landmarks)

        # 检测捏合手势 (最高优先级) - 使用滞后机制防抖
        pinch_dist = self._get_pinch_distance(landmarks)
        # 归一化：ratio = 捏合距离 / 手掌尺度。掌尺不可用时退回像素距离。
        pinch_measure, palm_scale = self._pinch_measure(landmarks, pinch_dist)
        enter_threshold, exit_threshold = self._pinch_thresholds_for(palm_scale)

        # 滞后判断：进入捏合用较小阈值，退出捏合用较大阈值
        if self.in_pinch_state:
            # 已在捏合状态，需要超过退出阈值才退出
            is_pinching = pinch_measure < exit_threshold
        else:
            # 未在捏合状态，需要小于进入阈值才进入
            is_pinching = pinch_measure < enter_threshold

        # OK手势检测（拇指食指成圈+其他三指伸直）
        if self._is_ok_gesture(landmarks):
            self._reset_pinch_state()
            return "ok"

        if is_pinching:
            self.in_pinch_state = True
            # Any pinch frame restarts the release evidence from zero.
            self._pinch_release_streak = 0
            self._release_measure = None
            return self._handle_pinch(now)

        # Not pinching: accumulate how long the hand has been open, and how far
        # past the exit threshold it went. The stabiliser needs both to decide
        # whether this is a deliberate release or a noisy frame.
        self._pinch_release_streak += 1
        self._release_measure = pinch_measure
        self._release_threshold = exit_threshold

        # 捏合释放时重置状态。The release evidence above (`_pinch_release_streak`
        # and `_release_measure`) is what lets the stabiliser end a pinch without
        # waiting for exit_threshold frames of a different label.
        if self.was_pinching:
            self._on_pinch_release(now)

        # MediaPipe ILoveYou：拇指、食指、小指伸出，中指和无名指弯曲。
        # Keep this before the less-specific custom gesture checks below.
        if fingers == [1, 1, 0, 0, 1]:
            return "ilove_you"

        # 拇指手势检测
        thumb_dir = self._get_thumb_direction(landmarks)
        # 拇指向上：只有拇指伸出
        if thumb_dir == "up" and fingers[0] == 1 and sum(fingers[1:]) == 0:
            return "thumb_up"
        # 拇指向下
        if thumb_dir == "down" and fingers[0] == 1 and sum(fingers[1:]) == 0:
            return "thumb_down"

        # 摇滚手势：拇指+小指伸出
        if fingers[0] == 1 and fingers[4] == 1 and sum(fingers[1:4]) == 0:
            return "rock"


        # 指向: 食指伸直，其他弯曲
        # 排除拇指食指距离较近的情况（可能是正在捏合）
        point_min_measure = (
            self.POINT_MIN_PINCH_RATIO if palm_scale is not None else 80.0
        )
        if fingers[1] == 1 and sum(fingers) <= 2:
            if pinch_measure > point_min_measure:  # 距离足够远才是真正的point
                return "point"

        # 三指：食指+中指+无名指
        if fingers[1] == 1 and fingers[2] == 1 and fingers[3] == 1:
            if fingers[0] == 0 and fingers[4] == 0:
                return "three"

        # 剪刀手
        if fingers[1] == 1 and fingers[2] == 1 and sum(fingers) == 2:
            return "peace"

        # 张开手掌
        if sum(fingers) >= 4:
            return "open_hand"

        # 握拳 - 排除拇指食指距离较近的情况（可能是捏合边界状态）
        if sum(fingers) == 0:
            # 真正的握拳时，拇指食指距离应该较大（拇指在外侧）
            if pinch_measure > exit_threshold:
                return "fist"
            # 距离较近时返回none，避免误识别
            return "none"

        return "none"

    def _get_finger_states(self, landmarks):
        """获取5个手指的伸直状态 - 基于距离比例"""
        states = []

        # 计算手掌参考点 (手腕和中指MCP的中点)
        wrist = landmarks[self.WRIST]
        middle_mcp = landmarks[self.MIDDLE_MCP]
        palm_cx = (wrist[0] + middle_mcp[0]) / 2
        palm_cy = (wrist[1] + middle_mcp[1]) / 2

        # 拇指: 比较TIP到食指MCP的距离
        thumb_tip = landmarks[self.THUMB_TIP]
        index_mcp = landmarks[self.INDEX_MCP]
        thumb_dist = self._distance(thumb_tip, index_mcp)
        # 拇指伸直时距离食指MCP较远
        palm_size = self._distance(wrist, middle_mcp)
        states.append(1 if thumb_dist > palm_size * 0.6 else 0)

        # 其他四指: 比较TIP到手腕的距离与MCP到手腕的距离
        finger_data = [
            (self.INDEX_MCP, self.INDEX_TIP),
            (self.MIDDLE_MCP, self.MIDDLE_TIP),
            (self.RING_MCP, self.RING_TIP),
            (self.PINKY_MCP, self.PINKY_TIP),
        ]

        for mcp_idx, tip_idx in finger_data:
            mcp = landmarks[mcp_idx]
            tip = landmarks[tip_idx]
            # 计算到手腕的距离
            mcp_dist = self._distance(mcp, wrist)
            tip_dist = self._distance(tip, wrist)
            # 手指伸直时，指尖到手腕的距离 > MCP到手腕的距离
            states.append(1 if tip_dist > mcp_dist * 1.1 else 0)

        return states

    def _distance(self, p1, p2):
        """计算两点之间的距离"""
        dx = p1[0] - p2[0]
        dy = p1[1] - p2[1]
        return math.sqrt(dx * dx + dy * dy)

    def _get_thumb_direction(self, landmarks):
        """获取拇指方向: 'up', 'down', 'side' 或 'none'"""
        thumb_tip = landmarks[self.THUMB_TIP]
        thumb_mcp = landmarks[self.THUMB_MCP]
        wrist = landmarks[self.WRIST]

        # 计算拇指向量
        dx = thumb_tip[0] - thumb_mcp[0]
        dy = thumb_tip[1] - thumb_mcp[1]

        # 判断方向（y轴向下为正）
        if abs(dy) > abs(dx) * 1.5:  # 主要是垂直方向
            if dy < -20:  # 向上
                return "up"
            elif dy > 20:  # 向下
                return "down"
        return "side"

    def _is_ok_gesture(self, landmarks):
        """检测OK手势 - 拇指食指成圈，其他三指伸直"""
        fingers = self._get_finger_states(landmarks)
        # 拇指和食指接近（成圈），使用与分辨率无关的手掌尺度比值。
        pinch_dist = self._get_pinch_distance(landmarks)
        pinch_measure, palm_scale = self._pinch_measure(landmarks, pinch_dist)
        if palm_scale is None:
            pinch_limit = self._pinch_threshold_px * 1.2
        else:
            pinch_limit = self._pinch_enter_ratio * 1.2
        # 中指、无名指、小指伸直
        other_extended = fingers[2] == 1 and fingers[3] == 1 and fingers[4] == 1
        return pinch_measure < pinch_limit and other_extended

    def _get_pinch_distance(self, landmarks):
        """计算拇指和食指指尖的距离"""
        thumb = landmarks[self.THUMB_TIP]
        index = landmarks[self.INDEX_TIP]
        dx = thumb[0] - index[0]
        dy = thumb[1] - index[1]
        return math.sqrt(dx * dx + dy * dy)

    def get_pinch_info(self, landmarks, timestamp=None):
        """Return pinch distance and velocity for one monotonic frame timestamp."""
        if not landmarks:
            self.pinch_dist_history.clear()
            self.pinch_time_history.clear()
            self.last_pinch_dist = None
            self.pinch_velocity = 0
            return {
            'distance': 999,
            'velocity': 0,
            'is_approaching': False,
            'is_pinching': False,
        }

        now = self._clock() if timestamp is None else timestamp
        dist = self._get_pinch_distance(landmarks)

        # 记录历史
        self.pinch_dist_history.append(dist)
        self.pinch_time_history.append(now)
        if len(self.pinch_dist_history) > self.pinch_history_size:
            self.pinch_dist_history.pop(0)
            self.pinch_time_history.pop(0)

        # 计算速度（使用最近几帧的平均变化率）
        velocity = 0
        if len(self.pinch_dist_history) >= 2:
            dt = self.pinch_time_history[-1] - self.pinch_time_history[0]
            if dt > 0:
                dd = self.pinch_dist_history[-1] - self.pinch_dist_history[0]
                velocity = dd / dt  # 像素/秒

        self.pinch_velocity = velocity
        self.last_pinch_dist = dist

        # 判断是否正在快速靠近（预测即将捏合）
        # 条件：速度为负（距离在减小）且速度足够快
        approach_threshold = -150  # 像素/秒，负值表示靠近
        is_approaching = velocity < approach_threshold and dist < 80

        return {
            'distance': dist,
            'velocity': velocity,
            'is_approaching': is_approaching,
            # Raw, hysteresis-backed pinch state. It flips on the frame the
            # fingers actually close, two or three frames before the stabiliser
            # confirms the label, which is what lets the pointer stop tracking
            # at the moment of the pinch instead of after it.
            'is_pinching': bool(self.in_pinch_state),
        }

    def _handle_pinch(self, now):
        """处理捏合手势"""
        if self.pinch_start_time is None:
            self.pinch_start_time = now
        self.was_pinching = True

        # 判断是短按还是长按
        duration = now - self.pinch_start_time
        if duration > self.hold_threshold:
            return "pinch_hold"
        return "pinch"

    def _on_pinch_release(self, now):
        """捏合释放时调用"""
        self.last_pinch_time = now
        self._reset_pinch_state()

    def _reset_pinch_state(self):
        """重置捏合状态"""
        self.pinch_start_time = None
        self.was_pinching = False
        self.in_pinch_state = False

    def is_double_tap(self, timestamp=None):
        """Check the double-tap window against a monotonic timestamp."""
        if self.last_pinch_time is None:
            return False
        now = self._clock() if timestamp is None else timestamp
        return now - self.last_pinch_time < self.double_tap_threshold

    # A release must overshoot the exit threshold by this factor to skip the
    # confirmation frames. Below it the opening is ambiguous.
    RELEASE_MARGIN = 1.15
    # Consecutive release frames before the fast path is allowed.
    RELEASE_CONFIRM_FRAMES = 2

    def _release_decisive(self) -> bool:
        """True when the pinch opened far enough past the exit threshold."""
        measure = self._release_measure
        threshold = self._release_threshold
        if measure is None or threshold is None:
            return False
        try:
            return float(measure) >= float(threshold) * self.RELEASE_MARGIN
        except (TypeError, ValueError):
            return False

    def _stabilize_gesture(self, raw_gesture, timestamp=None):
        """Stabilize raw labels against a monotonic frame timestamp."""
        now = self._clock() if timestamp is None else timestamp

        # A pinch that physically opened may leave immediately. Waiting for
        # exit_threshold frames of a different *label* on top of the pinch's own
        # hysteresis made two clicks need 233 ms of release, which ruled out any
        # quick repeat. Entry is untouched: re-pinching still needs
        # confirm_threshold frames, and the enter threshold is stricter than the
        # exit one, so the label cannot oscillate.
        decisive = (
            self._pinch_release_streak >= self.RELEASE_CONFIRM_FRAMES
            and self._release_decisive()
        )
        if (
            decisive
            and self.current_stable_gesture in {"pinch", "pinch_hold"}
            and raw_gesture != self.current_stable_gesture
        ):
            self.current_stable_gesture = raw_gesture
            # Clear the switch clock rather than stamping it. The cooldown exists
            # to stop the label bouncing immediately after a switch, but a
            # physical release already proves the previous gesture is finished,
            # and stamping `now` would then demand exit_threshold + 1 frames to
            # re-enter — the very delay this change is meant to remove.
            self.gesture_switch_time = None
            self.consecutive_count = 1
            return self.current_stable_gesture

        # 更新连续计数
        if raw_gesture == self.last_raw_gesture:
            self.consecutive_count += 1
        else:
            self.consecutive_count = 1
        self.last_raw_gesture = raw_gesture

        # 单独跟踪none计数
        if raw_gesture == "none":
            self.none_count += 1
        else:
            self.none_count = 0

        # 如果是当前手势，直接保持
        if raw_gesture == self.current_stable_gesture:
            return self.current_stable_gesture

        # 检查最小切换间隔
        if self.gesture_switch_time is not None:
            elapsed = now - self.gesture_switch_time
            # 冷却期内需要更高的阈值
            if elapsed < self.cooldown_time:
                required = self.exit_threshold + 1
            elif elapsed < self.min_switch_interval:
                return self.current_stable_gesture
            else:
                required = self.confirm_threshold

            # 从有效手势切换到none需要更多帧确认
            if self.current_stable_gesture != "none" and raw_gesture == "none":
                required = self.exit_threshold

            if self.consecutive_count >= required:
                self.current_stable_gesture = raw_gesture
                self.gesture_switch_time = now
        else:
            # 首次切换
            if self.consecutive_count >= self.confirm_threshold:
                self.current_stable_gesture = raw_gesture
                self.gesture_switch_time = now

        return self.current_stable_gesture

    def reset_stabilization(self):
        """重置稳定化状态"""
        self.current_stable_gesture = "none"
        self.gesture_switch_time = None
        self.consecutive_count = 0
        self.last_raw_gesture = "none"
        self.none_count = 0

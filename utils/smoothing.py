"""平滑滤波器 - One-Euro Filter 实现"""

import math
import time
from collections import deque


class LowPassFilter:
    """低通滤波器"""

    def __init__(self, alpha=0.5):
        self.alpha = alpha
        self.prev = None
        self.initialized = False

    def filter(self, value):
        if not self.initialized:
            self.prev = value
            self.initialized = True
            return value
        result = self.alpha * value + (1 - self.alpha) * self.prev
        self.prev = result
        return result

    def set_alpha(self, alpha):
        self.alpha = alpha


class OneEuroFilter:
    """
    One-Euro Filter - 自适应低通滤波器
    低速时减少抖动，高速时减少延迟
    """

    def __init__(self, freq=30, mincutoff=1.0, beta=0.007, dcutoff=1.0, clock=time.monotonic):
        self._clock = clock
        self.freq = freq
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self.x_filter = LowPassFilter()
        self.dx_filter = LowPassFilter()
        self.last_time = None

    def _alpha(self, cutoff):
        tau = 1.0 / (2 * math.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, x, timestamp=None):
        if timestamp is None:
            timestamp = self._clock()

        if self.last_time is not None:
            self.freq = 1.0 / (timestamp - self.last_time + 1e-8)
        self.last_time = timestamp

        # 计算导数
        if self.x_filter.initialized:
            dx = (x - self.x_filter.prev) * self.freq
        else:
            dx = 0

        # 滤波导数
        self.dx_filter.set_alpha(self._alpha(self.dcutoff))
        edx = self.dx_filter.filter(dx)

        # 自适应截止频率
        cutoff = self.mincutoff + self.beta * abs(edx)
        self.x_filter.set_alpha(self._alpha(cutoff))

        return self.x_filter.filter(x)

    def reset(self):
        self.x_filter = LowPassFilter()
        self.dx_filter = LowPassFilter()
        self.last_time = None



# --- smoothing preference -> filter parameter --------------------------------
#
# The settings surface exposes one "smoothing" dial, persisted as 0.001-0.020.
# It controlled ``beta``, which is the *high-speed* term: raising beta makes the
# filter follow fast motion more closely and does essentially nothing to the
# jitter of a resting hand (measured: 0.001 -> 10 px, 0.020 -> 13 px, i.e. the
# dial made resting jitter slightly *worse* in the direction users expected it to
# help). The parameter that governs resting jitter is ``mincutoff``.
#
# Measured on this machine at 30 fps (jitter of a still hand, mapped 640x480 ->
# 2560x1440):
#
#     mincutoff   resting jitter   90 % step response
#       0.5           8.0 px             67 ms
#       1.5          11.0 px             67 ms
#       3.0          14.0 px             67 ms
#
# The step response is unchanged because beta dominates during motion, so
# trading jitter against mincutoff costs no perceived latency. That is what makes
# this a safe dial to expose.
SM00THING_MIN = 0.001
SM00THING_MAX = 0.020
SM00THING_DEFAULT = 0.005
MINCUTOFF_AT_DEFAULT = 1.5
MINCUTOFF_FLOOR = 0.5
MINCUTOFF_CEILING = 3.5
# High-speed term. Raising it makes deliberate moves track the hand more
# tightly at the cost of some jitter during acceleration; the measured
# default is the value that kept the 90 % step response at two frames.
CURSOR_SMOOTHING_BETA = 0.005
# Resting-jitter radius, in screen points. This bounds immediate motion, not
# reachable positions: sustained small corrections are admitted by a separate
# time-based stability check below.
DEFAULT_DEAD_ZONE = 8.0
# < 1 so the range is not wildly asymmetric; 0.45 puts 0.001 at ~3.1 and 0.020
# at ~0.8, both well inside the useful band measured above.
_SMOOTHING_EXPONENT = 0.45


def mincutoff_for_smoothing(value, *, default: float = MINCUTOFF_AT_DEFAULT) -> float:
    """Map the persisted smoothing preference onto the 1€ ``mincutoff``.

    Larger preference = more smoothing = *lower* cutoff. Malformed values fall
    back to ``default`` so a corrupt settings file cannot make the cursor
    unusable.
    """
    try:
        preference = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(preference) or preference <= 0.0:
        return default
    preference = min(max(preference, SM00THING_MIN), SM00THING_MAX)
    cutoff = default * (SM00THING_DEFAULT / preference) ** _SMOOTHING_EXPONENT
    return min(max(cutoff, MINCUTOFF_FLOOR), MINCUTOFF_CEILING)


class CursorSmoother:
    """鼠标光标平滑器 - 触控板式丝滑效果"""

    def __init__(
        self,
        mincutoff=1.5,
        beta=0.005,
        dead_zone=DEFAULT_DEAD_ZONE,
        clock=time.monotonic,
    ):
        # 调整参数：更高的mincutoff减少延迟，更低的beta增加平滑
        self._clock = clock
        self.filter_x = OneEuroFilter(mincutoff=mincutoff, beta=beta, clock=clock)
        self.filter_y = OneEuroFilter(mincutoff=mincutoff, beta=beta, clock=clock)
        try:
            value = float(dead_zone)
        except (TypeError, ValueError):
            value = 0.0
        # A NaN or negative zone would either lock the pointer forever or
        # disable the feature; clamp rather than propagate.
        self.dead_zone = value if math.isfinite(value) and value > 0.0 else 0.0
        self._anchor = None
        self._recent_positions = deque()
        self.last_x = None
        self.last_y = None
        self.last_time = None

    def smooth(self, x, y, timestamp=None):
        t = self._clock() if timestamp is None else timestamp

        # 应用One-Euro滤波
        smooth_x = self.filter_x.filter(x, t)
        smooth_y = self.filter_y.filter(y, t)

        # One-Euro already adapts its cutoff to motion. Multiplying its output
        # displacement by an extra acceleration factor can overshoot both the
        # target and the desktop bounds, so no second acceleration is applied.
        #
        # Immediate large moves advance by the excess over the jitter radius.
        # A consistently observed small correction is allowed to settle all
        # the way to its target, including a screen edge. The previous spatial
        # dead zone permanently removed the final radius from every move.
        if self.dead_zone > 0.0:
            if self._anchor is None:
                self._anchor = (smooth_x, smooth_y)
            dx = smooth_x - self._anchor[0]
            dy = smooth_y - self._anchor[1]
            distance = math.hypot(dx, dy)
            if distance > self.dead_zone:
                travel = (distance - self.dead_zone) / distance
                self._anchor = (
                    self._anchor[0] + dx * travel,
                    self._anchor[1] + dy * travel,
                )
            if self._has_stable_correction(x, y, t):
                dt = max(0.0, t - self.last_time) if self.last_time is not None else 0.0
                # Time-based relaxation has the same settling behavior across
                # camera frame rates and never advances past the filtered aim.
                alpha = -math.expm1(-dt / 0.045)
                self._anchor = (
                    self._anchor[0] + (smooth_x - self._anchor[0]) * alpha,
                    self._anchor[1] + (smooth_y - self._anchor[1]) * alpha,
                )
            smooth_x, smooth_y = self._anchor

        self.last_x = smooth_x
        self.last_y = smooth_y
        self.last_time = t

        return smooth_x, smooth_y

    def _has_stable_correction(self, x, y, timestamp):
        """Accept small motion only when raw evidence stays spatially coherent.

        Test raw input rather than filtered output: a strong filter can make
        noisy observations appear stationary. A 120 ms window plus at least
        three observations keeps isolated noisy frames from moving the anchor.
        This does not claim to infer intent from arbitrary tremor; noisy aiming
        still trades precision for stability through the configured radius.
        """
        if self.last_time is not None and (
            timestamp <= self.last_time or timestamp - self.last_time > 0.25
        ):
            self._recent_positions.clear()
        self._recent_positions.append((timestamp, x, y))
        cutoff = timestamp - 0.12
        # Keep the observation immediately before the time boundary, so a
        # 15 Hz camera does not lose all evidence spanning 120 ms.
        while len(self._recent_positions) > 2 and self._recent_positions[1][0] <= cutoff:
            self._recent_positions.popleft()
        if len(self._recent_positions) < 3 or timestamp - self._recent_positions[0][0] < 0.12:
            return False
        xs = [point[1] for point in self._recent_positions]
        ys = [point[2] for point in self._recent_positions]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        return spread <= max(0.5, min(1.0, self.dead_zone / 8.0))

    def reset(self):
        self.filter_x.reset()
        self.filter_y.reset()
        self._anchor = None
        self._recent_positions.clear()
        self.last_x = None
        self.last_y = None
        self.last_time = None

"""平滑滤波器 - One-Euro Filter 实现"""

import math
import time


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


class CursorSmoother:
    """鼠标光标平滑器 - 触控板式丝滑效果"""

    def __init__(self, mincutoff=1.5, beta=0.005, clock=time.monotonic):
        # 调整参数：更高的mincutoff减少延迟，更低的beta增加平滑
        self._clock = clock
        self.filter_x = OneEuroFilter(mincutoff=mincutoff, beta=beta, clock=clock)
        self.filter_y = OneEuroFilter(mincutoff=mincutoff, beta=beta, clock=clock)
        self.last_x = None
        self.last_y = None
        self.last_time = None

    def smooth(self, x, y, timestamp=None):
        t = self._clock() if timestamp is None else timestamp

        # 应用One-Euro滤波
        smooth_x = self.filter_x.filter(x, t)
        smooth_y = self.filter_y.filter(y, t)

        # 计算速度并应用加速曲线
        if self.last_x is not None and self.last_time is not None:
            dt = t - self.last_time
            if dt > 0:
                # 计算移动速度
                speed = math.sqrt((smooth_x - self.last_x)**2 +
                                  (smooth_y - self.last_y)**2) / dt

                # 触控板式加速曲线：慢速精确，快速加速
                if speed > 500:  # 快速移动
                    accel = 1.3
                elif speed > 200:  # 中速移动
                    accel = 1.1
                else:  # 慢速移动 - 精确控制
                    accel = 1.0

                # 应用加速
                dx = (smooth_x - self.last_x) * accel
                dy = (smooth_y - self.last_y) * accel
                smooth_x = self.last_x + dx
                smooth_y = self.last_y + dy

        self.last_x = smooth_x
        self.last_y = smooth_y
        self.last_time = t

        return int(smooth_x), int(smooth_y)

    def reset(self):
        self.filter_x.reset()
        self.filter_y.reset()
        self.last_x = None
        self.last_y = None
        self.last_time = None

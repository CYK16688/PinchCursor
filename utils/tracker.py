"""目标跟踪器 - 防止手部丢失时光标跳动，支持边缘预测"""

import time


class TargetTracker:
    """跟踪手部位置，丢失时进行预测，支持边缘延续"""

    # 边缘区域定义（相对于画面尺寸的比例）
    EDGE_MARGIN = 0.1  # 边缘区域占10%

    def __init__(self, lost_threshold=0.5, momentum=0.7, clock=time.monotonic):
        self._clock = clock
        self.lost_threshold = lost_threshold  # 丢失判定时间(秒)
        self.momentum = momentum  # 动量系数

        self.last_pos = None
        self.velocity = (0, 0)
        self.last_time = None
        self.lost_time = None
        self.smooth_pos = None  # 平滑位置

        # 边缘预测增强
        self.frame_size = (640, 480)  # 默认画面尺寸
        self.at_edge = False  # 是否在边缘
        self.edge_direction = (0, 0)  # 边缘方向
        self.pre_lost_velocity = (0, 0)  # 丢失前的速度（用于边缘预测）

    def update(self, landmarks, frame_shape=None, timestamp=None):
        """更新跟踪状态

        Args:
            landmarks: 手部关键点列表
            frame_shape: 画面尺寸 (height, width, ...)
        """
        now = self._clock() if timestamp is None else timestamp

        # 更新画面尺寸
        if frame_shape:
            self.frame_size = (frame_shape[1], frame_shape[0])  # (width, height)

        if landmarks:
            # 检测到手部 - 使用食指指尖
            raw_pos = (landmarks[8][0], landmarks[8][1])

            # 平滑位置更新
            if self.smooth_pos is None:
                self.smooth_pos = raw_pos
            else:
                alpha = 0.6
                self.smooth_pos = (
                    alpha * raw_pos[0] + (1 - alpha) * self.smooth_pos[0],
                    alpha * raw_pos[1] + (1 - alpha) * self.smooth_pos[1]
                )

            pos = (int(self.smooth_pos[0]), int(self.smooth_pos[1]))

            # 计算速度
            if self.last_pos and self.last_time:
                dt = now - self.last_time
                if dt > 0:
                    vx = (pos[0] - self.last_pos[0]) / dt
                    vy = (pos[1] - self.last_pos[1]) / dt
                    self.velocity = (
                        self.momentum * self.velocity[0] + (1 - self.momentum) * vx,
                        self.momentum * self.velocity[1] + (1 - self.momentum) * vy
                    )

            # 检测是否在边缘，并记录边缘方向
            self.at_edge, self.edge_direction = self._check_edge(pos)

            # 保存丢失前的速度（用于边缘预测）
            self.pre_lost_velocity = self.velocity

            self.last_pos = pos
            self.last_time = now
            self.lost_time = None
            return pos, True

        else:
            # 未检测到手部 - 进行预测
            return self._predict_position(now)

    def reset(self):
        """重置跟踪器"""
        self.last_pos = None
        self.velocity = (0, 0)
        self.last_time = None
        self.lost_time = None
        self.smooth_pos = None
        self.at_edge = False
        self.edge_direction = (0, 0)
        self.pre_lost_velocity = (0, 0)

    def _check_edge(self, pos):
        """检测位置是否在边缘区域

        Returns:
            (is_at_edge, direction): direction为归一化的边缘方向向量
        """
        w, h = self.frame_size
        margin_x = w * self.EDGE_MARGIN
        margin_y = h * self.EDGE_MARGIN

        dx, dy = 0, 0

        # 检测水平边缘
        if pos[0] < margin_x:
            dx = -1  # 左边缘，向左
        elif pos[0] > w - margin_x:
            dx = 1   # 右边缘，向右

        # 检测垂直边缘
        if pos[1] < margin_y:
            dy = -1  # 上边缘，向上
        elif pos[1] > h - margin_y:
            dy = 1   # 下边缘，向下

        is_at_edge = dx != 0 or dy != 0
        return is_at_edge, (dx, dy)

    def _predict_position(self, now):
        """预测丢失后的位置"""
        if self.lost_time is None:
            self.lost_time = now

        if not self.last_pos:
            return None, False

        elapsed = now - self.lost_time
        dt = now - self.last_time

        # 边缘预测：如果丢失前在边缘且有向边缘方向的速度，延长预测时间
        extended_threshold = self.lost_threshold
        if self.at_edge:
            # 检查速度方向是否朝向边缘外
            vx, vy = self.pre_lost_velocity
            ex, ey = self.edge_direction
            # 速度与边缘方向同向时，延长预测
            if (ex != 0 and vx * ex > 0) or (ey != 0 and vy * ey > 0):
                extended_threshold = 0.8  # 边缘情况延长到0.8秒

        if elapsed < extended_threshold:
            # 使用衰减的速度预测
            decay = max(0, 1 - elapsed * 1.5)

            # 边缘模式：使用更强的预测
            if self.at_edge and elapsed < 0.5:
                # 边缘时使用丢失前的速度，衰减更慢
                vx, vy = self.pre_lost_velocity
                pred_x = self.last_pos[0] + vx * dt * 0.5 * decay
                pred_y = self.last_pos[1] + vy * dt * 0.5 * decay
            else:
                # 普通预测
                pred_x = self.last_pos[0] + self.velocity[0] * dt * 0.3 * decay
                pred_y = self.last_pos[1] + self.velocity[1] * dt * 0.3 * decay

            # 更新last_pos以便连续预测
            self.last_pos = (int(pred_x), int(pred_y))
            self.last_time = now

            return (int(pred_x), int(pred_y)), False

        return None, False

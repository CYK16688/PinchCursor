"""组合动作检测器 - 防误触的手势序列检测

改进机制：
1. 稳定性确认：第一个手势需保持N帧才算锁定
2. 过渡窗口：手势切换有合理的时间窗口
3. 冷却机制：执行后冷却防止连续误触
4. 取消机制：超时或回到none自动取消
"""

import time
from enum import Enum

from core.intent_arbiter import CORE_POINTER_GESTURES
from utils.config_manager import COMBO_ACTION_SET


class ComboState(Enum):
    """组合状态"""
    IDLE = "idle"           # 空闲，等待第一个手势
    LOCKING = "locking"     # 锁定中，第一个手势需要稳定
    READY = "ready"         # 就绪，等待第二个手势
    COOLDOWN = "cooldown"   # 冷却中


class ComboDetector:
    """防误触的组合手势检测器"""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.combos = []
        self.state = ComboState.IDLE

        # 当前检测状态
        self.current_gesture = "none"
        self.locked_gesture = None      # 锁定的第一个手势
        self.locked_combo = None        # 匹配的组合配置

        # 时间戳
        self.gesture_start_time = None  # 手势开始时间
        self.lock_time = None           # 锁定时间
        self.cooldown_start = None      # 冷却开始时间

        # 帧计数
        self.stable_frames = 0          # 稳定帧数

        # 参数（可配置）
        self.lock_frames = 5            # 锁定需要的稳定帧数
        self.transition_window = 0.8    # 过渡窗口时间(秒)
        self.cooldown_time = 0.3        # 冷却时间(秒)
        self.max_wait_time = 2.0        # 最大等待时间(秒)

    def set_combos(self, combos):
        """Install only shortcut combinations that cannot steal pointer control."""
        self.combos = [
            combo
            for combo in (combos or [])
            if isinstance(combo, dict)
            and combo.get("gesture1") not in CORE_POINTER_GESTURES
            and combo.get("gesture2") not in CORE_POINTER_GESTURES
            and combo.get("action") in COMBO_ACTION_SET
        ]
        # A settings refresh must not allow a partially observed old sequence to
        # complete using newly installed configuration.
        self.reset()

    def update(self, gesture, timestamp=None):
        """更新手势状态，返回匹配的动作或None"""
        now = self._clock() if timestamp is None else timestamp
        result = None

        # 冷却状态检查
        if self.state == ComboState.COOLDOWN:
            if now - self.cooldown_start >= self.cooldown_time:
                self._reset_to_idle()
            else:
                return None

        # 更新稳定帧计数
        if gesture == self.current_gesture:
            self.stable_frames += 1
        else:
            self.stable_frames = 1
            self.current_gesture = gesture
            self.gesture_start_time = now

        # 状态机处理
        if self.state == ComboState.IDLE:
            result = self._handle_idle(gesture, now)
        elif self.state == ComboState.LOCKING:
            result = self._handle_locking(gesture, now)
        elif self.state == ComboState.READY:
            result = self._handle_ready(gesture, now)

        return result

    def _handle_idle(self, gesture, now):
        """处理空闲状态"""
        if gesture == "none":
            return None

        # 检查是否是某个组合的第一个手势
        for combo in self.combos:
            if gesture == combo.get("gesture1"):
                self.state = ComboState.LOCKING
                self.locked_gesture = gesture
                self.locked_combo = combo
                self.gesture_start_time = now
                return None

        return None

    def _handle_locking(self, gesture, now):
        """处理锁定中状态"""
        # 超时检查
        if now - self.gesture_start_time > self.max_wait_time:
            self._reset_to_idle()
            return None

        # 手势变化检查
        if gesture != self.locked_gesture:
            # 如果变成none，取消锁定
            if gesture == "none":
                self._reset_to_idle()
                return None

            # 如果变成第二个手势，检查是否已经稳定足够帧数
            if gesture == self.locked_combo.get("gesture2"):
                if self.stable_frames >= self.lock_frames:
                    # 第一个手势已稳定，但还没进入READY就切换了
                    # 这种情况可能是误触，忽略
                    pass

            # 切换到其他手势，重新开始
            self._reset_to_idle()
            return self._handle_idle(gesture, now)

        # 检查是否稳定足够帧数
        if self.stable_frames >= self.lock_frames:
            self.state = ComboState.READY
            self.lock_time = now

        return None

    def _handle_ready(self, gesture, now):
        """处理就绪状态 - 等待第二个手势"""
        # 超时检查
        if now - self.lock_time > self.transition_window:
            self._reset_to_idle()
            return None

        # 如果回到none，继续等待（允许短暂的手势间隙）
        if gesture == "none":
            return None

        # 如果还是第一个手势，继续等待
        if gesture == self.locked_gesture:
            return None

        # 检查是否是第二个手势
        if gesture == self.locked_combo.get("gesture2"):
            # 匹配成功！
            action = self.locked_combo.get("action", "none")
            hotkey = self.locked_combo.get("hotkey", "")

            # 进入冷却
            self.state = ComboState.COOLDOWN
            self.cooldown_start = now

            return {"action": action, "hotkey": hotkey}

        # 其他手势，取消并重新检测
        self._reset_to_idle()
        return self._handle_idle(gesture, now)

    def _reset_to_idle(self):
        """重置到空闲状态"""
        self.state = ComboState.IDLE
        self.locked_gesture = None
        self.locked_combo = None
        self.lock_time = None

    def reset(self):
        """完全重置"""
        self._reset_to_idle()
        self.current_gesture = "none"
        self.stable_frames = 0
        self.gesture_start_time = None
        self.cooldown_start = None

    def get_state_info(self):
        """获取当前状态信息（用于调试/显示）"""
        return {
            "state": self.state.value,
            "locked_gesture": self.locked_gesture,
            "stable_frames": self.stable_frames
        }

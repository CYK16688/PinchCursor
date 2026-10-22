"""动作状态机 - Vision Pro风格的手势交互模型

核心机制：捏合预测 + 位置锁定
- 通过监测拇指-食指距离的变化速度，预测捏合开始
- 在检测到快速靠近时立即锁定位置
- 捏合完成时使用锁定位置执行点击

状态：
- MOVING: 移动模式，光标跟随手势移动
- LOCKING: 锁定中，检测到捏合趋势，位置已锁定
- CLICKING: 点击模式，执行点击动作
- DRAGGING: 拖动模式，捏合保持后进入
"""

import time
from math import isfinite
from enum import Enum


class ActionState(Enum):
    """动作状态枚举"""
    MOVING = "moving"      # 移动模式
    LOCKING = "locking"    # 锁定中（检测到捏合趋势）
    CLICKING = "clicking"  # 点击中
    DRAGGING = "dragging"  # 拖动中


class ActionStateMachine:
    """动作状态机 - 捏合预测实现精准点击。

    Time comes from an injected monotonic clock by default.  ``update`` also
    accepts an explicit timestamp for deterministic callers and replay tests.
    """

    def __init__(
        self,
        clock=None,
        dwell_threshold=0.3,
        move_threshold=8,
        drag_threshold=0.3,
        lock_confirmation_time=0.05,
    ):
        self._clock = clock or time.monotonic
        self.state = ActionState.MOVING
        self.last_pos = None
        self.locked_pos = None
        # Where the hand was when the target locked. ``locked_pos`` may have
        # been moved by aiming assist, so drag detection measures hand travel
        # from this anchor instead.
        self.lock_anchor = None
        self.pinch_start_time = None

        # These names are populated by the existing action_mode configuration.
        # Keep the legacy aliases below so callers that used the old internal
        # names continue to receive the same behavior.
        self.dwell_threshold = dwell_threshold
        self.move_threshold = move_threshold
        self.drag_threshold = drag_threshold

        self.on_state_change = None
        self.lock_time = None
        self.lock_timeout = 0.5

        # 动作冷却时间
        self.action_cooldown = 0.5
        self.last_action_time = 0
        self._last_timestamp = None

        # Approach velocity must persist briefly before it can lock a target.
        self.lock_confirmation_time = lock_confirmation_time
        self._approach_start_time = None
        self._approach_pos = None

        # 区域规则系统
        self.screen_size = None
        self.zone_rules = []

        # Optional aiming assist. Called once, with the frame position, at the
        # moment a target locks; it returns the position to actually lock, or
        # None to keep the raw one. The machine never asks who the target is,
        # so it stays free of accessibility and Qt imports.
        self.snap_provider = None

    @property
    def click_max_time(self):
        """Backward-compatible alias for ``dwell_threshold``."""
        return self.dwell_threshold

    @click_max_time.setter
    def click_max_time(self, value):
        self.dwell_threshold = value

    @property
    def drag_min_time(self):
        """Backward-compatible alias for ``drag_threshold``."""
        return self.drag_threshold

    @drag_min_time.setter
    def drag_min_time(self, value):
        self.drag_threshold = value

    @property
    def drag_move_threshold(self):
        """Backward-compatible alias for ``move_threshold``."""
        return self.move_threshold

    @drag_move_threshold.setter
    def drag_move_threshold(self, value):
        self.move_threshold = value

    def update(self, gesture, pos, pinch_info=None, timestamp=None):
        """更新状态机

        Args:
            gesture: 当前手势
            pos: 当前位置 (screen_x, screen_y)
            pinch_info: 捏合信息 {'distance', 'velocity', 'is_approaching'}
            timestamp: Optional monotonic timestamp for deterministic replay.
        """
        now = self._clock() if timestamp is None else timestamp
        result = {
            'action': 'none',
            'pos': pos,
            'state': self.state,
            'is_locked': False
        }

        if not self._accept_timestamp(now):
            was_dragging = self.state is ActionState.DRAGGING
            result['pos'] = self.locked_pos or pos
            self.reset(clear_timestamp=False)
            result['action'] = 'drag_end' if was_dragging else 'none'
            result['state'] = self.state
            return result

        if pos is None:
            return result

        if pinch_info is None:
            pinch_info = {'distance': 999, 'velocity': 0, 'is_approaching': False}

        # 状态机处理
        if self.state == ActionState.MOVING:
            result = self._handle_moving(gesture, pos, pinch_info, now)
        elif self.state == ActionState.LOCKING:
            result = self._handle_locking(gesture, pos, pinch_info, now)
        elif self.state == ActionState.CLICKING:
            result = self._handle_clicking(gesture, pos, now)
        elif self.state == ActionState.DRAGGING:
            result = self._handle_dragging(gesture, pos, now)

        # 应用区域规则过滤
        if result['action'] not in ('none', 'move_cursor', 'drag_end'):
            if not self._is_action_allowed(result['action'], pos):
                result['action'] = 'none'
            else:
                self.last_action_time = now

        self.last_pos = pos
        result['state'] = self.state
        return result

    def _handle_moving(self, gesture, pos, pinch_info, now):
        """处理移动状态"""
        result = {
            'action': 'none',
            'pos': pos,
            'state': self.state,
            'is_locked': False
        }

        # 指向手势：移动光标
        if gesture == "point":
            result['action'] = 'move_cursor'
            result['pos'] = pos

        # Direct pinch detection is not delayed by the prediction gate.
        if gesture in ("pinch", "pinch_hold"):
            self._change_state(ActionState.CLICKING)
            self.locked_pos = self._snap(pos)
            self.lock_anchor = pos
            self.pinch_start_time = now
            self._clear_approach_confirmation()
            # 不立即触发点击，等待释放时判断；锁定的那一帧就报吸附后的位置，
            # 否则光标会先画在原处、下一帧才跳到目标上。
            result['pos'] = self.locked_pos

        # A single noisy velocity report must not lock the cursor.  Remember
        # the first credible approach position and lock only after sustained
        # confirmation.
        elif pinch_info['is_approaching']:
            if self._approach_start_time is None:
                self._approach_start_time = now
                self._approach_pos = pos
            elif now - self._approach_start_time >= self.lock_confirmation_time:
                self._change_state(ActionState.LOCKING)
                self.locked_pos = self._snap(self._approach_pos)
                self.lock_anchor = self._approach_pos
                self.lock_time = now
                self._clear_approach_confirmation()
                result['is_locked'] = True
                result['pos'] = self.locked_pos
        else:
            self._clear_approach_confirmation()

        return result

    def _snap(self, pos):
        """Apply aiming assist at lock time, tolerating a failing provider."""
        if self.snap_provider is None or pos is None:
            return pos
        try:
            snapped = self.snap_provider(pos)
        except Exception:
            return pos
        return snapped if snapped is not None else pos

    def _handle_locking(self, gesture, pos, pinch_info, now):
        """处理锁定状态 - 等待捏合完成"""
        result = {
            'action': 'none',
            'pos': self.locked_pos,
            'state': self.state,
            'is_locked': True
        }

        # 检测到捏合完成
        if gesture in ("pinch", "pinch_hold"):
            self._change_state(ActionState.CLICKING)
            self.pinch_start_time = now
            # 不立即触发点击，等待释放时判断
            result['pos'] = self.locked_pos
            return result

        # 锁定超时：取消锁定
        if now - self.lock_time > self.lock_timeout:
            self._change_state(ActionState.MOVING)
            self.locked_pos = None
            self.lock_anchor = None
            result['is_locked'] = False
            result['pos'] = pos
            if gesture == "point":
                result['action'] = 'move_cursor'
            return result

        # 如果不再靠近且距离较远，取消锁定
        if not pinch_info['is_approaching'] and pinch_info['distance'] > 60:
            self._change_state(ActionState.MOVING)
            self.locked_pos = None
            self.lock_anchor = None
            result['is_locked'] = False
            result['pos'] = pos
            if gesture == "point":
                result['action'] = 'move_cursor'

        return result

    def _handle_clicking(self, gesture, pos, now):
        """处理点击状态"""
        result = {
            'action': 'none',
            'pos': self.locked_pos,
            'state': self.state,
            'is_locked': False
        }

        hold_time = (
            now - self.pinch_start_time
            if self.pinch_start_time is not None
            else 0
        )

        # 计算移动距离：从手部锚点算起，否则吸附产生的位移会被误判成拖动
        anchor = self.lock_anchor if self.lock_anchor is not None else self.locked_pos
        move_distance = 0
        if anchor and pos:
            dx = pos[0] - anchor[0]
            dy = pos[1] - anchor[1]
            move_distance = (dx * dx + dy * dy) ** 0.5

        # 捏合释放：判断动作
        if gesture not in ("pinch", "pinch_hold"):
            self._change_state(ActionState.MOVING)
            # 短按 = 点击
            if hold_time < self.dwell_threshold:
                result['action'] = 'left_click'
                result['pos'] = self.locked_pos
            # 中间时间 = 什么都不做（死区）
            self.locked_pos = None
            self.lock_anchor = None
            self.pinch_start_time = None
            return result

        # 长按 + 有移动：进入拖动模式
        if (
            hold_time + 1e-9 >= self.drag_threshold
            and move_distance >= self.move_threshold
        ):
            self._change_state(ActionState.DRAGGING)
            result['action'] = 'drag_start'
            result['pos'] = self.locked_pos

        return result

    def _handle_dragging(self, gesture, pos, now):
        """处理拖动状态"""
        result = {
            'action': 'drag',
            'pos': pos,
            'state': self.state,
            'is_locked': False
        }

        # 捏合结束
        if gesture not in ("pinch", "pinch_hold"):
            self._change_state(ActionState.MOVING)
            self.locked_pos = None
            self.lock_anchor = None
            self.pinch_start_time = None
            result['action'] = 'drag_end'

        return result

    def _change_state(self, new_state):
        """切换状态"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            if self.on_state_change:
                self.on_state_change(old_state, new_state)

    def _clear_approach_confirmation(self):
        self._approach_start_time = None
        self._approach_pos = None

    def _accept_timestamp(self, timestamp):
        """Accept only finite, strictly increasing control-frame timestamps."""
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            return False
        if not isfinite(timestamp):
            return False
        if self._last_timestamp is not None and timestamp <= self._last_timestamp:
            return False
        self._last_timestamp = timestamp
        return True

    def reset(self, *, clear_timestamp=True):
        """Reset pointer state; retain time ordering after an invalid frame."""
        self.state = ActionState.MOVING
        self.last_pos = None
        self.locked_pos = None
        self.pinch_start_time = None
        self.lock_time = None
        self.last_action_time = 0
        if clear_timestamp:
            self._last_timestamp = None
        self._clear_approach_confirmation()

    # ========== 区域规则系统 ==========

    def set_screen_size(self, width, height):
        """设置屏幕尺寸"""
        self.screen_size = (width, height)

    def add_zone_rule(self, x, y, w, h, allowed_actions):
        """添加区域规则

        Args:
            x, y, w, h: 区域矩形
            allowed_actions: 允许的动作列表 ['click', 'drag', 'scroll']
        """
        self.zone_rules.append({
            'rect': (x, y, w, h),
            'allowed': set(allowed_actions)
        })

    def clear_zone_rules(self):
        """清空区域规则"""
        self.zone_rules = []

    def set_zone_rules(self, rules):
        """Install validated persisted rules without letting malformed config break input safety."""
        self.zone_rules = []
        if not isinstance(rules, list):
            return
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            values = tuple(rule.get(key) for key in ("x", "y", "w", "h"))
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isfinite(value)
                for value in values
            ):
                continue
            x, y, w, h = values
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                continue
            allowed = rule.get("allowed")
            if not isinstance(allowed, list) or not all(
                isinstance(action, str) and action in {"click", "drag"}
                for action in allowed
            ):
                continue
            self.add_zone_rule(x, y, w, h, allowed)

    def _is_action_allowed(self, action, pos):
        """检查动作是否允许"""
        if pos is None:
            return True

        # 动作映射
        action_type = {
            'left_click': 'click',
            'drag_start': 'drag',
            'drag': 'drag',
            'drag_end': 'drag',
        }.get(action, action)

        # 检查区域规则
        x, y = pos
        for rule in self.zone_rules:
            rx, ry, rw, rh = rule['rect']
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return action_type in rule['allowed']

        # 默认允许
        return True

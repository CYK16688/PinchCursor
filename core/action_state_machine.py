"""连续指针动作状态机。

生产路径由 PinchActionEvidence 统一提供动作阶段、目标和物理时间；
候选阶段继续跟手，确认后才锁定回溯目标，短捏合在释放时点击。
未传入联合证据的直接调用保留旧的距离/速度接口，供兼容性回放使用。

状态：
- MOVING: 移动模式，光标跟随手势移动
- LOCKING: 捏合候选；联合证据路径继续移动，旧接口保留预锁定
- CLICKING: 点击模式，执行点击动作
- DRAGGING: 拖动模式，捏合保持后进入
"""

import time
from dataclasses import dataclass
from math import isfinite
from enum import Enum


class ActionState(Enum):
    """动作状态枚举"""
    MOVING = "moving"      # 移动模式
    LOCKING = "locking"    # 锁定中（检测到捏合趋势）
    CLICKING = "clicking"  # 点击中
    DRAGGING = "dragging"  # 拖动中


@dataclass(frozen=True)
class PinchActionEvidence:
    """Admission, hidden target and timing; visible motion stays independent."""

    phase: str
    target_pos: tuple | None = None
    motion_anchor: tuple | None = None
    closed_at: float | None = None
    opened_at: float | None = None
    new_episode: bool = False
    movement_allowed: bool = False


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
        self._pinch_opened_at = None
        self._evidence_phase = "idle"

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
        self._approach_motion_pos = None

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

    def update(self, gesture, pos, pinch_info=None, timestamp=None, motion_pos=None,
               pinch_evidence: PinchActionEvidence | None = None):
        """更新状态机

        Args:
            gesture: 当前手势
            pos: 当前位置 (screen_x, screen_y)
            pinch_info: 捏合信息 {'distance', 'velocity', 'is_approaching'}
            timestamp: Optional monotonic timestamp for deterministic replay.
            motion_pos: Unfrozen hand position used for drag distance and movement.
                ``pos`` may remain locked for click targeting. Omit for legacy callers.
            pinch_evidence: When present, the sole authority for pinch admission.
        """
        now = self._clock() if timestamp is None else timestamp
        result = {
            'action': 'none',
            'pos': pos,
            'state': self.state,
            'is_locked': False
        }

        if not self._accept_timestamp(now):
            result = self._cancel_pointer(pos)
            if pinch_evidence is not None:
                self._evidence_phase = "cancelled"
            return self._finalize(result, now)

        if pinch_evidence is not None:
            result = self._handle_pinch_evidence(
                gesture, pos, pinch_info or {}, now, motion_pos, pinch_evidence,
            )
            return self._finalize(result, now)

        if gesture == "cancel" or (
            gesture == "release"
            and self.state not in {ActionState.CLICKING, ActionState.DRAGGING}
        ):
            return self._finalize(self._cancel_pointer(pos), now)

        if gesture == "release" and pos is None:
            pos = self.last_pos or self.locked_pos
        if pos is None:
            return self._finalize(result, now)
        motion_pos = pos if motion_pos is None else motion_pos
        if not self._valid_pos(pos) or not self._valid_pos(motion_pos):
            return self._finalize(self._cancel_pointer(pos), now)

        if pinch_info is None:
            pinch_info = {'distance': 999, 'velocity': 0, 'is_approaching': False}

        if self.state in {ActionState.CLICKING, ActionState.DRAGGING}:
            if pinch_info.get('is_pinching') is False and self._pinch_opened_at is None:
                self._pinch_opened_at = now
            elif pinch_info.get('is_pinching') is True:
                self._pinch_opened_at = None

        # 状态机处理
        if self.state == ActionState.MOVING:
            result = self._handle_moving(gesture, pos, pinch_info, now, motion_pos)
        elif self.state == ActionState.LOCKING:
            result = self._handle_locking(gesture, pos, pinch_info, now)
        elif self.state == ActionState.CLICKING:
            result = self._handle_clicking(gesture, motion_pos, now, pinch_info)
        elif self.state == ActionState.DRAGGING:
            result = self._handle_dragging(gesture, motion_pos, now, pinch_info)

        return self._finalize(result, now)

    def _finalize(self, result, now):
        """All admission paths share action filtering and pointer bookkeeping."""
        if not self._valid_pos(result['pos']):
            result['pos'] = self.last_pos if self._valid_pos(self.last_pos) else None
            if result['action'] != 'drag_end':
                result['action'] = 'none'
        if result['action'] not in ('none', 'move_cursor', 'drag_end'):
            if not self._is_action_allowed(result['action'], result['pos']):
                if result['action'] == 'drag_start':
                    # A denied down never establishes a drag lifecycle.
                    self._change_state(ActionState.CLICKING)
                result['action'] = 'none'
                result['pos'] = self.last_pos or result['pos']
            else:
                self.last_action_time = now

        self.last_pos = result['pos']
        result['state'] = self.state
        return result

    @staticmethod
    def _valid_pos(pos):
        return (
            isinstance(pos, (tuple, list)) and len(pos) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                    and isfinite(value) for value in pos)
        )

    def _cancel_pointer(self, pos=None):
        was_dragging = self.state is ActionState.DRAGGING
        safe_pos = next((value for value in (self.last_pos, self.locked_pos, pos)
                         if self._valid_pos(value)), None)
        self.reset(clear_timestamp=False)
        return {'action': 'drag_end' if was_dragging else 'none', 'pos': safe_pos,
                'state': self.state, 'is_locked': False}

    def _valid_evidence(self, evidence, now):
        if not isinstance(evidence, PinchActionEvidence):
            return False
        if not isinstance(evidence.new_episode, bool) or not isinstance(evidence.movement_allowed, bool):
            return False
        if not isinstance(evidence.phase, str) or evidence.phase not in {
            'idle', 'candidate', 'confirmed', 'released', 'cancelled',
        }:
            return False
        for value in (evidence.target_pos, evidence.motion_anchor):
            if value is not None and not self._valid_pos(value):
                return False
        for value in (evidence.closed_at, evidence.opened_at):
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not isfinite(value) or value > now
            ):
                return False
        if (evidence.closed_at is not None and evidence.opened_at is not None
                and evidence.opened_at < evidence.closed_at):
            return False
        if evidence.phase in {'candidate', 'confirmed'} and evidence.target_pos is None:
            return False
        if evidence.phase == 'confirmed' and (
            evidence.closed_at is None or evidence.motion_anchor is None
        ):
            return False
        if evidence.phase == 'released' and self.pinch_start_time is not None:
            if evidence.opened_at is None or evidence.opened_at < self.pinch_start_time:
                return False
        if self._evidence_phase == 'confirmed' and evidence.phase in {'confirmed', 'released'}:
            if evidence.closed_at is not None and evidence.closed_at != self.pinch_start_time:
                return False
        return True

    def _handle_pinch_evidence(self, gesture, pos, pinch_info, now, motion_pos, evidence):
        """Keep admission independent of stabilized labels and raw approach gates."""
        if not self._valid_evidence(evidence, now):
            result = self._cancel_pointer(pos)
            self._evidence_phase = 'cancelled'
            return result
        phase = evidence.phase
        if phase in {'idle', 'cancelled'} or gesture == 'cancel':
            result = self._cancel_pointer(pos)
            self._evidence_phase = 'cancelled' if gesture == 'cancel' else phase
            if (phase == 'idle' and gesture == 'point' and result['action'] != 'drag_end'
                    and self._valid_pos(pos)):
                result.update(action='move_cursor', pos=pos)
            elif (phase == 'cancelled' and evidence.movement_allowed and gesture != 'cancel'
                    and result['action'] != 'drag_end' and self._valid_pos(pos)):
                # Movement does not rearm a click or clear the cancellation latch.
                result.update(action='move_cursor', pos=pos)
            return result

        # Qualified release can coincide with the last open frame at low FPS.
        # Only an explicitly new candidate may bridge that missing idle frame.
        if (self._evidence_phase == 'released' and phase == 'candidate'
                and evidence.new_episode):
            self._evidence_phase = 'idle'

        # A late confirmation cannot resurrect a terminal episode. Cancellation
        # always requires an observed idle frame before admission resumes.
        if self._evidence_phase in {'released', 'cancelled'}:
            return {'action': 'none', 'pos': self.last_pos or pos,
                    'state': self.state, 'is_locked': False}

        if phase == 'released':
            if self._evidence_phase == 'confirmed' and self.state is ActionState.CLICKING:
                self._pinch_opened_at = evidence.opened_at
                result = self._handle_clicking('release', self.lock_anchor, now, pinch_info)
            else:
                result = self._cancel_pointer(pos)
            self._evidence_phase = 'released'
            return result

        motion_pos = pos if motion_pos is None else motion_pos
        if not self._valid_pos(pos) or not self._valid_pos(motion_pos):
            result = self._cancel_pointer(pos)
            self._evidence_phase = 'cancelled'
            return result

        if phase == 'candidate':
            if self._evidence_phase == 'confirmed':
                result = self._cancel_pointer(pos)
                self._evidence_phase = 'cancelled'
                return result
            if self._evidence_phase != 'candidate':
                result = self._cancel_pointer(pos)
                self._change_state(ActionState.LOCKING)
                self.lock_time = now
                self._evidence_phase = 'candidate'
                # Release an orphaned native drag before resuming movement.
                if result['action'] == 'drag_end':
                    return result
            return {'action': 'move_cursor', 'pos': pos,
                    'state': self.state, 'is_locked': False}

        if self._evidence_phase != 'confirmed':
            if self.state is ActionState.DRAGGING:
                result = self._cancel_pointer(pos)
                self._evidence_phase = 'cancelled'
                return result
            self._clear_approach_confirmation()
            self.locked_pos = self._snap(evidence.target_pos)
            self.lock_anchor = evidence.motion_anchor
            self.pinch_start_time = evidence.closed_at
            self._pinch_opened_at = evidence.opened_at
            self._change_state(ActionState.CLICKING)
            self._evidence_phase = 'confirmed'
            return {'action': 'move_cursor', 'pos': self.locked_pos,
                    'state': self.state, 'is_locked': True}

        if evidence.opened_at is not None:
            self._pinch_opened_at = evidence.opened_at
        elif pinch_info.get('is_pinching') is False and self._pinch_opened_at is None:
            self._pinch_opened_at = now
        elif pinch_info.get('is_pinching') is True:
            self._pinch_opened_at = None
        if self.state is ActionState.DRAGGING:
            return self._handle_dragging('pinch_hold', motion_pos, now, pinch_info)
        return self._handle_clicking('pinch_hold', motion_pos, now, pinch_info)

    def _handle_moving(self, gesture, pos, pinch_info, now, motion_pos):
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
        if gesture in ("pinch", "pinch_hold") and pinch_info.get('is_pinching') is not False:
            self._change_state(ActionState.CLICKING)
            self.locked_pos = self._snap(pos)
            self.lock_anchor = motion_pos
            self.pinch_start_time = now
            self._pinch_opened_at = None
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
                self._approach_motion_pos = motion_pos
            elif now - self._approach_start_time >= self.lock_confirmation_time:
                self._change_state(ActionState.LOCKING)
                self.locked_pos = self._snap(self._approach_pos)
                self.lock_anchor = self._approach_motion_pos
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
        return snapped if self._valid_pos(snapped) else pos

    def _handle_locking(self, gesture, pos, pinch_info, now):
        """处理锁定状态 - 等待捏合完成"""
        result = {
            'action': 'none',
            'pos': self.locked_pos,
            'state': self.state,
            'is_locked': True
        }

        # 检测到捏合完成
        if gesture in ("pinch", "pinch_hold") and pinch_info.get('is_pinching') is not False:
            self._change_state(ActionState.CLICKING)
            self.pinch_start_time = now
            self._pinch_opened_at = None
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

    def _handle_clicking(self, gesture, pos, now, pinch_info):
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
            # Confirmation may arrive a few frames after the fingers opened.
            # That safety delay must not turn a short click into a long hold.
            if self._pinch_opened_at is not None and self.pinch_start_time is not None:
                hold_time = self._pinch_opened_at - self.pinch_start_time
            # 短按 = 点击
            if gesture in ("point", "release") and hold_time < self.dwell_threshold:
                result['action'] = 'left_click'
                result['pos'] = self.locked_pos
            # 中间时间 = 什么都不做（死区）
            self.locked_pos = None
            self.lock_anchor = None
            self.pinch_start_time = None
            self._pinch_opened_at = None
            return result

        # 长按 + 有移动：进入拖动模式
        if (
            hold_time + 1e-9 >= self.drag_threshold
            and move_distance >= self.move_threshold
            # Raw opening precedes the stabilized label. Its unfrozen position
            # must not turn a release-frame jump into a new native mouse-down.
            and pinch_info.get('is_pinching') is not False
        ):
            self._change_state(ActionState.DRAGGING)
            result['action'] = 'drag_start'
            result['pos'] = self.locked_pos

        return result

    def _handle_dragging(self, gesture, pos, now, pinch_info):
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
            self._pinch_opened_at = None
            result['action'] = 'drag_end'
            result['pos'] = self.last_pos or pos
        elif pinch_info.get('is_pinching') is False:
            # Await the arbiter's confirmed release without moving the object
            # with the opening fingers or interpreting one noisy frame as up.
            result['action'] = 'none'
            result['pos'] = self.last_pos or pos

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
        self._approach_motion_pos = None

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
        self.lock_anchor = None
        self.pinch_start_time = None
        self._pinch_opened_at = None
        self.lock_time = None
        self._evidence_phase = 'idle'
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
            # The origin may be negative: a display placed left of or above the
            # main one has negative coordinates in the global screen space, and
            # rejecting those rules silently dropped every zone on a second
            # display. Only a non-positive size is meaningless.
            if w <= 0 or h <= 0:
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

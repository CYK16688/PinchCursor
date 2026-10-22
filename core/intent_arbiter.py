"""Central ownership rules for pointer control and optional gesture shortcuts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.action_state_machine import ActionState


CORE_POINTER_GESTURES = frozenset({"point", "pinch", "pinch_hold"})


class IntentOwner(StrEnum):
    NEUTRAL = "neutral"
    POINTER = "pointer"
    DYNAMIC = "dynamic"
    WAIT_NEUTRAL = "wait_neutral"


@dataclass(frozen=True)
class IntentDecision:
    """Which input lane owns the current hand-motion evidence."""

    owner: IntentOwner
    # Gesture that may enter the deterministic pointer state machine. It is
    # distinct from the raw classifier label so a transient shortcut pose cannot
    # release an active click or drag.
    effective_pointer_gesture: str | None
    allow_pointer: bool
    allow_combo: bool
    allow_dynamic: bool


class IntentArbiter:
    """Gate shortcut lanes while the pointer lifecycle owns the hand motion.

    ``ActionStateMachine`` remains the sole owner of pointer move/click/drag
    transitions. This gate does not classify another pinch; it only preserves
    the last trusted core gesture through transient non-core labels and requires
    stable neutral frames before optional shortcut lanes can rearm.
    """

    def __init__(self, *, neutral_rearm_frames: int = 3):
        if not isinstance(neutral_rearm_frames, int) or isinstance(neutral_rearm_frames, bool):
            raise ValueError("neutral_rearm_frames must be a positive integer")
        if neutral_rearm_frames < 1:
            raise ValueError("neutral_rearm_frames must be a positive integer")
        self.neutral_rearm_frames = neutral_rearm_frames
        self._pointer_claimed = False
        self._wait_neutral = False
        self._neutral_frames = 0
        self._last_pointer_gesture: str | None = None

    def update(self, *, gesture, pinch_info, pointer_state, hand_present: bool, now: float) -> IntentDecision:
        """Return allowed input lanes for one timestamped hand observation."""
        del now  # Kept for a uniform, replay-friendly frame API.
        if not hand_present:
            self.reset()
            return self._decision(IntentOwner.NEUTRAL, None, False, False, False)

        state = self._coerce_pointer_state(pointer_state)
        is_core = gesture in CORE_POINTER_GESTURES
        # Once a click or drag is underway, non-core labels are transition
        # noise. A stable run of tracked ``none`` frames is the only fallback
        # release signal; an explicit point release still reaches the pointer
        # state machine immediately.
        held_pointer = state in {ActionState.CLICKING, ActionState.DRAGGING}
        if held_pointer and not is_core:
            if gesture == "none":
                self._neutral_frames += 1
                if self._neutral_frames >= self.neutral_rearm_frames:
                    self._pointer_claimed = True
                    self._wait_neutral = False
                    self._neutral_frames = 0
                    return self._decision(IntentOwner.POINTER, "none", True, False, False)
            else:
                self._neutral_frames = 0
            self._pointer_claimed = True
            return self._decision(
                IntentOwner.POINTER,
                self._last_pointer_gesture or "pinch",
                True,
                False,
                False,
            )

        pointer_evidence = is_core or self._is_approaching(pinch_info) or state is ActionState.LOCKING
        if pointer_evidence:
            self._pointer_claimed = True
            self._wait_neutral = False
            self._neutral_frames = 0
            if is_core:
                self._last_pointer_gesture = gesture
            effective = self._last_pointer_gesture or ("point" if self._is_approaching(pinch_info) else None)
            return self._decision(IntentOwner.POINTER, effective, effective is not None, False, False)

        if self._pointer_claimed or self._wait_neutral:
            if gesture == "none" and state is ActionState.MOVING:
                self._neutral_frames += 1
                if self._neutral_frames >= self.neutral_rearm_frames:
                    was_pointer = self._pointer_claimed
                    self._pointer_claimed = False
                    self._wait_neutral = False
                    self._neutral_frames = 0
                    self._last_pointer_gesture = None
                    return self._decision(
                        IntentOwner.NEUTRAL,
                        "none" if was_pointer else None,
                        was_pointer,
                        not was_pointer,
                        not was_pointer,
                    )
            else:
                self._neutral_frames = 0
            owner = IntentOwner.WAIT_NEUTRAL if self._wait_neutral else IntentOwner.POINTER
            return self._decision(owner, self._last_pointer_gesture, self._last_pointer_gesture is not None, False, False)

        return self._decision(IntentOwner.NEUTRAL, None, False, True, True)

    def mark_shortcut_committed(self) -> None:
        """Require a neutral rearm after any one-shot shortcut dispatch."""
        self._pointer_claimed = False
        self._wait_neutral = True
        self._neutral_frames = 0
        self._last_pointer_gesture = None

    def mark_composite_committed(self) -> None:
        """Backward-compatible semantic name for a combo or DTW shortcut commit."""
        self.mark_shortcut_committed()

    def reset(self) -> None:
        self._pointer_claimed = False
        self._wait_neutral = False
        self._neutral_frames = 0
        self._last_pointer_gesture = None

    @staticmethod
    def _decision(owner, effective_pointer_gesture, allow_pointer, allow_combo, allow_dynamic):
        return IntentDecision(
            owner=owner,
            effective_pointer_gesture=effective_pointer_gesture,
            allow_pointer=allow_pointer,
            allow_combo=allow_combo,
            allow_dynamic=allow_dynamic,
        )

    @staticmethod
    def _coerce_pointer_state(value):
        try:
            return ActionState(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_approaching(pinch_info) -> bool:
        return isinstance(pinch_info, dict) and pinch_info.get("is_approaching") is True

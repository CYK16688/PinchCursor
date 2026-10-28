"""Truthful, GUI-independent presentation of the current control transaction."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Iterable

from core.action_state_machine import ActionState
from core.control_session import SessionState
from gui.hud_state import HudState

if TYPE_CHECKING:
    from core.control_engine import ControlSnapshot, DispatchOutcome


@dataclass(frozen=True)
class InteractionFeedback:
    """Translation keys and semantic styling, with no native or Qt behavior.

    ``stage`` selects aim (0), pinch (1), or release (2). It is a discrete
    instruction step, never a confidence or elapsed-time percentage.
    """

    title_key: str
    hint_key: str
    semantic_state: str
    stage: int | None
    hud_state: HudState


def _feedback(title, hint, semantic, stage=None, hud=HudState.HIDDEN):
    return InteractionFeedback(
        f"interaction.{title}", f"interaction.{hint}", semantic, stage, hud,
    )


_TRACKING_ERRORS = frozenset({
    "invalid_frame_time", "invalid_observation", "frame_geometry_changed",
    "stale_frame",
})
_POLICY_FAILURES = frozenset({
    "gesture_blocked", "action_blocked", "context_target_unavailable",
    "context_target_changed", "session_stopped",
})
_CLICK_ACTIONS = frozenset({"left_click", "right_click", "double_click"})


def interaction_feedback_model(
    snapshot: ControlSnapshot | None,
    *,
    is_running: bool,
    session_state: SessionState | None = None,
    ready: bool = True,
    outcomes: Iterable[DispatchOutcome] | None = None,
) -> InteractionFeedback:
    """Describe actual evidence and dispatch results without predicting actions.

    A stopped or inactive session overrides a retained gesture snapshot.
    ``outcomes`` can carry the runtime's coalesced dispatch results, which may
    include an action from a frame older than its latest displayed snapshot.
    Pinch release alone is never evidence that a click was executed.
    """
    if not is_running:
        if not ready:
            return _feedback("blocked", "permissions", "waiting")
        return _feedback("paused", "start", "idle")

    if snapshot is not None and snapshot.error:
        hint = "recover_tracking" if snapshot.error in _TRACKING_ERRORS else "retry"
        return _feedback("error", hint, "danger", hud=HudState.ERROR)

    dispatches = tuple(outcomes if outcomes is not None else
                       snapshot.outcomes if snapshot is not None else ())
    # A failed release must remain visible even if the session has just exited.
    # A no-op is a normal transaction outcome, not an input failure.
    failures = tuple(outcome for outcome in dispatches
                     if outcome.result is not None
                     and not outcome.result.executed
                     and outcome.request.action != "none"
                     and outcome.result.error_code != "no_action")
    if failures:
        codes = {outcome.result.error_code for outcome in failures}
        if codes & _TRACKING_ERRORS:
            return _feedback("error", "recover_tracking", "danger", hud=HudState.ERROR)
        if codes <= _POLICY_FAILURES:
            return _feedback("not_executed", "retry", "warning", hud=HudState.ERROR)
        return _feedback("not_executed", "retry", "danger", hud=HudState.ERROR)

    state = session_state if session_state is not None else (
        snapshot.session_state if snapshot is not None else SessionState.INACTIVE
    )
    if state not in {SessionState.ARMED, SessionState.POINTER}:
        return _feedback("inactive", "activate", "waiting")
    if snapshot is None or not snapshot.hand_present:
        return _feedback("hand_lost", "show_hand", "waiting")

    # The FSM owns a live drag even while the physical observer still reports
    # confirmed pinch. Do not offer a release-to-click instruction during drag.
    if snapshot.pointer_state is ActionState.DRAGGING:
        return _feedback("dragging", "release_to_drop", "active", 2, HudState.DRAGGING)

    clicks = tuple(outcome for outcome in dispatches
                   if outcome.result is not None and outcome.result.executed
                   and outcome.request.action in _CLICK_ACTIONS)
    if clicks:
        hud = (HudState.SECONDARY_CLICK if clicks[-1].request.action == "right_click"
               else HudState.CLICKED)
        return _feedback("clicked", "aim_again", "success", 2, hud)

    if snapshot.pinch_phase == "cancelled":
        return _feedback("cancelled", "reopen", "warning")
    if snapshot.pinch_phase == "candidate":
        return _feedback("candidate", "pinch_to_confirm", "armed", 1, HudState.POINTER)
    if snapshot.pinch_phase == "confirmed":
        return _feedback("confirmed", "release_or_drag", "armed", 2, HudState.LOCKING)
    if snapshot.pinch_phase == "released":
        return _feedback("released", "aim_again", "active", 2, HudState.POINTER)
    return _feedback("aiming", "aim", "active", 0, HudState.POINTER)


class InteractionFeedbackPresenter:
    """Keep brief outcomes readable without obscuring the next instruction.

    Timing belongs to presentation only. Callers supply monotonic ``now``;
    snapshots and native actions are never retained or modified here. An
    identical event repeated on adjacent updates is the same presentation,
    so repainting a snapshot cannot extend its lifetime indefinitely.
    """

    HOLD_SECONDS = {"interaction.clicked": 0.7, "interaction.not_executed": 1.5}
    _RESUMABLE = frozenset({"interaction.aiming", "interaction.released"})

    def __init__(self):
        self._held: InteractionFeedback | None = None
        self._until = 0.0
        self._last_input: InteractionFeedback | None = None
        self._last_now: float | None = None
        self._baseline = _feedback("aiming", "aim", "active", 0, HudState.POINTER)

    def update(self, feedback: InteractionFeedback, *, now: float) -> InteractionFeedback:
        if not isfinite(now) or (self._last_now is not None and now < self._last_now):
            # A discontinuous presentation clock cannot justify retaining an
            # older action. The current evidence remains available verbatim.
            self._held = None
            self._last_input = None
            self._last_now = None
            return feedback

        duration = self.HOLD_SECONDS.get(feedback.title_key)
        if duration is not None:
            if feedback != self._last_input:
                self._held = feedback
                self._until = now + duration
        elif feedback.title_key in self._RESUMABLE:
            self._baseline = feedback
        else:
            # New gesture work, hand loss, session changes and tracking errors
            # all outrank a previous action's read time, including cancellation.
            self._held = None

        self._last_input = feedback
        self._last_now = now
        if self._held is not None and now < self._until:
            return self._held
        self._held = None
        return self._baseline if duration is not None else feedback

"""Safe contextual intent resolution for gesture control targets."""

from __future__ import annotations

from dataclasses import dataclass

from platform_services.contracts import UIContext


@dataclass(frozen=True)
class ContextualIntent:
    """A proposed action; confirmation remains in the deterministic core lane."""

    action: str
    label: str = ""
    requires_confirmation: bool = False
    confirmation_gesture: str = ""


class ContextualIntentController:
    """Requires a stable target dwell before accepting a contextual command."""

    def __init__(self, dwell_seconds=0.3):
        self.dwell_seconds = max(0.0, float(dwell_seconds))
        self._target_key = None
        self._target = None
        self._point_started_at = None
        self._candidate = None

    def reset(self):
        self._target_key = None
        self._target = None
        self._point_started_at = None
        self._candidate = None

    def observe(self, context: UIContext, *, gesture: str, now: float):
        # Contextual actions are optional. Any uncertain identity cancels the
        # candidate rather than carrying it across a same-role target switch.
        if not context.target_id:
            self.reset()
            return None
        key = (context.category, context.native_role, context.source, context.target_id)
        if gesture == "point":
            if context.category != "scrollable":
                self.reset()
                return None
            if key != self._target_key:
                self._target_key = key
                self._target = context
                self._point_started_at = now
                self._candidate = None
                return None
            if self._point_started_at is None or now - self._point_started_at < self.dwell_seconds:
                return None
            self._candidate = self._candidate_for(context)
            return self._candidate

        if key != self._target_key or self._candidate is None:
            self.reset()
            return None
        if self._candidate.confirmation_gesture == "pinch" and gesture == "pinch":
            return self._confirm(resolve_contextual_intent(
                context, gesture="pinch", fallback_action="none"
            ))
        if self._candidate.confirmation_gesture == "thumb_direction" and gesture in {"thumb_up", "thumb_down"}:
            return self._confirm(resolve_contextual_intent(
                context, gesture=gesture, fallback_action="none"
            ))
        return None

    def _candidate_for(self, context: UIContext):
        # Without a stable, non-content target fingerprint, a later frame could
        # belong to a different same-role control. Preserve ordinary bindings.
        if not context.target_id:
            return None
        if context.category == "scrollable":
            return ContextualIntent(
                action="none",
                label="Scroll: thumb up or down",
                requires_confirmation=True,
                confirmation_gesture="thumb_direction",
            )
        intent = resolve_contextual_intent(context, gesture="point", fallback_action="none")
        return intent if intent.action != "none" else None

    def _confirm(self, intent: ContextualIntent):
        self.reset()
        if intent.action == "none":
            return None
        return ContextualIntent(action=intent.action, label=intent.label)


def resolve_contextual_intent(
    context: UIContext,
    *,
    gesture: str,
    fallback_action: str,
) -> ContextualIntent:
    """Resolve only optional semantic actions against a verified target.

    Core pointer move/click/drag lifecycle is never represented in this lane.
    ``fallback_action`` is retained for source compatibility but intentionally
    cannot turn missing or untrusted AX context into an executable proposal.
    """
    if not context.target_id:
        return ContextualIntent(action="none")
    if context.category == "scrollable" and gesture == "thumb_up":
        return ContextualIntent(action="scroll_up", label="Scroll up")
    if context.category == "scrollable" and gesture == "thumb_down":
        return ContextualIntent(action="scroll_down", label="Scroll down")
    return ContextualIntent(action="none")

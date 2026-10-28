"""Safe contextual intent resolution for gesture control targets.

Two kinds of contextual action live here, and they need different lifecycles:

* **One-shot** (a pinch confirming a contextual click) — resolved once, then the
  controller clears so the same gesture cannot fire twice.
* **Continuous** (thumbing up/down inside a scrollable region) — has to repeat
  while the gesture is held. Scrolling is the most frequent desktop action, and
  the previous implementation resolved one notch and then cleared its state, so
  the user had to re-aim at the scroll area and wait out the dwell again for
  every single notch. Browsing a page that way is not usable.

The safety property is preserved for both: a contextual action still requires a
verified target identity, and the dwell still has to elapse before the lane arms.
"""

from __future__ import annotations

from dataclasses import dataclass

from platform_services.contracts import UIContext


# Notches per second when a thumb gesture is held: one every 120 ms is about
# what a trackpad's momentum-less scroll feels like, and slow enough that the
# user can stop on a line.
DEFAULT_SCROLL_REPEAT_SECONDS = 0.12


@dataclass(frozen=True)
class ContextualIntent:
    """A proposed action; confirmation remains in the deterministic core lane."""

    action: str
    label: str = ""
    requires_confirmation: bool = False
    confirmation_gesture: str = ""


class ContextualIntentController:
    """Requires a stable target dwell before accepting a contextual command."""

    def __init__(self, dwell_seconds=0.3, scroll_repeat_seconds=DEFAULT_SCROLL_REPEAT_SECONDS):
        self.dwell_seconds = max(0.0, float(dwell_seconds))
        # 0 would emit a notch per frame and flood the event tap.
        self.scroll_repeat_seconds = max(0.02, float(scroll_repeat_seconds))
        self._target_key = None
        self._target = None
        self._point_started_at = None
        self._candidate = None
        self._last_scroll_at = None

    def reset(self):
        self._target_key = None
        self._target = None
        self._point_started_at = None
        self._candidate = None
        self._last_scroll_at = None

    def observe(self, context: UIContext, *, gesture: str, now: float):
        # Contextual actions are optional. Any uncertain identity cancels the
        # candidate rather than carrying it across a same-role target switch.
        if not context.target_id:
            self.reset()
            return None

        key = (context.category, context.native_role, context.source, context.target_id)
        if key != self._target_key:
            # A different target is a fresh decision: drop everything and start
            # its dwell from zero, so a gesture aimed at the previous target
            # cannot confirm against this one.
            self.reset()
            self._target_key = key
            self._target = context
            self._point_started_at = now
            return None

        if gesture == "point":
            if context.category != "scrollable":
                self.reset()
                return None
            if self._point_started_at is None or now - self._point_started_at < self.dwell_seconds:
                return None
            self._candidate = self._candidate_for(context)
            return self._candidate

        if gesture in {"thumb_up", "thumb_down"}:
            return self._observe_scroll(context, gesture=gesture, now=now)

        if gesture == "pinch":
            return self._observe_confirm(context, gesture="pinch")

        return None

    def _observe_scroll(self, context: UIContext, *, gesture: str, now: float):
        """Repeat a scroll notch while the thumb gesture is held.

        The dwell is deliberately *not* re-armed here: the target is still the
        one the user already settled on, and re-waiting 300 ms between notches is
        what made this unusable. Only the repeat interval throttles it.
        """
        if context.category != "scrollable":
            return None
        if self._candidate is None or self._candidate.confirmation_gesture != "thumb_direction":
            return None
        if self._last_scroll_at is not None and now - self._last_scroll_at < self.scroll_repeat_seconds:
            return None
        intent = resolve_contextual_intent(context, gesture=gesture, fallback_action="none")
        if intent.action == "none":
            return None
        self._last_scroll_at = now
        return intent

    def _observe_confirm(self, context: UIContext, *, gesture: str):
        if self._candidate is None or self._candidate.confirmation_gesture != "pinch":
            return None
        intent = resolve_contextual_intent(context, gesture=gesture, fallback_action="none")
        # A confirmation is one-shot: consuming it clears the armed state so the
        # same pinch cannot fire a second time on the next frame.
        self.reset()
        return intent if intent.action != "none" else None

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

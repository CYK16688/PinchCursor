"""Holding a thumb gesture must keep scrolling.

The controller used to resolve one notch and then clear its state, so scrolling
a page meant re-aiming at the scroll area and waiting out the 300 ms dwell again
for every single notch. Scrolling is the most frequent desktop interaction, which
made that the single biggest reason the app could not replace a mouse.
"""

import pytest

from core.contextual_intent import ContextualIntentController
from platform_services.contracts import UIContext

FRAME = 1 / 30


def _scroll_area(target_id="tab-1"):
    return UIContext(
        category="scrollable",
        target_id=target_id,
        native_role="AXScrollArea",
        source="ax",
    )


def _armed(controller, context, start=0.0):
    """Point at the target until the dwell has elapsed."""
    controller.observe(context, gesture="point", now=start)
    return controller.observe(context, gesture="point", now=start + 0.31)


def test_holding_a_thumb_scrolls_repeatedly():
    controller = ContextualIntentController(dwell_seconds=0.3)
    context = _scroll_area()
    assert _armed(controller, context).requires_confirmation is True

    actions = []
    now = 0.40
    for _ in range(30):
        intent = controller.observe(context, gesture="thumb_up", now=now)
        if intent is not None:
            actions.append(intent.action)
        now += FRAME

    assert len(actions) > 3, "one notch per dwell is what made scrolling unusable"
    assert set(actions) == {"scroll_up"}


def test_the_repeat_rate_is_throttled():
    """Every frame would flood the event tap: 30 notches a second is unusable."""
    controller = ContextualIntentController(dwell_seconds=0.3, scroll_repeat_seconds=0.12)
    context = _scroll_area()
    _armed(controller, context)

    count = 0
    now = 0.40
    for _ in range(30):  # one second
        if controller.observe(context, gesture="thumb_up", now=now) is not None:
            count += 1
        now += FRAME

    assert 5 <= count <= 12


def test_scrolling_stops_when_the_thumb_is_lowered():
    controller = ContextualIntentController(dwell_seconds=0.3)
    context = _scroll_area()
    _armed(controller, context)

    assert controller.observe(context, gesture="thumb_up", now=0.40) is not None
    # Lowering the thumb produces no scroll intent.
    assert controller.observe(context, gesture="point", now=0.50).requires_confirmation is True
    # And the user can scroll again immediately, without waiting out a dwell:
    # the target never changed.
    assert controller.observe(context, gesture="thumb_up", now=0.60) is not None


def test_a_different_scroll_target_needs_its_own_dwell():
    controller = ContextualIntentController(dwell_seconds=0.3)
    first = _scroll_area("tab-1")
    second = _scroll_area("tab-2")
    _armed(controller, first)

    assert controller.observe(second, gesture="point", now=0.40) is None
    # Thumbing at a target that has not armed yet must do nothing.
    assert controller.observe(second, gesture="thumb_up", now=0.45) is None

    _armed(controller, second, start=0.50)
    assert controller.observe(second, gesture="thumb_up", now=0.90) is not None


def test_a_non_scrollable_target_never_scrolls():
    controller = ContextualIntentController(dwell_seconds=0.3)
    button = UIContext(
        category="generic", target_id="btn-1", native_role="AXButton", source="ax"
    )
    controller.observe(button, gesture="point", now=0.0)
    controller.observe(button, gesture="point", now=0.40)

    assert controller.observe(button, gesture="thumb_up", now=0.50) is None
    assert controller.observe(button, gesture="thumb_down", now=0.60) is None


def test_losing_the_target_stops_scrolling():
    controller = ContextualIntentController(dwell_seconds=0.3)
    context = _scroll_area()
    _armed(controller, context)
    assert controller.observe(context, gesture="thumb_up", now=0.40) is not None

    empty = UIContext(category="scrollable", target_id="", native_role="", source="ax")
    assert controller.observe(empty, gesture="thumb_up", now=0.50) is None
    # After losing the target the dwell has to run again.
    assert controller.observe(context, gesture="thumb_up", now=0.60) is None


def test_a_pinch_confirmation_is_still_one_shot():
    """Making scroll repeat must not make a contextual click repeat."""
    controller = ContextualIntentController(dwell_seconds=0.3)
    context = _scroll_area()
    _armed(controller, context)

    # A scroll area's candidate confirms with a thumb, not a pinch, so a pinch
    # must not fire anything at all.
    assert controller.observe(context, gesture="pinch", now=0.40) is None
    assert controller.observe(context, gesture="pinch", now=0.45) is None


def test_a_zero_repeat_interval_is_clamped():
    """A caller passing 0 must not produce a notch per frame."""
    controller = ContextualIntentController(dwell_seconds=0.3, scroll_repeat_seconds=0)
    assert controller.scroll_repeat_seconds >= 0.02

from core.contextual_intent import ContextualIntentController
from platform_services.contracts import UIContext


def test_clickable_target_never_arms_a_contextual_candidate_for_core_click():
    controller = ContextualIntentController(dwell_seconds=0.3)
    target = UIContext(category="clickable", native_role="AXButton", source="test", target_id="button")

    assert controller.observe(target, gesture="point", now=1.0) is None
    assert controller.observe(target, gesture="point", now=1.30) is None
    assert controller.observe(target, gesture="pinch", now=1.31) is None


def test_contextual_candidate_does_not_survive_a_target_change():
    controller = ContextualIntentController(dwell_seconds=0.3)
    button = UIContext(category="clickable", native_role="AXButton", source="test", target_id="button")
    text = UIContext(category="text_input", native_role="AXTextField", source="test", target_id="text")

    controller.observe(button, gesture="point", now=1.0)
    controller.observe(button, gesture="point", now=1.3)

    assert controller.observe(text, gesture="pinch", now=1.31) is None


def test_same_role_target_change_invalidates_an_armed_scroll_candidate():
    controller = ContextualIntentController(dwell_seconds=0.3)
    first_target = UIContext(
        category="scrollable",
        native_role="AXWebArea",
        source="accessibility",
        target_id="scroll-a",
    )
    second_target = UIContext(
        category="scrollable",
        native_role="AXWebArea",
        source="accessibility",
        target_id="scroll-b",
    )

    controller.observe(first_target, gesture="point", now=1.0)
    assert controller.observe(first_target, gesture="point", now=1.3) is not None

    assert controller.observe(second_target, gesture="thumb_down", now=1.31) is None


def test_context_without_a_stable_target_identity_never_arms_a_candidate():
    controller = ContextualIntentController(dwell_seconds=0.3)
    target = UIContext(category="clickable", native_role="AXButton", source="accessibility")

    controller.observe(target, gesture="point", now=1.0)

    assert controller.observe(target, gesture="point", now=1.3) is None


def test_ambiguous_target_identity_cancels_an_armed_scroll_candidate():
    controller = ContextualIntentController(dwell_seconds=0.3)
    initially_verified = UIContext(
        category="scrollable",
        native_role="AXWebArea",
        source="accessibility",
        target_id="previously-verified-scroll-area",
    )
    ambiguous_same_role_target = UIContext(
        category="scrollable",
        native_role="AXWebArea",
        source="accessibility",
        target_id="",
    )

    controller.observe(initially_verified, gesture="point", now=1.0)
    assert controller.observe(initially_verified, gesture="point", now=1.3) is not None

    assert controller.observe(ambiguous_same_role_target, gesture="thumb_down", now=1.31) is None
    assert controller.observe(initially_verified, gesture="thumb_down", now=1.32) is None


def test_scroll_target_requires_point_dwell_before_thumb_confirmation():
    controller = ContextualIntentController(dwell_seconds=0.3)
    target = UIContext(category="scrollable", native_role="AXWebArea", source="test", target_id="web-area")

    controller.observe(target, gesture="point", now=1.0)
    candidate = controller.observe(target, gesture="point", now=1.3)
    assert candidate is not None
    assert candidate.label == "Scroll: thumb up or down"

    confirmed = controller.observe(target, gesture="thumb_down", now=1.31)
    assert confirmed is not None
    assert confirmed.action == "scroll_down"

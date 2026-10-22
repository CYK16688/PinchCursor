from core.contextual_intent import resolve_contextual_intent
from platform_services.contracts import UIContext


def test_contextual_lane_never_proposes_core_pointer_actions_for_clickable_targets():
    intent = resolve_contextual_intent(
        UIContext(category="clickable", native_role="AXButton", source="test"),
        gesture="point",
        fallback_action="move_cursor",
    )

    assert intent.action == "none"
    assert intent.label == ""
    assert intent.requires_confirmation is False


def test_contextual_lane_never_proposes_core_pointer_actions_for_text_input():
    intent = resolve_contextual_intent(
        UIContext(category="text_input", native_role="AXTextField", source="test"),
        gesture="pinch",
        fallback_action="custom_hotkey",
    )

    assert intent.action == "none"
    assert intent.label == ""
    assert intent.requires_confirmation is False


def test_thumb_gesture_over_scrollable_target_becomes_a_scroll_intent():
    intent = resolve_contextual_intent(
        UIContext(
            category="scrollable", native_role="AXWebArea", source="test", target_id="safe-target"
        ),
        gesture="thumb_down",
        fallback_action="volume_down",
    )

    assert intent.action == "scroll_down"
    assert intent.label == "Scroll down"
    assert intent.requires_confirmation is False


def test_unknown_target_cannot_turn_fallback_into_a_contextual_action():
    intent = resolve_contextual_intent(
        UIContext(category="generic", source="test"),
        gesture="thumb_down",
        fallback_action="custom_hotkey",
    )

    assert intent.action == "none"
    assert intent.label == ""

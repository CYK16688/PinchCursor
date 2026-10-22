from platform_services.contracts import UIContext
from platform_services.policy import ContextPolicy


def test_text_input_blocks_drag_but_allows_point_and_pinch():
    policy = ContextPolicy.default()
    context = UIContext(category="text_input", native_role="AXTextField", source="test")

    assert policy.is_gesture_allowed(context, "point")
    assert policy.is_gesture_allowed(context, "pinch")
    assert not policy.is_gesture_allowed(context, "pinch_hold")
    assert not policy.is_action_allowed(context, "drag")


def test_generic_context_allows_pinch_hold_for_core_drag_lifecycle():
    policy = ContextPolicy.default()
    context = UIContext(category="generic", source="test")

    assert policy.is_gesture_allowed(context, "pinch_hold")


def test_configured_generic_context_allows_pinch_hold_for_core_drag_lifecycle():
    policy = ContextPolicy.from_config({
        "control_gestures": {"generic": ["point", "pinch", "pinch_hold", "peace"]}
    })

    assert policy.is_gesture_allowed(UIContext(category="generic", source="test"), "pinch_hold")


def test_configured_context_policy_replaces_known_category_rules_and_filters_unknown_gestures():
    policy = ContextPolicy.from_config({
        "control_gestures": {
            "scrollable": ["thumb_down", "not_a_gesture"],
            "not_a_category": ["point"],
        }
    })

    scrollable = UIContext(category="scrollable", source="test")
    clickable = UIContext(category="clickable", source="test")

    assert policy.is_gesture_allowed(scrollable, "thumb_down")
    assert not policy.is_gesture_allowed(scrollable, "thumb_up")
    assert policy.is_gesture_allowed(clickable, "point")


def test_disabled_context_policy_does_not_block_non_contextual_optional_gestures():
    policy = ContextPolicy.from_config({"enabled": False})

    assert policy.is_gesture_allowed(UIContext(category="scrollable"), "thumb_down")
    assert policy.is_action_allowed(UIContext(category="text_input"), "scroll_down")

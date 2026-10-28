from dataclasses import FrozenInstanceError

import pytest

from core.scroll_intent import ScrollIntentController


def update(controller, now, gesture="point", *, raw=None, anchor=(100, 200), allowed=True):
    return controller.update(
        gesture=gesture, raw_gesture=gesture if raw is None else raw,
        anchor=anchor, allowed=allowed, now=now,
    )


def arm(controller, start=0):
    assert update(controller, start) is None
    assert update(controller, start + 0.15) is None
    assert update(controller, start + 0.3) is None
    assert controller.armed


def enter(controller, start=0.31, gesture="thumb_up"):
    assert update(controller, start, gesture) is None
    intent = update(controller, start + 0.08, gesture)
    assert intent is not None
    return intent


def test_core_scroll_needs_point_dwell_then_raw_and_stable_thumb_confirmation():
    controller = ScrollIntentController()
    assert update(controller, 0, "thumb_up") is None
    assert update(controller, 1, "thumb_up") is None
    assert not controller.armed
    arm(controller, 2)
    assert update(controller, 2.31, "point", raw="thumb_up") is None
    assert update(controller, 2.4, "thumb_up") is None
    assert update(controller, 2.479, "thumb_up") is None
    intent = update(controller, 2.48, "thumb_up", anchor=(300, 400))
    assert intent.action == "scroll_up"
    assert intent.anchor == (100.0, 200.0)
    with pytest.raises(FrozenInstanceError):
        intent.action = "scroll_down"


def test_point_dwell_restarts_after_motion_or_interruption():
    controller = ScrollIntentController()
    update(controller, 0)
    update(controller, 0.2, anchor=(113, 200))
    update(controller, 0.3, anchor=(113, 200))
    assert not controller.armed
    update(controller, 0.5, anchor=(113, 200))
    assert controller.armed
    update(controller, 0.6, "open_hand")
    assert not controller.armed
    update(controller, 0.7)
    update(controller, 0.8, "thumb_up")
    update(controller, 2, "thumb_up")
    assert not controller.armed
    assert not controller.active


def test_point_drift_tolerance_uses_fixed_origin_not_cumulative_small_steps():
    controller = ScrollIntentController()
    update(controller, 0, anchor=(0, 0))
    update(controller, 0.1, anchor=(5, 0))
    update(controller, 0.2, anchor=(10, 0))
    update(controller, 0.3, anchor=(15, 0))
    assert not controller.armed
    update(controller, 0.6, anchor=(15, 0))
    assert controller.armed


def test_scroll_repeat_is_time_based_with_no_backlogged_catchup():
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    assert update(controller, 0.5, "thumb_up") is None
    assert update(controller, 0.51, "thumb_up").action == "scroll_up"
    assert update(controller, 5.0, "thumb_up").action == "scroll_up"
    assert update(controller, 5.01, "thumb_up") is None
    assert update(controller, 5.12, "thumb_up").action == "scroll_up"


def test_direction_reversal_keeps_anchor_but_requires_fresh_confirmation():
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    assert update(controller, 0.4, "thumb_up", raw="thumb_down") is None
    assert update(controller, 0.45, "thumb_down", anchor=(900, 800)) is None
    assert update(controller, 0.52, "thumb_down") is None
    intent = update(controller, 0.53, "thumb_down")
    assert intent.action == "scroll_down"
    assert intent.anchor == (100.0, 200.0)
    assert controller.active
    assert update(controller, 0.65, "thumb_down").action == "scroll_down"


def test_direction_reversal_also_respects_global_repeat_limit():
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    assert update(controller, 0.4, "thumb_down") is None
    assert update(controller, 0.48, "thumb_down") is None
    assert update(controller, 0.51, "thumb_down").action == "scroll_down"


@pytest.mark.parametrize("raw", ["point", "none", "pinch", "pinch_hold", "open_hand", "peace"])
def test_raw_pose_loss_immediately_stops_even_if_stabilized_thumb_lags(raw):
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    assert update(controller, 0.6, "thumb_up", raw=raw) is None
    assert not controller.active
    assert not controller.armed
    assert update(controller, 0.7, "thumb_up") is None
    assert update(controller, 1.0, "thumb_up") is None
    arm(controller, 2)
    assert enter(controller, 2.31).action == "scroll_up"


def test_disallowed_ownership_hand_loss_or_disarm_requires_new_point_dwell():
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    assert update(controller, 0.6, "thumb_up", allowed=False) is None
    assert not controller.active
    assert update(controller, 0.7, "thumb_up") is None
    assert update(controller, 1, "thumb_up") is None
    arm(controller, 2)
    assert enter(controller, 2.31, "thumb_down").action == "scroll_down"
    controller.reset()
    assert not controller.armed
    assert not controller.active


def test_return_to_point_stops_and_rearms_after_another_dwell():
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    update(controller, 0.6)
    assert not controller.active
    assert not controller.armed
    update(controller, 0.9)
    assert controller.armed
    assert enter(controller, 0.91).action == "scroll_up"


@pytest.mark.parametrize("now,anchor", [
    (0.39, (100, 200)),  # duplicated timestamp
    (0.2, (100, 200)),
    (float("nan"), (100, 200)),
    (float("inf"), (100, 200)),
    (0.5, (float("nan"), 200)),
    (0.5, None),
])
def test_invalid_or_replayed_evidence_resets_scroll(now, anchor):
    controller = ScrollIntentController()
    arm(controller)
    enter(controller)
    assert update(controller, now, "thumb_up", anchor=anchor) is None
    assert not controller.active
    assert not controller.armed


def test_repeat_interval_has_a_minimum_even_for_zero_configuration():
    controller = ScrollIntentController(dwell_seconds=0, enter_seconds=0, repeat_seconds=0)
    update(controller, 0)
    assert update(controller, 0.01, "thumb_up") is not None
    assert update(controller, 0.02, "thumb_up") is None
    assert update(controller, 0.03, "thumb_up") is not None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "0.1"])
def test_invalid_durations_are_rejected(value):
    with pytest.raises(ValueError):
        ScrollIntentController(repeat_seconds=value)


def test_default_config_enables_core_scroll_independently_of_context(tmp_path):
    from utils.config_manager import ConfigManager, DEFAULT_CONFIG

    assert DEFAULT_CONFIG["pointer_scroll"] == {
        "enabled": True, "dwell_seconds": 0.3, "repeat_seconds": 0.12, "enter_seconds": 0.08,
    }
    path = tmp_path / "settings.json"
    path.write_text('{"context_aware": {"enabled": false}}')
    config = ConfigManager(path).config
    assert config["pointer_scroll"]["enabled"]
    assert not config["context_aware"]["enabled"]

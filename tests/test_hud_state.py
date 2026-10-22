from gui.hud_state import HudController, HudState


def test_click_feedback_expires_after_220ms():
    hud = HudController()
    hud.show_click(now=1.0)

    assert hud.current_state(now=1.10) is HudState.CLICKED
    assert hud.current_state(now=1.23) is HudState.HIDDEN


def test_dragging_overrides_pointer_and_persists_until_released():
    hud = HudController()
    hud.show_pointer(now=1.0)
    hud.show_dragging(now=1.1)

    assert hud.current_state(now=2.0) is HudState.DRAGGING
    hud.hide_dragging()
    assert hud.current_state(now=2.0) is HudState.HIDDEN


def test_quiet_mode_hides_noncritical_pointer_feedback():
    hud = HudController(mode="quiet")

    hud.show_pointer(now=1.0)

    assert hud.current_state(now=1.0) is HudState.HIDDEN


def test_error_overrides_transient_click_feedback():
    hud = HudController()
    hud.show_click(now=1.0)
    hud.show_error("Accessibility required", now=1.1)

    assert hud.current_state(now=1.1) is HudState.ERROR

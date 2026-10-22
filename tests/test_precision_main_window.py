from gui.i18n import tr
from gui.main_window import control_button_model
from core.control_session import SessionState
from platform_services.contracts import AuthorizationState, PermissionSnapshot


def test_missing_accessibility_yields_authorization_primary_action():
    model = control_button_model(
        is_running=False,
        permissions=PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.DENIED,
        ),
    )

    assert model.label == tr("main.grant_accessibility")
    assert model.intent == "request_accessibility"


def test_ready_state_yields_start_primary_action():
    model = control_button_model(
        is_running=False,
        permissions=PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.GRANTED,
        ),
    )

    assert model.label == tr("main.start")
    assert model.intent == "start"


def test_undetermined_camera_without_a_prompt_offers_start_instead_of_grant():
    """Windows cannot raise a camera consent prompt, so the button must not claim it can."""
    model = control_button_model(
        is_running=False,
        permissions=PermissionSnapshot(
            camera=AuthorizationState.NOT_DETERMINED,
            accessibility=AuthorizationState.GRANTED,
        ),
        camera_promptable=False,
    )

    assert model.label == tr("main.start")
    assert model.intent == "start"


def test_undetermined_camera_with_a_prompt_still_asks_for_grant():
    """macOS must keep offering the explicit, user-initiated permission action."""
    model = control_button_model(
        is_running=False,
        permissions=PermissionSnapshot(
            camera=AuthorizationState.NOT_DETERMINED,
            accessibility=AuthorizationState.GRANTED,
        ),
        camera_promptable=True,
    )

    assert model.label == tr("main.grant_camera")
    assert model.intent == "request_camera"


def test_denied_camera_asks_for_grant_even_without_a_prompt():
    """A denied camera is fixed in system settings, so the label stays actionable."""
    model = control_button_model(
        is_running=False,
        permissions=PermissionSnapshot(
            camera=AuthorizationState.DENIED,
            accessibility=AuthorizationState.GRANTED,
        ),
        camera_promptable=False,
    )

    assert model.label == tr("main.grant_camera")
    assert model.intent == "request_camera"


def test_gesture_activation_state_explains_how_to_enable_pointer_control():
    from gui.main_window import control_session_status_model

    waiting = control_session_status_model(
        is_running=True,
        state=SessionState.INACTIVE,
        activation_gesture="open_hand",
    )
    armed = control_session_status_model(
        is_running=True,
        state=SessionState.ARMED,
        activation_gesture="open_hand",
    )
    pointer = control_session_status_model(
        is_running=True,
        state=SessionState.POINTER,
        activation_gesture="open_hand",
    )

    assert waiting.label == tr("session.wait_open_hand")
    assert armed.label == tr("session.armed")
    assert pointer.label == tr("session.active")

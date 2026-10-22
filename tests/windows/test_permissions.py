"""Windows permission reporting: honest states, no invented prompts."""

import pytest

from platform_services.contracts import AuthorizationState
from platform_services.windows.permissions import PERMISSION_NOTES, WindowsPermissionProvider


class FakeNative:
    def __init__(self, camera="not_determined"):
        self.camera = camera
        self.calls = 0

    def camera_authorization(self):
        self.calls += 1
        if isinstance(self.camera, Exception):
            raise self.camera
        return self.camera


def test_snapshot_reports_windows_realities_without_pretending():
    native = FakeNative()

    snapshot = WindowsPermissionProvider(native).snapshot()

    assert snapshot.camera is AuthorizationState.NOT_DETERMINED
    assert snapshot.accessibility is AuthorizationState.GRANTED
    assert snapshot.input_monitoring is AuthorizationState.UNAVAILABLE
    assert native.calls == 1


def test_snapshot_without_a_native_facade_still_reports_undetermined_camera():
    snapshot = WindowsPermissionProvider().snapshot()

    assert snapshot.camera is AuthorizationState.NOT_DETERMINED
    assert snapshot.accessibility is AuthorizationState.GRANTED


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("denied", AuthorizationState.DENIED),
        ("blocked", AuthorizationState.DENIED),
        ("authorized", AuthorizationState.GRANTED),
        ("GRANTED", AuthorizationState.GRANTED),
        ("unavailable", AuthorizationState.NOT_DETERMINED),
        ("something-new", AuthorizationState.NOT_DETERMINED),
        (None, AuthorizationState.NOT_DETERMINED),
    ],
)
def test_camera_state_maps_native_answers_conservatively(reported, expected):
    snapshot = WindowsPermissionProvider(FakeNative(camera=reported)).snapshot()

    assert snapshot.camera is expected


def test_camera_state_degrades_to_undetermined_when_the_query_fails():
    snapshot = WindowsPermissionProvider(FakeNative(camera=OSError("winrt missing"))).snapshot()

    assert snapshot.camera is AuthorizationState.NOT_DETERMINED


def test_no_permission_prompt_is_offered_or_claimed():
    provider = WindowsPermissionProvider(FakeNative())

    assert provider.request_accessibility_prompt() is False
    assert provider.request_input_monitoring_prompt() is False
    assert set(PERMISSION_NOTES) == {"accessibility", "input_monitoring", "camera"}


def test_camera_request_completes_immediately_because_windows_has_no_prompt():
    observed = []

    WindowsPermissionProvider(FakeNative()).request_camera_access(observed.append)

    assert observed == [True]


def test_camera_request_without_a_callback_does_not_raise():
    WindowsPermissionProvider(FakeNative()).request_camera_access(None)
    WindowsPermissionProvider(FakeNative()).request_camera_access("not-callable")


def test_accessibility_is_never_reported_as_denied_because_windows_never_asks():
    for camera in ("not_determined", "denied", "authorized"):
        snapshot = WindowsPermissionProvider(FakeNative(camera=camera)).snapshot()
        assert snapshot.accessibility is AuthorizationState.GRANTED

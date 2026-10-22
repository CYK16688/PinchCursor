from platform_services.contracts import AuthorizationState
from platform_services.macos.permissions import MacOSPermissionProvider


class CameraPromptNative:
    def __init__(self):
        self.requested = False

    def accessibility_trusted(self):
        return False

    def camera_authorization(self):
        return "not_determined"

    def request_camera_access(self, completion):
        self.requested = True
        completion(True)


def test_camera_permission_request_is_delegated_before_worker_startup():
    native = CameraPromptNative()
    received = []

    MacOSPermissionProvider(native).request_camera_access(received.append)

    assert native.requested is True
    assert received == [True]


def test_permission_snapshot_reports_independent_camera_accessibility_and_input_monitoring_states():
    class PermissionNative:
        def accessibility_trusted(self):
            return False

        def camera_authorization(self):
            return "not_determined"

        def input_monitoring_trusted(self):
            return True

    snapshot = MacOSPermissionProvider(PermissionNative()).snapshot()

    assert snapshot.camera == AuthorizationState.NOT_DETERMINED
    assert snapshot.accessibility == AuthorizationState.DENIED
    assert snapshot.input_monitoring == AuthorizationState.GRANTED


def test_input_monitoring_prompt_is_delegated_only_when_explicitly_requested():
    class PermissionNative:
        def accessibility_trusted(self):
            return True

        def camera_authorization(self):
            return "authorized"

        def input_monitoring_trusted(self):
            return False

        def request_input_monitoring_prompt(self):
            self.requested = True
            return False

    native = PermissionNative()

    assert native.__dict__.get("requested") is None
    assert MacOSPermissionProvider(native).request_input_monitoring_prompt() is False
    assert native.requested is True

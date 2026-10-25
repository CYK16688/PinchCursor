"""Windows permission reporting.

Windows has no TCC-style per-application gate for input injection or UI
automation, so only the camera question is real, and even that cannot be
answered reliably from a Win32 process without a WinRT/COM consent query. The
rule for this module is: never report GRANTED for something we did not verify.

* ``accessibility`` - GRANTED by construction: SendInput/UI Automation are not
  gated by a user-toggleable OS permission on Windows (UIPI elevation is a
  separate, per-target restriction reported at injection time).
* ``input_monitoring`` - UNAVAILABLE: the concept does not exist on Windows.
  Polling uses ``GetAsyncKeyState``, which needs no authorization.
* ``camera`` - whatever the native facade can prove; NOT_DETERMINED when it
  cannot prove anything, DENIED only on an explicit negative answer.
"""

from __future__ import annotations

from platform_services.contracts import AuthorizationState, PermissionSnapshot

# Rationale strings are kept for logs/support output; the platform contract has
# no field for them because macOS prompts carry that meaning already.
PERMISSION_NOTES = {
    "accessibility": "Windows does not gate input injection behind a user authorization prompt",
    "input_monitoring": "Windows has no input-monitoring authorization concept",
    "camera": "Camera consent cannot be determined reliably from a Win32 process",
}


class WindowsPermissionProvider:
    """Honest Windows permission snapshot with no prompts to offer."""

    def __init__(self, native=None):
        self.native = native

    def snapshot(self) -> PermissionSnapshot:
        return PermissionSnapshot(
            camera=self._camera_state(),
            accessibility=AuthorizationState.GRANTED,
            input_monitoring=AuthorizationState.UNAVAILABLE,
        )

    def request_accessibility_prompt(self) -> bool:
        """Windows has nothing to prompt for; returning False avoids fake dialogs."""
        return False

    def request_input_monitoring_prompt(self) -> bool:
        """Windows has no Input Monitoring authorization, so nothing is requested."""
        return False

    def open_privacy_settings(self, pane: str) -> bool:
        """Windows privacy pages exist but are not part of this contract's scope."""
        return False

    def request_camera_access(self, completion) -> None:
        """Continue immediately: there is no OS camera prompt to wait for.

        A missing or blocked camera fails when ``VideoCapture`` opens it, which
        the worker already reports through its camera-unavailable path.
        """
        if callable(completion):
            completion(True)

    def _camera_state(self) -> AuthorizationState:
        if self.native is None:
            return AuthorizationState.NOT_DETERMINED
        try:
            reported = self.native.camera_authorization()
        except Exception:
            return AuthorizationState.NOT_DETERMINED
        return self._to_camera_state(reported)

    @staticmethod
    def _to_camera_state(value: object) -> AuthorizationState:
        if isinstance(value, AuthorizationState):
            if value is AuthorizationState.GRANTED:
                return value
            if value is AuthorizationState.DENIED:
                return value
            return AuthorizationState.NOT_DETERMINED
        normalized = str(value).strip().lower()
        if normalized in {"authorized", "granted"}:
            return AuthorizationState.GRANTED
        if normalized in {"denied", "restricted", "blocked"}:
            return AuthorizationState.DENIED
        # Unknown or absent answers must stay undetermined rather than defaulting
        # to a state the GUI would treat as usable or as a refusal.
        return AuthorizationState.NOT_DETERMINED

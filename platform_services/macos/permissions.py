from __future__ import annotations

from platform_services.contracts import AuthorizationState, PermissionSnapshot


class MacOSPermissionProvider:
    def __init__(self, native):
        self.native = native

    def snapshot(self) -> PermissionSnapshot:
        return PermissionSnapshot(
            camera=self._to_authorization_state(self.native.camera_authorization()),
            accessibility=(
                AuthorizationState.GRANTED
                if self.native.accessibility_trusted()
                else AuthorizationState.DENIED
            ),
            input_monitoring=(
                AuthorizationState.GRANTED
                if self.native.input_monitoring_trusted()
                else AuthorizationState.DENIED
            ),
        )

    def request_accessibility_prompt(self) -> bool:
        return bool(self.native.request_accessibility_prompt())

    def request_input_monitoring_prompt(self) -> bool:
        return bool(self.native.request_input_monitoring_prompt())

    def open_privacy_settings(self, pane: str) -> bool:
        """Deep-link into the pane that owns one permission."""
        return bool(self.native.open_privacy_settings(pane))

    def request_camera_access(self, completion) -> None:
        """Request camera access on the Qt main thread before starting a worker."""
        self.native.request_camera_access(completion)

    @staticmethod
    def _to_authorization_state(value: str | int | AuthorizationState) -> AuthorizationState:
        if isinstance(value, AuthorizationState):
            return value
        normalized = str(value).lower()
        mapping = {
            "authorized": AuthorizationState.GRANTED,
            "granted": AuthorizationState.GRANTED,
            "denied": AuthorizationState.DENIED,
            "restricted": AuthorizationState.DENIED,
            "not_determined": AuthorizationState.NOT_DETERMINED,
            "unavailable": AuthorizationState.UNAVAILABLE,
        }
        return mapping.get(normalized, AuthorizationState.UNAVAILABLE)

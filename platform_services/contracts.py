from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from numbers import Real
from typing import Protocol


class AuthorizationState(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    NOT_DETERMINED = "not_determined"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PermissionSnapshot:
    camera: AuthorizationState
    accessibility: AuthorizationState
    input_monitoring: AuthorizationState = AuthorizationState.UNAVAILABLE


@dataclass(frozen=True)
class CameraDevice:
    device_id: str
    display_name: str
    kind: str
    available: bool


@dataclass(frozen=True)
class ActionRequest:
    action: str
    x: int | None = None
    y: int | None = None
    scroll_amount: int = 0
    hotkey: str = ""
    gesture: str = "none"
    # Core pointer lifecycle requests bypass optional contextual policy. Semantic
    # commands opt in and may bind execution to a freshly checked AX target.
    core_pointer: bool = False
    contextual: bool = False
    expected_target_id: str = ""


@dataclass(frozen=True)
class ActionResult:
    executed: bool
    reason: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class UIContext:
    category: str
    native_role: str = ""
    source: str = ""
    # Ephemeral, non-content fingerprint used only to invalidate a live
    # contextual candidate when the accessible target changes.
    target_id: str = ""
    # Screen-space frame (x, y, width, height) in points. Optional: a provider
    # that cannot read geometry leaves it None, and point assist simply does
    # not engage. Never used for identity, only for aiming.
    bounds: tuple[int, int, int, int] | None = None
    is_enabled: bool = True


@dataclass(frozen=True)
class PlatformCapabilities:
    platform: str
    architecture: str
    supported_actions: frozenset[str] = field(default_factory=frozenset)
    unavailable_reasons: dict[str, str] = field(default_factory=dict)
    permissions: PermissionSnapshot = field(
        default_factory=lambda: PermissionSnapshot(
            camera=AuthorizationState.UNAVAILABLE,
            accessibility=AuthorizationState.UNAVAILABLE,
        )
    )
    # False on platforms with no in-app camera consent prompt (Windows). The UI
    # must then offer "Start control" instead of "Grant camera access", because
    # no click can produce a system prompt -- capture either opens or fails.
    camera_permission_promptable: bool = True


def normalize_cursor_position(position: object) -> tuple[float, float] | None:
    """Accept only a finite numeric pair at the native pointer boundary."""
    if not isinstance(position, (tuple, list)) or len(position) != 2:
        return None
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in position):
        return None
    try:
        x, y = float(position[0]), float(position[1])
    except (TypeError, ValueError, OverflowError):
        return None
    return (x, y) if isfinite(x) and isfinite(y) else None


class SystemInputController(Protocol):
    @property
    def supported_actions(self) -> frozenset[str]: ...

    def execute(self, request: ActionRequest) -> ActionResult: ...

    def release_drag(self) -> ActionResult: ...

    def cursor_position(self) -> tuple[float, float] | None:
        """Read the actual OS pointer without moving it; None if unavailable."""
        ...


class UIContextProvider(Protocol):
    def get_context(self, x: int | None = None, y: int | None = None) -> UIContext: ...

    def is_gesture_allowed(self, gesture: str, x: int | None = None, y: int | None = None) -> bool: ...

    def is_action_allowed(self, action: str, x: int | None = None, y: int | None = None) -> bool: ...


class PermissionProvider(Protocol):
    def snapshot(self) -> PermissionSnapshot: ...

    def request_accessibility_prompt(self) -> bool: ...

    def request_input_monitoring_prompt(self) -> bool: ...

    def open_privacy_settings(self, pane: str) -> bool: ...


class HoldShortcutMonitor(Protocol):
    """Observes one configured global shortcut without consuming input."""

    def configure(self, shortcut: str) -> bool: ...

    def start(self) -> bool: ...

    def stop(self) -> None: ...

    def is_held(self) -> bool: ...


class CameraService(Protocol):
    def list_devices(self) -> list[CameraDevice]: ...

    def open_selected(self, device_id: str, width: int, height: int): ...


@dataclass(frozen=True)
class PlatformServices:
    capabilities: PlatformCapabilities
    input_controller: SystemInputController
    context_provider: UIContextProvider
    permission_provider: PermissionProvider
    camera_service: CameraService | None = None
    hold_shortcut_monitor: HoldShortcutMonitor | None = None

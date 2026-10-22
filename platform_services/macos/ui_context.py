from __future__ import annotations

import hashlib
import math

from platform_services.contracts import UIContext
from platform_services.policy import ContextPolicy


# Categories that can be an aiming target. Containers are excluded on
# purpose: snapping to a scroll area would move the cursor for no reason.
# Sliders are aimable: a thin track is the control point assist helps most
# with, and it is otherwise almost impossible to grab with a pinch.
PROBE_CATEGORIES = frozenset({"clickable", "menu", "slider"})

# Screen-space offsets, as fractions of the probe radius, in probe order:
# centre first, then three rings of eight. Ordered so a small budget still
# covers the immediate neighbourhood. The innermost ring shrinks the largest
# unsampled gap from 0.5 r to 0.33 r; that is what catches controls that sit
# between the old samples.
_PROBE_RINGS = (0.0, 0.33, 0.66, 1.0)

# Frames larger than this share of the main screen are containers, not
# controls. Scroll views are routinely reported as clickable at the leaf, and
# snapping the cursor to a full-window element is never what the user meant.
_CONTAINER_AREA_RATIO = 0.6


def probe_offsets(radius: int) -> list[tuple[int, int]]:
    """Return deterministic probe offsets covering the cursor neighbourhood."""
    offsets: list[tuple[int, int]] = [(0, 0)]
    for ring in _PROBE_RINGS[1:]:
        distance = int(round(radius * ring))
        for step in range(8):
            angle = step * math.pi / 4
            dx = int(round(distance * math.cos(angle)))
            dy = int(round(distance * math.sin(angle)))
            offsets.append((dx, dy))
    return offsets


def _main_screen_area(native) -> float:
    """Return the main screen area in points, or 0.0 when it cannot be read.

    Only the container filter consumes this, so a missing display or a facade
    without NSScreen must disable that one filter rather than fail the probe.
    """
    appkit = getattr(native, "appkit", None)
    if appkit is None:
        try:
            import AppKit as appkit
        except Exception:
            return 0.0
    try:
        screen = appkit.NSScreen.mainScreen()
        frame = screen.frame() if screen is not None else None
        size = frame.size
        width, height = float(size.width), float(size.height)
    except Exception:
        return 0.0
    if width <= 0.0 or height <= 0.0:
        return 0.0
    return width * height


def _aimable_bounds(bounds: object) -> tuple[int, int, int, int] | None:
    """Return a validated screen frame, or None when it cannot be aimed at."""
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 4:
        return None
    try:
        frame = [int(value) for value in bounds]
    except (TypeError, ValueError, OverflowError):
        return None
    if frame[2] <= 0 or frame[3] <= 0:
        return None
    return (frame[0], frame[1], frame[2], frame[3])


def _bounds_area(bounds: tuple[int, int, int, int]) -> int:
    """Return a validated frame's area in square points."""
    return bounds[2] * bounds[3]


ROLE_CATEGORIES = {
    "AXTextField": "text_input",
    "AXTextArea": "text_input",
    "AXButton": "clickable",
    "AXCheckBox": "clickable",
    "AXRadioButton": "clickable",
    "AXSlider": "slider",
    "AXScrollBar": "slider",
    "AXMenu": "menu",
    "AXMenuItem": "menu",
    "AXList": "scrollable",
    "AXOutline": "scrollable",
    "AXScrollArea": "scrollable",
    "AXWebArea": "scrollable",
}


def _valid_process_id(value: object) -> bool:
    # bool is an int subclass in Python, but never a valid native process ID.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _target_fingerprint(element: dict) -> str:
    """Return a verified, non-content process-local identity for candidate gating."""
    process_id = element.get("process_id")
    if (
        element.get("identity_verified") is not True
        or element.get("identity_path_verified") is not True
        or not _valid_process_id(process_id)
    ):
        return ""

    materials = []
    current = element
    seen = set()
    for _ in range(5):
        if current is None:
            break
        if not isinstance(current, dict) or id(current) in seen:
            return ""
        seen.add(id(current))
        role = current.get("role", "")
        identifier = current.get("identifier", "")
        current_process_id = current.get("process_id")
        # AXApplication is a process-local terminal anchor. The owning PID is
        # already fingerprint material, so an application root is not a target
        # or structural identity node and does not need an AX identifier or a
        # sibling list. Any other anonymous ancestor remains unsafe.
        if role == "AXApplication" and current.get("parent") is None:
            if (
                current.get("identity_path_verified") is not True
                or not _valid_process_id(current_process_id)
                or current_process_id != process_id
            ):
                return ""
            break
        # Every identity-bearing node in the bounded structural path needs a
        # unique, non-content identifier. An anonymous or ambiguous ancestor
        # could be a different container on the next frame, so fail closed.
        if (
            current.get("identity_verified") is not True
            or current.get("identity_path_verified") is not True
            or not _valid_process_id(current_process_id)
            or current_process_id != process_id
            or not isinstance(role, str)
            or not role
            or not isinstance(identifier, str)
            or not identifier
        ):
            return ""
        materials.append((role, identifier))
        current = current.get("parent")
    else:
        # A non-empty sixth node is a truncated identity path.
        if current is not None:
            return ""
    if not materials:
        return ""
    material = "\x1e".join(
        [f"pid\x1f{process_id}"]
        + [f"{role}\x1f{identifier}" for role, identifier in materials]
    )
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:32]


class MacOSUIContextProvider:
    def __init__(self, native, policy: ContextPolicy | None = None):
        self.native = native
        self.policy = policy or ContextPolicy.default()

    def get_context(self, x: int | None = None, y: int | None = None) -> UIContext:
        if x is None or y is None:
            return UIContext(category="generic", source="missing_coordinates")
        try:
            element = self.native.element_at_position(x, y)
        except Exception:
            return UIContext(category="generic", source="accessibility_unavailable")

        current = element
        for _ in range(5):
            if not current:
                break
            role = current.get("role", "")
            category = ROLE_CATEGORIES.get(role)
            if category:
                return UIContext(
                    category=category,
                    native_role=role,
                    source="accessibility",
                    target_id=_target_fingerprint(current),
                    bounds=current.get("bounds"),
                    is_enabled=current.get("enabled", True) is not False,
                )
            current = current.get("parent")
        return UIContext(category="generic", source="accessibility")

    def probe_targets(
        self,
        x: int,
        y: int,
        radius: int = 120,
    ) -> list[UIContext]:
        """Return distinct aimable targets near a screen point.

        Candidates come from hit tests on a fixed offset pattern rather than a
        tree walk: it is bounded in cost, needs no extra accessibility
        traversal, and only reports what is genuinely under (or adjacent to)
        the pointer.

        Point assist is an optimisation, never a requirement, so a probe that
        cannot run returns no candidates instead of raising into the click
        path. A single failed hit test only drops that sample.
        """
        try:
            return self._probe_targets(x, y, radius)
        except Exception:
            return []

    def _probe_targets(self, x: int, y: int, radius: int) -> list[UIContext]:
        if not isinstance(x, int) or not isinstance(y, int):
            return []
        if isinstance(radius, bool) or not isinstance(radius, (int, float)):
            return []
        if radius <= 0:
            return []
        light = getattr(self.native, "element_box_at_position", None)
        # Read screen geometry once per probe, not once per sample. A zero area
        # means the display is unknown, which only disables the container
        # filter.
        container_limit = _main_screen_area(self.native) * _CONTAINER_AREA_RATIO
        found: dict[tuple[str, tuple[int, int, int, int]], UIContext] = {}
        for dx, dy in probe_offsets(radius):
            try:
                element = (
                    light(x + dx, y + dy)
                    if light is not None
                    else self.native.element_at_position(x + dx, y + dy)
                )
            except Exception:
                continue
            if not isinstance(element, dict):
                continue
            role = str(element.get("role") or "")
            category = ROLE_CATEGORIES.get(role)
            bounds = _aimable_bounds(element.get("bounds"))
            if category not in PROBE_CATEGORIES or bounds is None:
                continue
            if element.get("enabled", True) is False:
                continue
            # Window-sized "clickable" leaves are containers (scroll views,
            # web areas). Aiming at them would drag the cursor to the frame
            # centre for no benefit.
            if container_limit > 0.0 and _bounds_area(bounds) > container_limit:
                continue
            key = (role, bounds)
            found.setdefault(
                key,
                UIContext(
                    category=category,
                    native_role=role,
                    source="probe",
                    bounds=bounds,
                    is_enabled=True,
                ),
            )
        return list(found.values())

    def is_gesture_allowed(self, gesture: str, x: int | None = None, y: int | None = None) -> bool:
        return self.policy.is_gesture_allowed(self.get_context(x, y), gesture)

    def is_action_allowed(self, action: str, x: int | None = None, y: int | None = None) -> bool:
        return self.policy.is_action_allowed(self.get_context(x, y), action)

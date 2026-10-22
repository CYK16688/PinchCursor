from __future__ import annotations

from typing import Callable


def open_configured_camera(
    camera_config: dict,
    camera_service,
    legacy_open: Callable[[int], object],
):
    """Prefer stable platform device identity; retain index fallback temporarily."""
    device_id = camera_config.get("device_id", "")
    width = camera_config.get("width", 640)
    height = camera_config.get("height", 480)
    if device_id:
        return camera_service.open_selected(device_id, width, height)
    return legacy_open(camera_config.get("id", 0))

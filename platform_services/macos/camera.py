from __future__ import annotations

import cv2

from platform_services.contracts import CameraDevice


class MacOSCameraService:
    def __init__(self, native):
        self.native = native

    def list_devices(self) -> list[CameraDevice]:
        return [
            CameraDevice(
                device_id=device["unique_id"],
                display_name=device["name"],
                kind=device.get("kind", "unknown"),
                available=bool(device.get("available", False)),
            )
            for device in self.native.list_video_devices()
        ]

    def open_selected(self, device_id: str, width: int, height: int):
        index = self.native.open_cv_index_for_device(device_id)
        if index is None:
            return None
        capture = cv2.VideoCapture(index)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        return capture

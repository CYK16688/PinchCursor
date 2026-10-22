from platform_services.camera_selection import open_configured_camera


class CameraService:
    def __init__(self):
        self.calls = []

    def open_selected(self, device_id, width, height):
        self.calls.append((device_id, width, height))
        return "selected-capture"


def test_nonempty_stable_device_id_is_passed_to_open_selected_not_legacy_open():
    service = CameraService()
    legacy_calls = []
    config = {"device_id": "usb-001", "id": 0, "width": 1280, "height": 720}

    capture = open_configured_camera(
        config,
        service,
        legacy_open=lambda camera_id: legacy_calls.append(camera_id) or "legacy-capture",
    )

    assert capture == "selected-capture"
    assert service.calls == [("usb-001", 1280, 720)]
    assert legacy_calls == []


def test_unavailable_nonempty_selected_device_fails_closed_without_legacy_fallback():
    class UnavailableSelectedCameraService:
        def __init__(self):
            self.calls = []

        def open_selected(self, device_id, width, height):
            self.calls.append((device_id, width, height))
            return None

    service = UnavailableSelectedCameraService()
    legacy_calls = []
    config = {"device_id": "usb-missing", "id": 2, "width": 1280, "height": 720}

    capture = open_configured_camera(
        config,
        service,
        legacy_open=lambda camera_id: legacy_calls.append(camera_id) or "legacy-capture",
    )

    assert capture is None
    assert service.calls == [("usb-missing", 1280, 720)]
    assert legacy_calls == []

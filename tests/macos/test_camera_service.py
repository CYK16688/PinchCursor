from platform_services.macos.camera import MacOSCameraService


class CameraNative:
    def list_video_devices(self):
        return [
            {
                "unique_id": "builtin-001",
                "name": "FaceTime HD Camera",
                "kind": "built_in",
                "available": True,
            },
            {
                "unique_id": "usb-001",
                "name": "Logitech Brio 4K",
                "kind": "external",
                "available": True,
            },
        ]


def test_macos_camera_service_preserves_stable_avfoundation_ids():
    devices = MacOSCameraService(CameraNative()).list_devices()

    assert [(device.device_id, device.display_name) for device in devices] == [
        ("builtin-001", "FaceTime HD Camera"),
        ("usb-001", "Logitech Brio 4K"),
    ]


def test_macos_camera_service_exposes_unavailable_external_device():
    native = CameraNative()
    native.list_video_devices = lambda: [
        {
            "unique_id": "usb-001",
            "name": "Logitech Brio 4K",
            "kind": "external",
            "available": False,
        }
    ]

    device = MacOSCameraService(native).list_devices()[0]

    assert device.kind == "external"
    assert device.available is False

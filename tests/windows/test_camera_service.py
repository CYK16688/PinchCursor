"""Windows camera service: index probing, stable ids, and honest absence."""

import cv2
import pytest

from platform_services.windows.camera import (
    DEVICE_ID_PREFIX,
    UnavailableCameraService,
    WindowsCameraService,
)


class FakeCapture:
    def __init__(self, opened=True, delivers_frames=True):
        self.opened = opened
        self.delivers_frames = delivers_frames
        self.settings = []
        self.reads = 0
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        self.reads += 1
        return (True, object()) if self.delivers_frames else (False, None)

    def set(self, prop, value):
        self.settings.append((prop, value))
        return True

    def release(self):
        self.released = True


def make_factory(specs):
    """specs maps index -> FakeCapture, Exception, or None (closed device)."""
    created = []

    def factory(index):
        created.append(index)
        spec = specs.get(index)
        if isinstance(spec, Exception):
            raise spec
        if spec is None:
            return FakeCapture(opened=False)
        return spec

    factory.created = created
    return factory


def test_windows_camera_service_does_not_claim_devices_on_macos():
    service = UnavailableCameraService()

    assert service.list_devices() == []
    assert service.open_selected("not-real", 640, 480) is None


def test_list_devices_reports_only_cameras_that_deliver_a_frame():
    usable = FakeCapture()
    unreadable = FakeCapture(delivers_frames=False)
    service = WindowsCameraService(
        capture_factory=make_factory({0: usable, 1: None, 2: unreadable}),
        max_devices=3,
    )

    devices = service.list_devices()

    assert [(device.device_id, device.display_name) for device in devices] == [
        (f"{DEVICE_ID_PREFIX}0", "Camera 0")
    ]
    assert devices[0].kind == "unknown"
    assert devices[0].available is True


def test_probing_releases_every_capture_it_opened():
    opened = {0: FakeCapture(), 1: FakeCapture(opened=False), 2: FakeCapture(delivers_frames=False)}
    service = WindowsCameraService(capture_factory=make_factory(opened), max_devices=3)

    service.list_devices()

    assert all(capture.released for capture in opened.values())


def test_list_devices_returns_nothing_when_the_native_backend_is_unavailable():
    factory = make_factory({index: RuntimeError("no DirectShow") for index in range(3)})
    service = WindowsCameraService(capture_factory=factory, max_devices=3)

    assert service.list_devices() == []
    assert factory.created == [0, 1, 2]


def test_device_ids_encode_the_capture_index_and_survive_a_gap():
    service = WindowsCameraService(
        capture_factory=make_factory({1: FakeCapture(), 3: FakeCapture()}),
        max_devices=4,
    )

    assert [device.device_id for device in service.list_devices()] == [
        f"{DEVICE_ID_PREFIX}1",
        f"{DEVICE_ID_PREFIX}3",
    ]


def test_open_selected_opens_the_requested_index_and_applies_the_resolution():
    target = FakeCapture()
    factory = make_factory({2: target})
    service = WindowsCameraService(capture_factory=factory)

    capture = service.open_selected(f"{DEVICE_ID_PREFIX}2", 1280, 720)

    assert capture is target
    assert factory.created == [2]
    assert target.settings == [
        (cv2.CAP_PROP_FRAME_WIDTH, 1280),
        (cv2.CAP_PROP_FRAME_HEIGHT, 720),
    ]


@pytest.mark.parametrize(
    "device_id",
    ["", "camera-1", "windows-index-", "windows-index-x", "windows-index-1x", None, 3],
)
def test_open_selected_rejects_any_other_identity_without_touching_hardware(device_id):
    factory = make_factory({})
    service = WindowsCameraService(capture_factory=factory)

    assert service.open_selected(device_id, 640, 480) is None
    assert factory.created == []


def test_open_selected_returns_none_and_releases_a_closed_device():
    closed = FakeCapture(opened=False)
    service = WindowsCameraService(capture_factory=make_factory({0: closed}))

    assert service.open_selected(f"{DEVICE_ID_PREFIX}0", 640, 480) is None
    assert closed.released is True


def test_open_selected_returns_none_when_the_backend_raises():
    service = WindowsCameraService(capture_factory=make_factory({0: OSError("in use")}))

    assert service.open_selected(f"{DEVICE_ID_PREFIX}0", 640, 480) is None


def test_device_list_is_cached_briefly_but_refreshes_on_demand():
    now = [100.0]
    factory = make_factory({0: FakeCapture()})
    service = WindowsCameraService(
        capture_factory=factory, max_devices=2, cache_seconds=2.0, clock=lambda: now[0]
    )

    service.list_devices()
    service.list_devices()

    assert factory.created == [0, 1]

    service.list_devices(force=True)
    assert factory.created == [0, 1, 0, 1]

    now[0] += 5.0
    service.list_devices()
    assert factory.created == [0, 1, 0, 1, 0, 1]


def test_device_id_parsing_is_pure_and_precise():
    assert WindowsCameraService.index_for_device("windows-index-7") == 7
    assert WindowsCameraService.index_for_device("windows-index-00") == 0
    assert WindowsCameraService.index_for_device("WINDOWS-INDEX-7") is None
    assert WindowsCameraService.index_for_device("windows-index-7-1") is None
    assert WindowsCameraService.index_for_device("") is None


def test_a_handed_out_camera_is_not_re_opened_by_the_next_probe():
    active = FakeCapture()
    factory = make_factory({0: FakeCapture(), 1: active})
    service = WindowsCameraService(capture_factory=factory, max_devices=2)
    service.open_selected(f"{DEVICE_ID_PREFIX}1", 640, 480)
    factory.created.clear()

    devices = service.list_devices()

    assert [device.device_id for device in devices] == [
        f"{DEVICE_ID_PREFIX}0",
        f"{DEVICE_ID_PREFIX}1",
    ]
    # Only the untouched index is probed; the live capture is left alone.
    assert factory.created == [0]


def test_a_handed_out_device_survives_a_second_open_that_would_now_fail():
    active = FakeCapture()
    specs = {0: active}
    factory = make_factory(specs)
    service = WindowsCameraService(capture_factory=factory, max_devices=1)
    service.open_selected(f"{DEVICE_ID_PREFIX}0", 640, 480)
    specs[0] = OSError("device in use by this process")

    devices = service.list_devices(force=True)

    assert [device.device_id for device in devices] == [f"{DEVICE_ID_PREFIX}0"]
    assert devices[0].available is True


def test_probing_resumes_once_the_handed_out_capture_is_closed():
    active = FakeCapture()
    factory = make_factory({0: active})
    service = WindowsCameraService(capture_factory=factory, max_devices=1)
    service.open_selected(f"{DEVICE_ID_PREFIX}0", 640, 480)
    active.opened = False
    factory.created.clear()

    assert service.list_devices(force=True) == []
    assert factory.created == [0]

"""Point-assist probe coverage: denser sampling, sliders, container filtering."""

from types import SimpleNamespace

import pytest

from platform_services.macos.ui_context import MacOSUIContextProvider, probe_offsets


def _appkit(width: int, height: int):
    """Return a stand-in AppKit exposing the one screen query the probe uses."""
    frame = SimpleNamespace(size=SimpleNamespace(width=width, height=height))
    screen = SimpleNamespace(frame=lambda: frame)
    return SimpleNamespace(NSScreen=SimpleNamespace(mainScreen=lambda: screen))


def _unreadable_appkit():
    """Return an AppKit stand-in whose main screen cannot be resolved."""
    return SimpleNamespace(NSScreen=SimpleNamespace(mainScreen=lambda: None))


class FakeNative:
    """Minimal facade: maps a screen point to a serialized accessibility leaf."""

    def __init__(self, elements=None, *, screen: tuple[int, int] | None = (1920, 1080)):
        self.elements = dict(elements or {})
        self.appkit = _appkit(*screen) if screen else _unreadable_appkit()
        self.calls: list[tuple[int, int]] = []

    def element_box_at_position(self, x, y):
        self.calls.append((x, y))
        return self.elements.get((x, y))

    def element_at_position(self, x, y):
        raise AssertionError("probe must prefer the shallow box hit test")


def _element(role: str, bounds, *, enabled: bool = True):
    return {"role": role, "bounds": bounds, "enabled": enabled}


def _provider(native) -> MacOSUIContextProvider:
    return MacOSUIContextProvider(native)


def test_probe_offsets_are_centre_first_then_three_rings_of_eight():
    offsets = probe_offsets(120)

    assert len(offsets) == 25
    assert offsets[0] == (0, 0)
    # One cardinal sample per ring proves ring order and spacing.
    assert offsets[1] == (40, 0)
    assert offsets[9] == (79, 0)
    assert offsets[17] == (120, 0)
    assert len(set(offsets)) == 25


def test_a_button_seen_by_several_samples_is_collected_once():
    button = _element("AXButton", (300, 300, 80, 30))
    # Centre plus the 0-degree sample of each ring, so the same frame is hit
    # four times and must collapse into one candidate.
    native = FakeNative({point: button for point in {(500, 500), (540, 500), (579, 500), (620, 500)}})

    targets = _provider(native).probe_targets(500, 500)

    assert len(native.calls) == 25
    assert len(targets) == 1
    assert targets[0].category == "clickable"
    assert targets[0].native_role == "AXButton"
    assert targets[0].source == "probe"
    assert targets[0].bounds == (300, 300, 80, 30)


def test_distinct_buttons_at_different_frames_are_both_collected():
    native = FakeNative(
        {
            (500, 500): _element("AXButton", (400, 480, 60, 40)),
            (620, 500): _element("AXCheckBox", (600, 480, 24, 24)),
        }
    )

    targets = _provider(native).probe_targets(500, 500)

    assert sorted(target.bounds for target in targets) == [
        (400, 480, 60, 40),
        (600, 480, 24, 24),
    ]
    assert {target.category for target in targets} == {"clickable"}


def test_sliders_and_scrollbars_are_aimable():
    native = FakeNative(
        {
            (500, 500): _element("AXSlider", (300, 480, 200, 20)),
            (540, 500): _element("AXScrollBar", (700, 100, 12, 300)),
        }
    )

    targets = _provider(native).probe_targets(500, 500)

    assert [target.native_role for target in targets] == ["AXSlider", "AXScrollBar"]
    assert {target.category for target in targets} == {"slider"}
    assert all(target.bounds for target in targets)


@pytest.mark.parametrize("role", ["AXTextField", "AXTextArea", "AXScrollArea", "AXList", "AXWebArea"])
def test_text_inputs_and_scroll_containers_are_not_aimable(role):
    # Scroll-area frames here are ordinary-sized, so only the category rule can
    # reject them; the container-area filter is covered separately.
    native = FakeNative({(500, 500): _element(role, (400, 480, 200, 24))})

    assert _provider(native).probe_targets(500, 500) == []


def test_window_sized_clickable_frames_are_not_candidates():
    # 2000x1200 exceeds 60% of the fake 1920x1080 display, so this is a scroll
    # view or web area mislabelled as clickable, not an aimable control.
    native = FakeNative({(500, 500): _element("AXButton", (0, 0, 2000, 1200))})

    assert _provider(native).probe_targets(500, 500) == []


def test_container_filter_is_skipped_when_the_screen_is_unknown():
    native = FakeNative({(500, 500): _element("AXButton", (0, 0, 2000, 1200))}, screen=None)

    targets = _provider(native).probe_targets(500, 500)

    assert len(targets) == 1
    assert targets[0].bounds == (0, 0, 2000, 1200)


def test_a_failing_native_returns_no_candidates():
    class BrokenNative:
        appkit = _appkit(1920, 1080)

        def element_box_at_position(self, x, y):
            raise RuntimeError("accessibility went away")

    assert _provider(BrokenNative()).probe_targets(10, 10) == []


def test_repeated_probes_return_the_same_targets_in_the_same_order():
    native = FakeNative(
        {
            (500, 500): _element("AXButton", (460, 480, 80, 30)),
            (620, 500): _element("AXSlider", (600, 490, 200, 20)),
        }
    )
    provider = _provider(native)

    first = provider.probe_targets(500, 500)
    second = provider.probe_targets(500, 500)

    assert [(target.category, target.bounds) for target in first] == [
        (target.category, target.bounds) for target in second
    ]
    assert [target.native_role for target in first] == ["AXButton", "AXSlider"]

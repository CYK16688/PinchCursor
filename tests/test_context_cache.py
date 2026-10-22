"""The AX context cache: fewer accessibility round-trips per frame."""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from platform_services.contracts import UIContext


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class CountingProvider:
    def __init__(self):
        self.calls = 0

    def get_context(self, x=None, y=None):
        self.calls += 1
        return UIContext(category="generic", source="counting")


def _window():
    provider = CountingProvider()
    window = MainWindow.__new__(MainWindow)
    window.platform_services = SimpleNamespace(context_provider=provider)
    return window, provider


def test_repeated_lookups_at_the_same_spot_hit_the_cache(app):
    window, provider = _window()

    for _ in range(10):
        MainWindow._cached_context(window, 100, 100)

    assert provider.calls == 1


def test_small_jitter_stays_in_the_cache(app):
    window, provider = _window()
    MainWindow._cached_context(window, 100, 100)

    MainWindow._cached_context(window, 108, 106)

    assert provider.calls == 1


def test_a_real_move_refetches(app):
    window, provider = _window()
    MainWindow._cached_context(window, 100, 100)

    MainWindow._cached_context(window, 140, 100)

    assert provider.calls == 2


def test_an_expired_entry_refetches(app):
    window, provider = _window()
    window._context_cache = (100, 100, time.monotonic() - 1.0, UIContext(category="generic"))

    MainWindow._cached_context(window, 100, 100)

    assert provider.calls == 1


def test_thirty_frames_of_pointing_cost_a_handful_of_lookups(app):
    """One second at 30 fps must not mean 30 accessibility hit tests."""
    window, provider = _window()
    start = time.monotonic()
    calls = 0
    for frame in range(30):
        MainWindow._cached_context(window, 100 + (frame % 5), 100)
        # The cache is time-based; force expiry every 4 frames to model a
        # second of real pointing without sleeping.
        if frame % 4 == 3:
            cached = window._context_cache
            window._context_cache = (cached[0], cached[1], cached[2] - 1.0, cached[3])
            calls += 1

    assert provider.calls <= 9
    assert time.monotonic() - start < 1.0

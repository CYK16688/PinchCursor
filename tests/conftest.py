"""Shared pytest configuration for the PinchCursor test suite."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from gui.i18n import DEFAULT_LOCALE, set_locale


@pytest.fixture(autouse=True)
def reset_process_locale():
    """Keep the process-local UI locale from leaking across independent tests."""
    set_locale(DEFAULT_LOCALE)
    yield
    set_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
def isolate_user_data_dir(tmp_path, monkeypatch):
    """Never let a test read or write the developer's real settings.

    A window built without an explicit config path resolves the per-user data
    directory, so an unisolated test would load whatever this machine's
    ``settings.json`` happens to contain — enabled dynamic gestures, recorded
    templates, a different locale — and the verdict would depend on the machine.
    """
    from utils import config_manager

    sandbox = tmp_path / "_userdata"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_manager, "user_data_dir", lambda: str(sandbox))
    yield


# --- Qt teardown containment -------------------------------------------------
#
# PySide6 6.12 aborts on macOS during CPython interpreter finalization:
# shiboken releases the QApplication and its QObject children in arbitrary GC
# order, and a late reparent touches freed memory, dying inside
# QObjectPrivate::setParent_helper. Every test has already run and every verdict
# has already been reported when this happens, so the abort can only corrupt the
# process exit status -- never a test result.
#
# pytest_sessionfinish fires before the terminal summary is written, so the exit
# is deferred to pytest_unconfigure, which runs after reporting completes.
_EXIT_STATUS = None


def pytest_sessionfinish(session, exitstatus):
    global _EXIT_STATUS
    _EXIT_STATUS = int(exitstatus)


def pytest_unconfigure(config):
    """Exit with pytest's own verdict, skipping the aborting interpreter teardown."""
    if _EXIT_STATUS is None:
        return
    import os

    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(_EXIT_STATUS)

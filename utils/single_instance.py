"""Process-wide application instance guard for the desktop entry point."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class SingleInstanceGuard:
    """Own one non-blocking advisory lock without deleting another process's file."""

    def __init__(self, lock_path: Path | str | None = None):
        self.lock_path = Path(lock_path) if lock_path is not None else (
            Path.home() / "Library" / "Application Support" / "Gesture Control" / "gesture-control.lock"
        )
        self._handle = None
        self._acquired = False

    def acquire(self) -> bool:
        """Try to become the sole running instance without blocking."""
        if self._acquired:
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        try:
            if sys.platform == "win32":
                handle.seek(0)
                if not handle.read(1):
                    handle.write("0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        self._acquired = True
        return True

    def release(self) -> None:
        """Release only this guard's advisory lock; leave its lock file in place."""
        if self._handle is None:
            return
        try:
            if self._acquired:
                if sys.platform == "win32":
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
            self._acquired = False

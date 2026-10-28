# PySide6 Migration Record

> Historical migration evidence. Build names, bundle sizes and test counts below
> describe that migration; use [Local Development](DEVELOPMENT.md) and
> [Validation Matrix](VALIDATION.md) for the current project.

**Date:** 2026-10-21
**From:** PyQt5 5.15 / Qt 5 / Python 3.11
**To:** PySide6 6.12.0 / Qt 6.12 / Python 3.13

## Why

| Driver | Detail |
|---|---|
| Qt 5 is end-of-life | Qt 5.15 open-source support ended 2020-12-08; commercial support ended 2025-05-25. No further security patches. |
| Licensing | PyQt5 is GPLv3-or-commercial. PySide6 is LGPL-3.0, so closed-source distribution is permitted without buying a licence. |
| Upstream direction | PySide6 is the Qt Company's official binding; PyQt is third-party. |
| Dependency floor | `numpy` 2.5.4 requires Python >= 3.12, which forces an interpreter upgrade in any case. |

## Final dependency set

| Package | Version | Note |
|---|---|---|
| Python | 3.13 | `numpy` 2.5.4 requires >= 3.12 |
| PySide6 | 6.12.0 | current LTS line (OSS support to 2027-04) |
| mediapipe | 1.1.1 | |
| numpy | 2.5.4 | |
| opencv-contrib-python | 5.0.0.93 | **not** `opencv-python` — MediaPipe 1.1.1 depends on the contrib build, and both provide `cv2` |
| pytest | 9.1.1 | |
| pytest-qt | 4.5.0 | |
| pyobjc-framework-* | 12.2.2 | Quartz / AVFoundation / ApplicationServices |
| pyinstaller | 6.22.3 | |

## What changed in the code

Migration was deliberately mechanical; the gesture engine was not touched.

- **39 files / 48 change kinds** rewritten by codemod:
  - `PyQt5.*` → `PySide6.*`
  - `pyqtSignal` → `Signal`, `pyqtSlot` → `Slot` (9 signal declarations)
  - `exec_()` → `exec()` (4 production call sites, 7 test doubles) — Qt 6 deprecates `exec_`
- `core/` pure logic and `platform_services/` were **untouched** — they have zero Qt imports
  (2342 + 1395 lines), so the classifier, action state machine, intent arbiter, DTW matcher,
  control session and platform contracts carry over unchanged.
- Only `gui/` (5279 lines) and `main.py` were in scope.

### One real semantic difference

`QWidget.pixmap()` returned `None` in PyQt5 but returns a **null `QPixmap` object** in PySide6,
so identity checks silently break:

```python
if self.preview.pixmap() is None:      # always False under PySide6
if not self.preview.pixmap():          # correct: works in both
```

Three call sites: `gui/main_window.py`, `gui/static_gesture_record_dialog.py`,
`gui/dynamic_gesture_record_dialog.py`.

Everything else this application uses — `Qt.AlignCenter`, `Qt.UserRole`, `Qt.WA_*` flat enum
aliases, `QtSvg`, `QtTest` — still works in PySide6 6.12 unchanged. `QDesktopWidget` (removed in
Qt 6) is not used.

## The PySide6 macOS teardown abort

**Symptom.** `pytest` prints its verdict and then the process dies with `SIGSEGV` (exit 139) or
`SIGABRT` (134). Tests themselves always passed — 366 green, every run.

**Root cause** (from an LLDB backtrace):

```
EXC_BAD_ACCESS (code=1, address=0x84)
QtCore`QObjectPrivate::setParent_helper(QObject*) + 72
```

During CPython interpreter finalization, shiboken frees the `QApplication` and its `QObject`
children in arbitrary GC order; a late reparent then touches freed memory. PyQt5's SIP
binding tears down in a safe order, which is why the identical suite exits 0 there.

**Scope.** 11 of 61 test files abort. It is not file-specific: each file alone can pass, and
even splitting the suite into halves still aborts. Production is unaffected — the real
application path (`app.exec_()` actually running an event loop) exited cleanly 8/8.

**What does NOT work** (all measured, all failed):

| Attempt | Result |
|---|---|
| Flush `DeferredDelete` in an autouse teardown fixture | 4/4 abort, fixture itself triggered it |
| Session-scoped autouse `QApplication` keepalive | 5/5 abort |
| `atexit` + `QApplication.shutdown(app)` (wrong call form — it is an instance method) | 5/5 abort |
| `pytest_sessionfinish` running one `app.exec_()` turn | 5/5 abort |
| `pytest_configure` holding a module-global reference | 21/21 abort |
| `app.shutdown()` in `pytest_sessionfinish` | aborts before the summary is even printed |

**What works.** `tests/conftest.py` records the verdict in `pytest_sessionfinish` and exits the
process in `pytest_unconfigure` — after the terminal summary has been written, before
interpreter finalization:

```python
def pytest_sessionfinish(session, exitstatus):
    global _EXIT_STATUS
    _EXIT_STATUS = int(exitstatus)

def pytest_unconfigure(config):
    import os
    try:
        sys.stdout.flush(); sys.stderr.flush()
    finally:
        os._exit(_EXIT_STATUS)
```

Validated properties:
- 5/5 runs print `366 passed` and exit **0**
- A deliberately failing test still exits **1** (the fix cannot mask failures)
- A passing single-file run still exits **0**

`os._exit` skips atexit handlers and buffer flushing — hence the explicit flushes. Nothing in
this project relies on atexit cleanup during tests.

## Build

Both platforms build from the single spec `Gesture Control.spec`; the spec is
`sys.platform`-aware and only wraps the bundle in `BUNDLE()` on macOS.

- macOS: `./scripts/build_macos_app.sh` → `dist/Gesture Control.app`, **365 MB**
  (was 428 MB on PyQt5). PySide6 is collected by PyInstaller's own hook with explicit
  `excludes` for Quick/QML/WebEngine/Charts/Pdf/etc., which drops the Qt payload from 348 MB
  to 77 MB.
- Windows: `pwsh ./scripts/build_windows.ps1` → `dist\Gesture Control\Gesture Control.exe`.
  PyInstaller cannot cross-compile; this must run on Windows.

Neither script signs with a Developer ID by default. `CODESIGN_IDENTITY` and `NOTARY_PROFILE`
env vars enable that path — required before distributing, because an ad-hoc signature changes
on every rebuild and macOS re-prompts for Camera and Accessibility each time.

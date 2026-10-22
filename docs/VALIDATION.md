# Validation Matrix

## Automated validation — macOS Apple Silicon host

Run with the project environment (Python 3.13 + PySide6 6.12):

```bash
env -u PYTHONPATH .venv/bin/python -m compileall -q core gui platform_services utils main.py tests
env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Latest verified result (repeated runs, exit code checked each time):

```text
474 passed
compileall passed
exit code 0
```

**A run is only green when it prints `474 passed` AND exits `0`.** The suite
report is followed by a deliberate `os._exit` in `tests/conftest.py`; see
[PYSIDE6-MIGRATION.md](PYSIDE6-MIGRATION.md) for why PySide6 requires it.

Verified by automated tests:

| Area | Status | Evidence |
|---|---|---|
| Core pointer lane | Passed | deterministic state machine replay, pinch/click/drag thresholds, tracking-loss release, and zone-rule tests |
| Timestamp safety | Passed | worker timestamp propagation, duplicate/regressed/non-finite timestamp fail-closed tests, and injected-clock replay tests |
| Dynamic shortcuts | Passed | neutral-delimited lifecycle, DTW gating, pointer-lane isolation, cooldown/rearm, and reset-boundary tests |
| Gesture arbitration | Passed | `IntentArbiter` tests keep pointer move/click/drag deterministic and suppress optional lanes during pointer ownership |
| MediaPipe VIDEO mode | Passed | strictly increasing worker timestamps and a real local `HandDetector` empty-frame inference test (MediaPipe 1.1.1, ~5 ms/frame on M-series) |
| Landmark contract and rendering | Passed | malformed, non-finite, or non-21-point output fails closed before classifier dispatch; rendering uses the shared 21-landmark topology rather than a worker-owned detector instance |
| Camera selection | Passed | selected stable ID is persisted and unavailable selections fail closed without legacy-camera fallback |
| macOS input and permissions | Passed | injected Quartz-facade move/click/drag/scroll/hotkey, permission, and AX-context tests |
| Settings/runtime configuration | Passed | staged Save/Cancel/Restore Defaults, live reload of pointer thresholds/smoothing/zone rules, normalized combo allowlist, dynamic templates, and hold-shortcut reconfiguration |
| Settings dialog modality | Passed | test doubles implement `exec()`; Qt 6 removed the `exec_` spelling |
| Legacy cleanup | Passed | retired LSTM/data-collection/YOLO/GestureEngine paths and obsolete configuration keys are absent from live runtime and Settings action surfaces |
| Windows contract layer | Passed on macOS | ctypes facade, INPUT-record construction, permission mapping, GetAsyncKeyState hold-shortcut polling, camera index probing, and factory fallback — all against fake bindings. **No Windows-native behaviour has been exercised.** |
| Factory routing | Passed | `create_platform_services("Darwin")` yields 13 supported actions; `("Windows")` composes the Windows adapter set when a native facade can be built and otherwise degrades to `Unavailable*` services instead of raising |

## macOS development bundle

```bash
./scripts/build_macos_app.sh
```

Verified on this host: builds from the shared spec, ad-hoc signs, bundles the
MediaPipe model at `Contents/Resources/models/hand_landmarker.task`, carries the
Camera/Accessibility usage strings and `LSMinimumSystemVersion`, and the produced
executable starts and stays in its event loop.

- Bundle size: **365 MB** (PyQt5 build was 428 MB)
- Bundle ID: `com.cyk.gesturecontroller.dev`
- Not notarized, not DMG-distributed, ad-hoc signature by default.
  Set `CODESIGN_IDENTITY` (and optionally `NOTARY_PROFILE`) for a stable TCC
  identity and a distributable build.

## Windows build

`pwsh ./scripts/build_windows.ps1` shares the same spec. **Not yet executed** —
PyInstaller cannot cross-compile, so it must run on a Windows 10/11 host.

## Windows adapter — implemented but unvalidated on hardware

The ctypes layer composes, injects the right INPUT records, and is covered by
111 fake-binding tests. The following are **known gaps**, not bugs to be
discovered later:

| Gap | Why it matters |
|---|---|
| DPI scaling | Injected coordinates are physical pixels; Qt screen geometry is logical pixels. At 125%/150% scaling the pointer will land off-target until a per-monitor mapping is added (needs an HWND). |
| SendInput acceptance / UIPI | An elevated foreground window silently ignores non-elevated injection. The controller reports `input_unavailable` instead of pretending it clicked, but this path has never run for real. |
| Hold-shortcut under IME | `GetAsyncKeyState` polling observes physical keys; behaviour under an active IME / non-US layout is unverified. |
| Camera enumeration | Index order, whether DSHOW initialises, probe duration on the UI thread, and whether probing during an open recording is treated as device takeover — all unmeasured on real hardware. |
| UI context | Window-class heuristics only (`Edit`/`Button`/`ComboBox`…). No UIA COM, so Chrome/Electron-hosted controls fall back to `generic` and their contextual filtering is inert. |

## Manual macOS acceptance — requires user permissions and hardware

| Check | Status | Notes |
|---|---|---|
| Camera permission prompt from Start | Pending | Requires a selected physical camera and explicit Start |
| Accessibility permission from explicit button | Pending | Requires user action in System Settings |
| Point, pinch click, pinch-hold drag, and stop release | Pending | Requires Accessibility permission |
| Scroll and configured shortcut | Pending | Requires Accessibility permission |
| AX context filtering across apps | Pending | Requires Accessibility permission and a foreground target app |
| Camera disconnect/reconnect | Pending | Requires physical/virtual camera testing |
| HUD across desktop, full-screen apps, and multiple Spaces | Pending | Requires visual macOS validation |
| Windows native validation | Not run | Do not claim Windows input injection, camera support, UI Automation, or parity until tested on Windows 10/11. Open items: physical-pixel vs Qt-logical DPI mapping, camera index probing while a live capture is held, UIPI blocking against elevated windows, and UI context quality from the Win32 window-class heuristic |

## Delivery limits

- The project is macOS-first. Windows now has a real ctypes adapter layer and a
  wired factory, but only fake-binding contract tests back it; real-host
  validation is outstanding.
- No signed, notarized, or DMG distribution has been produced.
- The retired action-recognizer/LSTM training-data collection, YOLO detector,
  legacy gesture engine, and direct Windows automation path are deliberately
  removed rather than merely disabled.

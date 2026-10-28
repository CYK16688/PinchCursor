# Validation Matrix

## Automated validation — macOS Apple Silicon host

Run with the project environment (Python 3.13 + PySide6 6.12):

```bash
env -u PYTHONPATH .venv/bin/python -m compileall -q core gui platform_services utils main.py tests
env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Latest automated result (2026-10-28, exit code checked):

```text
1353 passed in 115.01s
compileall passed
exit code 0
```

**A run is only green when all collected tests pass AND it exits `0`.** The suite
report is followed by a deliberate `os._exit` in `tests/conftest.py`; see
[PYSIDE6-MIGRATION.md](PYSIDE6-MIGRATION.md) for why PySide6 requires it.

### Product identity and cleanup

The canonical `gui/resources/pinchcursor.png` is used by the app and README,
with ICNS/ICO exports for platform packaging. `test_app_branding.py` verifies
transparent artwork, resource loading under a simulated PyInstaller extraction
root, every shipped ICO resolution, and a macOS `iconutil` decode of the ICNS.
The existing HiDPI tests verify logical sizing. UI screenshots were regenerated.

Old logo variants and the unused concept note were removed, together with seven
unreferenced helpers. The full regression suite above passed after these changes.
The Windows build script now points to `PinchCursor.spec` and the current output
name; no Windows executable or new macOS app bundle was built in this pass.
See [Branding](BRANDING.md) for the source, exports and generation record.

### Control workspace UI

The UI refactor applies the Intent context, heuristic evaluation and Journey
progressive-disclosure skills to the existing native desktop interface. The
main window now separates session controls, transaction feedback, settings
shortcuts and an action-first gesture guide. Control settings open on pointer
mapping, fine control and calibration; activation and advanced options have
separate tabs. [Design context and evaluation](ui/context-pinchcursor.md).

`test_control_workspace.py` verifies real Qt widgets at exactly 1000×660 and
1200×760 in Chinese and English, with ready and permission-blocked states. It
checks containment/overlap, truthful coalesced action results, keyboard Escape
that only stops, and routes to the intended settings tab.
`test_settings_control_hierarchy.py` verifies primary controls at 900×640 and
1040×720, translated accessible names and staged Save/Cancel persistence.
`test_summary_row_accessibility.py` checks native button role and press action.
`test_control_workspace.py` also verifies that candidate snapshots keep a pointer
HUD with no preview lock marker, and confirmation alone displays the lock.
`test_interaction_feedback.py` verifies discrete gesture phases and bounded
presentation of successes/failures without delaying the next interaction.

Screenshots in `docs/screenshots/` were regenerated from real widgets using fake
platform services. `main-pinch-confirmed.png` is explicitly labelled as a
synthetic gesture replay. No physical camera, native mouse event, manual
VoiceOver session or real-user usability study was used for this validation.

### Continuous-control regression evidence

The 2026-10-28 changes were tested locally without opening a physical camera or
posting native mouse events. The existing detector smoke test still runs real
MediaPipe inference on an empty image; it does not measure gesture accuracy.

| Area | Evidence |
|---|---|
| Full pointer lifecycle | `test_continuous_pointer_pipeline.py` passes landmarks through the real classifier, dynamics, session, arbiter, state machine, smoothing, coordinator and macOS controller, ending at a fake native facade. Click/double-click and drag/release cases run at 15/30/60 FPS. |
| Joint click/aim inference | `test_joint_pinch_pipeline.py` contains 114 complete-chain cases. The 24 moving target cases compare against an independently primed open-finger trajectory at the first contraction frame: sudden/gradual closing at 15/30/60 FPS, absolute center/left/right edge and relative mapping. All measured click coordinates match that synthetic reference (0.0 screen-point error; test tolerance 4 points). Stationary index curls of 20/30/40 camera pixels also preserve aim. |
| Candidate pointer continuity | Independent ordinary-pointer replays compare every native move at 15/30/60 FPS in absolute/relative modes. Gradual pre-threshold contraction, candidate admission and unconfirmed opening/cancellation do not rewind or interrupt the visible filter path. Confirmed clicks still use the onset target. Cancelled episodes allow safe open movement before click rearming, while lost/stale/gapped/incoherent frames emit no events. |
| Physical intent and recovery | One-frame closure, incomplete approach, fist transitions, missing/stale/gapped observations and incoherent palm jumps emit no click and permit a fresh deliberate click after genuine opening. Curl-only long holds do not drag or become clicks; whole-hand translation drags and releases once. Consecutive pinches rearm at 15/30/60 FPS. |
| Reconstruction boundaries | Camera dimension changes during a candidate or drag discard the episode and release exactly the owed button; absent trusted filter history reports cancellation. Both absolute and relative paths recover after opening. Numeric filter copies preserve bound clock services, including owners with locks. |
| Physical timing and FSM authority | Observer/FSM tests distinguish physical closure from confidence dwell, keep original opening time through release debounce, snap targets once, and prevent cancelled candidates or late labels from re-admitting a click. Zone filtering and native release remain enforced. |
| Continuous scrolling | Core scroll replays run at 15/30/60 FPS without an AX provider: stable pointing arms, thumb direction confirms, wheel ticks repeat at a bounded rate and raw pose exit stops immediately. Separate contextual-only tests retain target-identity invalidation. |
| Release recovery | `macos/test_release_recovery.py` and `test_input_guard.py` cover failed mouse-up, partially delivered clicks, repeated recovery, and retry while fresh frames continue. No new press is allowed while release remains pending. |
| Camera stalls and UI stalls | `test_input_guard.py` verifies a separate watchdog releases without another Qt callback, and rejects dispatch after a slow context lookup. A 250 ms frame lease with nominal 25 ms watchdog polling is a software timeout policy, not a hard real-time or OS-delivery guarantee. |
| Backpressure and restart | `test_frame_mailbox.py` verifies one pending latest-frame notification, discarding old worker notifications after restart, and safe retirement when capture blocks in `read()`. |
| Fine control | `test_dead_zone.py`, `test_cursor_smoothing.py` and `test_pointer_mapping.py` cover subpixel observations, 1–8 point corrections, modest synthetic noise, screen endpoints and overshoot prevention. These are algorithmic replays, not measured user performance. |
| Independent control owner | `test_control_engine.py` and `test_control_runtime.py` run the real decision chain without Qt event processing, including blocked accessibility/disk calls, stop during an in-flight decision, one-slot frame replacement and native failures. |
| Live window wiring | `test_control_runtime_window.py` calls the actual camera-to-runtime callback from a producer thread without pumping Qt, reaches the macOS adapter with a fake native sink, rejects old callbacks after restart, and verifies failed restart/owed release/blocked AX handling. |
| Native-call stalls | Stuck native down/up test doubles cannot block the GUI-side runtime stop. Input is revoked immediately; the serialized release finishes only after the stalled native call returns. |
| Auxiliary freshness and bounds | `test_async_services.py` checks bounded request/write queues, request-start cache age, spatial validity, invalidation generations, policy-disabled behavior, and deferred store disposal. |
| Native cursor reanchor | Fake Quartz and Win32 cursor readers retain fractional/negative coordinates and reject malformed positions; relative mapping does not read QCursor from the control thread. |

Manual acceptance remains required for actual camera lighting/distance, left and
right hands, small controls, Finder/text selection, drag-and-drop, scrolling,
multi-display geometry, camera unplugging and sustained-use fatigue. Record
task completion/error rates and motion-to-event latency against a physical
mouse. Episode ordering now records actual successful dispatch before resolving a
released pinch, and failed input cannot become a positive action label. That
software correction does not establish real-user label quality or qualify a
trained model for promotion.

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

The bundle observations below predate this runtime refactor; this batch verifies
source behavior and does not establish a newly packaged app's device behavior.

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

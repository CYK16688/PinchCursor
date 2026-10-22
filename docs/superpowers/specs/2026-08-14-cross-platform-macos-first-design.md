# Cross-Platform macOS-First Gesture Controller Design

> **Historical record (PyQt5 / Python 3.11 era).** This document describes the
> stack as it was on 2026-08-14. The project has since moved to PySide6 6.12
> and Python 3.13 — see [../PYSIDE6-MIGRATION.md](../PYSIDE6-MIGRATION.md).
> Python/Qt versions mentioned below are no longer current.

**Status:** Approved architecture; implementation specification pending final user review

**Goal:** Evolve the gesture controller into a local-development application that supports Windows 10/11 and Apple Silicon Macs running macOS 15+, with macOS usability as the primary product constraint and comparable cross-application, context-aware gesture control on both platforms.

## Product Constraints

- Target platforms are Windows 10/11 and macOS 15+ on Apple Silicon only.
- macOS interaction quality takes precedence over preservation of the existing Windows-oriented implementation or `settings.json` format.
- The first delivery target is local development and real-device validation, not signed/notarized external distribution.
- The shared hand-gesture engine must run without platform-native imports.
- Python 3.11 is the project runtime baseline.
- The first macOS release requires camera permission and Accessibility permission. Screen Recording permission is excluded unless a later feature needs screen capture or visual screen analysis.
- MediaPipe Hand Landmarker is the production hand landmark implementation for both platforms.

## Current-State Constraints

The current application couples platform-specific behavior to core orchestration:

- `core/system_controller.py` executes Windows-key shortcuts through PyAutoGUI.
- `utils/ui_context.py` imports `ctypes.windll` at module import time and queries Windows UI Automation.
- `gui/main_window.py` owns camera capture, MediaPipe invocation, gesture logic, UI updates, and system execution in one Qt timer callback.
- `utils/camera_utils.py` favors the Windows DirectShow backend.
- `core/yolo_detector.py` does not currently provide a reliable 21-hand-landmark implementation and is not part of the macOS-first MVP.

These constraints require an adapter boundary rather than conditional patches to the present modules.

## Supported User Experience

### Core behavior on both platforms

- Select and open a local camera.
- Detect one hand and obtain 21 landmarks through MediaPipe Hand Landmarker.
- Recognize the existing configured gesture vocabulary: point, pinch, pinch hold, open hand, fist, peace, thumb up/down, OK, rock, three, and call.
- Smooth the pointing position, lock the target while a pinch is forming, generate click and drag action intents, and display tracking/gesture feedback.
- Bind gestures and gesture sequences to supported actions and configurable keyboard shortcuts.
- Filter actions using a shared UI-category model: `text_input`, `clickable`, `slider`, `menu`, `scrollable`, and `generic`.

### macOS behavior

- Support cursor movement, left/right/middle click, double click, click modifiers, drag lifecycle, vertical/horizontal scrolling, media keys, and configured keyboard shortcuts through Quartz events.
- Resolve the accessibility element at the current cursor position with `AXUIElement`, normalize its role/subrole to the shared UI categories, and enforce configured gesture/action restrictions.
- Query and show Camera and Accessibility authorization states before enabling unavailable capabilities.
- Provide user-visible, accurate messages when a requested action is unavailable because permission is absent or macOS does not expose a compatible Accessibility action.
- Provide initial window/app operation implementations only where a documented native primitive is available; unsupported operations remain visible but disabled with an explanatory capability reason.

### Windows behavior

- Keep the same shared gestures, action intents, category rules, and configuration schema introduced by this migration.
- Reimplement system input and UI-context resolution behind the same interfaces with Windows APIs or a maintained Windows automation library.
- Do not depend on the legacy direct Windows imports from shared modules.

## Non-Goals for This Delivery

- Signed, notarized, or DMG-packaged macOS distribution.
- Intel Mac support.
- A second vision backend replacing MediaPipe.
- Claiming exact parity for every legacy Windows-only command before native behavior is verified.
- Automatic migration of legacy `settings.json` values.
- Any silent fallback that reports an action as executed when the platform adapter cannot execute it.

## Architecture

### Layering

```text
PyQt presentation
  └── Application coordinator
        ├── Shared gesture engine
        │     ├── MediaPipe landmark worker
        │     ├── gesture classifier
        │     ├── position tracker and smoother
        │     ├── action state machine
        │     └── combo detector
        └── platform services
              ├── platform capabilities and permissions
              ├── system input controller
              ├── UI context provider
              └── optional window/application controller
```

Dependencies only point downward. Shared engine modules cannot import PyObjC, Quartz, AppKit, `ctypes.windll`, `win32*`, or PyAutoGUI. Platform adapters may import native APIs but return only shared data classes and action results.

### Shared domain types

Create a `platform_services` package with import-safe interfaces and domain types:

- `PlatformCapabilities`: immutable snapshot of platform name, architecture, camera authorization, accessibility authorization, supported actions, and per-action unavailable reasons.
- `ActionRequest`: action identifier, target screen coordinates, scroll amount, optional hotkey, and optional gesture source.
- `ActionResult`: `executed`, `reason`, and optional normalized error identifier. `executed=False` must be propagated to the UI without pretending success.
- `UIContext`: a normalized category, native role string for diagnostics, and a confidence/source indicator.
- `SystemInputController`: executes `ActionRequest`, exposes supported actions, and releases a held drag safely.
- `UIContextProvider`: returns the context at a coordinate and decides whether an action/gesture is allowed under the shared policy.
- `PermissionProvider`: returns and requests/checks camera and accessibility authorization states without performing system input.
- `PlatformServices`: factory result that groups the above services for one selected host platform.

### Shared action vocabulary

Action identifiers remain string values to preserve the current configuration ergonomics, but their eligibility comes from `SystemInputController.supported_actions` rather than from a global Windows-biased hardcoded list. Shared policy separates:

- continuous pointer actions: `move_cursor`, `drag_start`, `drag`, `drag_end`, and scrolling;
- pointer actions: clicks and modifier clicks;
- keyboard/media actions: hotkeys and media control;
- optional platform actions: screenshot, application switching, window operations, lock screen, and file manager operations.

The settings UI only presents actions that are supported by the active platform or labels unsupported choices with a clear unavailable reason.

### macOS adapter

The macOS implementation uses Python 3.11 with PyObjC framework bindings:

- Quartz event services for cursor movement, button events, drag events, scroll events, and keyboard events.
- ApplicationServices Accessibility bindings for authorization checks and AX element inspection at the pointer position.
- AVFoundation or Qt-native camera authorization status when needed; the implementation must keep permission querying isolated from the vision worker.

`MacOSInputController` maps action identifiers to Quartz event sequences. It tracks pressed mouse buttons internally, always provides `release_drag()`, and releases a drag when the worker stops, the controller is disabled, permission is revoked, or the application closes.

`MacOSUIContextProvider` obtains the UI element at the pointer, walks a bounded parent chain when the leaf role is not useful, then maps AX roles/subroles to shared categories. If Accessibility permission is unavailable or lookup fails, it returns `generic` with an explicit diagnostic source and applies the safe default shared rules rather than crashing.

`MacOSPermissionProvider` distinguishes `granted`, `denied`, `not_determined`, and `unavailable`. It may request Accessibility trust only from an explicit user action in the UI; no permission dialog is triggered from the frame-processing loop.

### Windows adapter

`WindowsInputController`, `WindowsUIContextProvider`, and `WindowsPermissionProvider` implement the same interfaces. They encapsulate UI Automation, native event injection or a Windows-specific backend, and platform action handling. The refactor first protects macOS from Windows imports; the replacement Windows adapter is introduced as a dedicated phase and verified on Windows before claiming parity.

### MediaPipe vision pipeline

The application uses the official MediaPipe Tasks Python Hand Landmarker in `VIDEO` mode, not independent image-mode detection for every frame. The worker owns:

- camera capture;
- monotonically increasing millisecond timestamps;
- RGB conversion;
- `detect_for_video()` calls;
- conversion of the result to the existing 21-point landmark form;
- latest-result publication via a Qt signal or a lock-protected latest-frame container.

The Qt main thread never waits for inference. It receives the latest result, updates the preview/state labels, feeds the pure gesture engine, and dispatches only allowed action intents. The worker has bounded latest-frame behavior: when inference lags, stale queued frames are discarded rather than allowing unbounded input latency.

`LIVE_STREAM` with `detect_async()` is deferred. It becomes an optimization only if measurements on the target Apple Silicon Mac show that the `VIDEO` worker does not meet interaction responsiveness expectations.

### Configuration

Replace mutable shallow-copy defaults with a versioned configuration document. New configuration includes:

- `schema_version`;
- camera selection and resolution;
- MediaPipe confidence/tracking values;
- gesture bindings, enablement, and shortcut strings;
- smoothing and stabilization settings;
- combo rules;
- normalized context-category rules;
- optional zone rules.

A missing or obsolete configuration creates a clean versioned configuration; legacy migration is intentionally not required. Configuration validation rejects unknown action identifiers and action bindings unsupported by the active platform only at runtime presentation time; it does not delete the user’s choice so a configuration may remain portable between platforms.

## Main Runtime Data Flow

1. The application creates `PlatformServices` after the Qt app is initialized.
2. The UI obtains a capability snapshot and displays permission/device readiness.
3. The user explicitly grants/rechecks permissions and starts gesture control.
4. The landmark worker opens the selected camera and processes latest frames through MediaPipe VIDEO mode.
5. The worker publishes frame, landmarks, timestamp, and detection metadata.
6. The coordinator runs the classifier, tracker, smoother, combo detector, and action state machine using only shared logic.
7. The coordinator resolves the action binding and asks the context provider whether the gesture/action is allowed.
8. If allowed and supported, it creates `ActionRequest` and calls the platform input controller.
9. The UI presents success/failure/capability feedback; it never assumes action execution.
10. Stop, permission loss, camera failure, or app exit invokes `release_drag()`, stops the worker, closes the camera, and disposes the MediaPipe model.

## Error Handling and Safety

- Camera failure remains recoverable: show the device error, stop control safely, and retain settings access.
- Permission denial does not repeatedly prompt. Show one actionable status and a user-triggered recheck/open-settings control.
- A platform action cannot be called if it is absent from the capability snapshot.
- `release_drag()` executes during all shutdown/failure paths and is idempotent.
- UI-context lookup failures degrade to the documented generic category; they never cause event dispatch to crash.
- Worker exceptions are delivered to the UI through a typed error signal and stop the worker cleanly.
- All native API calls remain behind adapters so they can be replaced with test doubles.

## Testing and Validation

### Unit tests, runnable on macOS and Windows without camera/native permissions

- Gesture classifier stabilization and pinch transitions.
- Action state machine click, lock, timeout, drag, and release paths.
- Combo detector timing and cooldown paths using injectable clock/time abstraction where required.
- Shared context policy for each category/action/gesture.
- Configuration schema validation and default creation.
- Platform factory selection and capability gating using fake platform services.
- Coordinator behavior with fake landmark stream, fake input controller, and fake context provider.

### macOS adapter tests

- Role/subrole mapping uses fixture data and parent fallback without calling real AX APIs.
- Quartz event construction is tested by injecting a small event-posting facade, not by moving the real cursor in automated tests.
- Permission state conversion is tested with mocked native calls.
- Manual local verification checks Camera and Accessibility onboarding, pointer movement, click, drag release on stop, scroll, shortcuts, context blocking on a text input/button/scroll view, unsupported action feedback, and application shutdown.

### Windows adapter tests

- The same adapter contract suite runs against fake Windows native facades.
- Manual Windows validation occurs on a real Windows 10/11 host before Windows parity is reported.

### Performance acceptance checks on the target Apple Silicon Mac

- Use a 640×480 camera baseline with one hand.
- Log capture timestamp, inference completion timestamp, action dispatch timestamp, and dropped frame count only in development diagnostics.
- Verify that the UI remains responsive during continuous hand tracking and that queue growth is bounded.
- Choose `LIVE_STREAM` only with measured evidence that it improves the input-to-action behavior without destabilizing result ordering.

## Delivery Phases

1. Add Python 3.11 project metadata, reproducible macOS arm64 virtual environment instructions, unit-test foundation, and versioned configuration.
2. Extract pure platform interfaces and move action/context policies out of Windows-specific imports; retain fake services for tests.
3. Implement macOS permission state, Quartz input controller, drag-safety lifecycle, and capability-driven settings presentation.
4. Implement macOS AX UI-context resolution and shared category policy; manually validate cross-application filtering.
5. Replace timer-bound camera inference with the MediaPipe VIDEO worker pipeline and validate responsiveness on the local Apple Silicon Mac.
6. Add/replace the Windows adapters behind the same interfaces and validate on Windows 10/11.
7. Prepare packaging/signing/notarization only after local validation meets the product bar.

## External Technical Basis

MediaPipe Tasks Python documents desktop support including macOS and Python 3.9+, while the current package metadata includes an arm64 macOS wheel.[1][2] The Hand Landmarker guide describes `VIDEO` and `LIVE_STREAM` modes and explains that their tracking avoids palm detection for every frame, motivating the VIDEO-mode desktop worker.[7] PyObjC ApplicationServices and Quartz package metadata requires Python 3.10+, compatible with the Python 3.11 baseline.[5][6]

## Sources

[1] https://ai.google.dev/edge/mediapipe/solutions/setup_python — MediaPipe Python setup guide
[2] https://pypi.org/pypi/mediapipe/json — MediaPipe PyPI release metadata
[5] https://pypi.org/pypi/pyobjc-framework-ApplicationServices/json — PyObjC ApplicationServices package metadata
[6] https://pypi.org/pypi/pyobjc-framework-Quartz/json — PyObjC Quartz package metadata
[7] https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python — MediaPipe Hand Landmarker Python guide

# Cross-Platform macOS-First Gesture Controller Implementation Plan

> **Historical record (PyQt5 / Python 3.11 era).** This document describes the
> stack as it was on 2026-08-14. The project has since moved to PySide6 6.12
> and Python 3.13 — see [../PYSIDE6-MIGRATION.md](../PYSIDE6-MIGRATION.md).
> Python/Qt versions mentioned below are no longer current.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS-first, testable platform-adapter architecture for the gesture controller, with a functioning local Apple Silicon macOS development path and an interface-compatible Windows path.

**Architecture:** The existing classifier, tracker, smoother, action state machine, and combo detector remain pure shared logic. A new `platform_services` boundary owns permission state, input injection, UI-context discovery, action capabilities, and platform selection. A MediaPipe VIDEO-mode Qt worker owns capture/inference while the main thread coordinates gesture intent, UI feedback, and platform dispatch.

**Tech Stack:** Python 3.11; PyQt5; OpenCV; MediaPipe Tasks Hand Landmarker; PyObjC ApplicationServices/Quartz on macOS; pytest; mocked native facades for unit tests.

**Spec:** `docs/superpowers/specs/2026-08-14-cross-platform-macos-first-design.md`

## Global Constraints

- Support Windows 10/11 and Apple Silicon macOS 15+; macOS UX is the primary constraint.
- Use Python 3.11 as the project runtime baseline.
- Shared gesture modules must not import PyObjC, Quartz, AppKit, `ctypes.windll`, `win32*`, or PyAutoGUI.
- Do not migrate legacy `settings.json`; create a versioned configuration document.
- First macOS delivery is local development validation only; no signing, notarization, or DMG.
- Native permission prompts are only initiated from an explicit UI action, never from the frame loop.
- Every new production behavior is implemented test-first and checked with pytest.
- There is no Git repository in the current directory, so no worktree or commits are possible until repository metadata is supplied.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Python 3.11 build/dependency/test configuration, optional macOS dependency group. |
| `requirements.txt` | Minimal runtime dependency compatibility for direct local setup. |
| `platform_services/contracts.py` | Shared immutable data objects and abstract protocols. |
| `platform_services/policy.py` | Platform-independent category/action/gesture filter rules. |
| `platform_services/factory.py` | Host-platform selection and service assembly. |
| `platform_services/null.py` | Safe unavailable service implementations for unsupported or uninstalled native backends. |
| `platform_services/macos/*.py` | PyObjC permission, Quartz input, AX context, and service composition. |
| `platform_services/windows/*.py` | Interface-compatible Windows services, initially safe wrappers around existing functionality. |
| `core/gesture_engine.py` | Orchestrates shared gesture components and produces action intents without native imports. |
| `core/mediapipe_worker.py` | Qt worker for camera capture and MediaPipe VIDEO inference. |
| `utils/config_manager.py` | Versioned config, deep-copy defaults, and platform-aware binding validation. |
| `gui/main_window.py` | Thin presentation/coordinator consuming worker and platform services. |
| `gui/settings_dialog.py`, `gui/gesture_card.py` | Capability-aware action presentation and permission status/actions. |
| `tests/` | Unit and contract tests that do not move the actual pointer or require camera/accessibility permissions. |
| `docs/DEVELOPMENT.md` | Apple Silicon macOS local setup and manual validation checklist. |

## Task 1: Establish Python 3.11 project setup and test foundation

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_project_runtime.py`
- Create: `docs/DEVELOPMENT.md`
- Modify: `requirements.txt`

**Interfaces:**
- Produces a reproducible Python 3.11 test command: `python3.11 -m pytest`.
- Produces `tests/conftest.py` helpers that isolate project imports and prevent native-event execution.

- [ ] **Step 1: Write a failing runtime-baseline test**

```python
# tests/test_project_runtime.py
import sys


def test_project_requires_python_311_or_newer():
    assert sys.version_info >= (3, 11)
```

- [ ] **Step 2: Run the test with the intended Python 3.11 interpreter**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_project_runtime.py -v
```

Expected: FAIL because pytest is not declared/configured for this source tree.

- [ ] **Step 3: Add project metadata and test dependencies**

Create `pyproject.toml` with:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "gesture-controller"
version = "0.1.0"
requires-python = ">=3.11,<3.12"
dependencies = [
  "mediapipe>=0.10.0",
  "numpy>=1.24.0",
  "opencv-python>=4.8.0",
  "PyQt5>=5.15.0",
]

[project.optional-dependencies]
macos = [
  "pyobjc-framework-ApplicationServices>=12.2.2",
  "pyobjc-framework-Quartz>=12.2.2",
]
test = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Keep `requirements.txt` as a simple compatibility install list, move `pyautogui` to a Windows-only comment or optional requirements file after Task 6 has migrated the Windows controller.

- [ ] **Step 4: Add safe pytest setup**

Create `tests/conftest.py` that adds the repository root to `sys.path`, and add an empty `tests/__init__.py`.

- [ ] **Step 5: Re-run the baseline test**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_project_runtime.py -v
```

Expected: PASS.

- [ ] **Step 6: Document local Apple Silicon setup and manual prerequisites**

Create `docs/DEVELOPMENT.md` with exact commands to:

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[macos,test]"
python -m pytest
```

Include a manual checklist: arm64 verification, camera permission, Accessibility permission, run command, and expected local-only status. Do not claim a package/notarization workflow exists.

- [ ] **Step 7: Run the initial full suite**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest -q
```

Expected: the runtime baseline test passes.

## Task 2: Define platform contracts and shared filtering policy

**Files:**
- Create: `platform_services/__init__.py`
- Create: `platform_services/contracts.py`
- Create: `platform_services/policy.py`
- Create: `platform_services/null.py`
- Create: `tests/test_platform_contracts.py`
- Create: `tests/test_context_policy.py`

**Interfaces:**
- Produces `AuthorizationState`, `ActionRequest`, `ActionResult`, `UIContext`, `PlatformCapabilities`, and `PlatformServices` from `platform_services.contracts`.
- Produces `ContextPolicy.is_gesture_allowed(context, gesture)` and `ContextPolicy.is_action_allowed(context, action)` from `platform_services.policy`.
- Produces safe unavailable services from `platform_services.null`.

- [ ] **Step 1: Write a failing shared-policy test**

```python
# tests/test_context_policy.py
from platform_services.contracts import UIContext
from platform_services.policy import ContextPolicy


def test_text_input_blocks_drag_but_allows_point_and_pinch():
    policy = ContextPolicy.default()
    context = UIContext(category="text_input", native_role="AXTextField", source="test")

    assert policy.is_gesture_allowed(context, "point")
    assert policy.is_gesture_allowed(context, "pinch")
    assert not policy.is_gesture_allowed(context, "pinch_hold")
    assert not policy.is_action_allowed(context, "drag")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_context_policy.py::test_text_input_blocks_drag_but_allows_point_and_pinch -v
```

Expected: FAIL with missing `platform_services` module.

- [ ] **Step 3: Implement minimum contracts and policy**

Use frozen dataclasses and `typing.Protocol`/`abc.ABC` to define these exact contracts:

```python
@dataclass(frozen=True)
class ActionRequest:
    action: str
    x: int | None = None
    y: int | None = None
    scroll_amount: int = 0
    hotkey: str = ""
    gesture: str = "none"

@dataclass(frozen=True)
class ActionResult:
    executed: bool
    reason: str = ""
    error_code: str = ""

@dataclass(frozen=True)
class UIContext:
    category: str
    native_role: str = ""
    source: str = ""
```

Implement the existing shared category restrictions in `ContextPolicy.default()` without importing the legacy Windows context module.

- [ ] **Step 4: Verify GREEN and add unavailable-result test**

Run the specific policy test, then add and run:

```python
# tests/test_platform_contracts.py
from platform_services.null import UnavailableInputController
from platform_services.contracts import ActionRequest


def test_unavailable_controller_never_reports_execution():
    result = UnavailableInputController("Not supported").execute(ActionRequest(action="move_cursor"))
    assert result.executed is False
    assert result.reason == "Not supported"
```

- [ ] **Step 5: Run all platform contract tests**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_platform_contracts.py tests/test_context_policy.py -q
```

Expected: PASS.

## Task 3: Add macOS capability, permission, Quartz input, and drag-safety services

**Files:**
- Create: `platform_services/macos/__init__.py`
- Create: `platform_services/macos/native.py`
- Create: `platform_services/macos/permissions.py`
- Create: `platform_services/macos/input_controller.py`
- Create: `tests/macos/test_permissions.py`
- Create: `tests/macos/test_input_controller.py`

**Interfaces:**
- Produces `MacOSPermissionProvider` with `snapshot()` and explicit `request_accessibility_prompt()`.
- Produces `MacOSInputController(native)` with `execute(ActionRequest)`, `supported_actions`, and idempotent `release_drag()`.
- `native` is an injected facade exposing Quartz/Accessibility calls, enabling tests without moving the user’s pointer.

- [ ] **Step 1: Write a failing drag-release test**

```python
# tests/macos/test_input_controller.py
from platform_services.contracts import ActionRequest
from platform_services.macos.input_controller import MacOSInputController


class RecordingNative:
    def __init__(self):
        self.events = []

    def post_mouse(self, event_type, x, y, button):
        self.events.append((event_type, x, y, button))


def test_release_drag_posts_mouse_up_once_after_drag_start():
    native = RecordingNative()
    controller = MacOSInputController(native)

    controller.execute(ActionRequest(action="drag_start", x=30, y=40))
    first = controller.release_drag()
    second = controller.release_drag()

    assert first.executed is True
    assert second.executed is True
    assert native.events == [
        ("left_down", 30, 40, "left"),
        ("left_up", 30, 40, "left"),
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/macos/test_input_controller.py::test_release_drag_posts_mouse_up_once_after_drag_start -v
```

Expected: FAIL because macOS controller is absent.

- [ ] **Step 3: Implement facade and minimal drag lifecycle**

`native.py` must import PyObjC lazily inside `create_native_facade()` so importing platform contracts works on Windows. Implement normalized methods for post mouse, scroll, keyboard, cursor position, accessibility trust, and accessibility prompt. Implement only the action mappings covered by tests first: pointer move, click, drag start/move/end, scrolling, hotkey. Unsupported actions return `ActionResult(executed=False, reason=...)`.

- [ ] **Step 4: Verify GREEN**

Run the drag-release test. Expected: PASS.

- [ ] **Step 5: Write and verify a permission-state test**

```python
# tests/macos/test_permissions.py
from platform_services.macos.permissions import MacOSPermissionProvider


class PermissionNative:
    def accessibility_trusted(self):
        return False

    def camera_authorization(self):
        return "not_determined"


def test_permission_snapshot_reports_independent_camera_and_accessibility_states():
    snapshot = MacOSPermissionProvider(PermissionNative()).snapshot()

    assert snapshot.camera == "not_determined"
    assert snapshot.accessibility == "denied"
```

First run RED, then implement conversion logic and run GREEN.

- [ ] **Step 6: Expand input tests one action at a time**

Add one RED→GREEN cycle each for:

```python
ActionRequest(action="move_cursor", x=12, y=24)
ActionRequest(action="left_click", x=12, y=24)
ActionRequest(action="scroll_down", x=12, y=24, scroll_amount=3)
ActionRequest(action="custom_hotkey", hotkey="cmd+space")
ActionRequest(action="lock_screen")
```

Assert native call sequences for supported actions. Assert `executed is False` and a nonempty reason for unimplemented platform actions such as `lock_screen`.

- [ ] **Step 7: Run macOS adapter tests**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/macos -q
```

Expected: PASS without PyObjC being installed because all tests use injected facades.

## Task 4: Implement AX UI-context normalization and capability factory

**Files:**
- Create: `platform_services/macos/ui_context.py`
- Create: `platform_services/factory.py`
- Create: `tests/macos/test_ui_context.py`
- Create: `tests/test_platform_factory.py`

**Interfaces:**
- Produces `MacOSUIContextProvider(native, policy)` with `get_context(x, y)`, `is_gesture_allowed(gesture, x, y)`, and `is_action_allowed(action, x, y)`.
- Produces `create_platform_services(system_name=None)` that returns safe services and a `PlatformCapabilities` snapshot.

- [ ] **Step 1: Write a failing AX role mapping test**

```python
# tests/macos/test_ui_context.py
from platform_services.macos.ui_context import MacOSUIContextProvider
from platform_services.policy import ContextPolicy


class AccessibilityNative:
    def element_at_position(self, x, y):
        return {"role": "AXTextField", "subrole": "", "parent": None}


def test_ax_text_field_maps_to_text_input():
    provider = MacOSUIContextProvider(AccessibilityNative(), ContextPolicy.default())

    context = provider.get_context(15, 20)

    assert context.category == "text_input"
    assert context.native_role == "AXTextField"
```

- [ ] **Step 2: Verify RED**

Run the specific test. Expected: FAIL because the provider is absent.

- [ ] **Step 3: Implement role map and parent fallback**

Implement role mappings for `AXTextField`, `AXTextArea`, `AXButton`, `AXCheckBox`, `AXRadioButton`, `AXSlider`, `AXScrollBar`, `AXMenu`, `AXMenuItem`, `AXList`, `AXOutline`, `AXWebArea`, and unknown roles. Walk at most four parent nodes when the leaf maps to `generic`. Native failures must return `UIContext(category="generic", source="accessibility_unavailable")`.

- [ ] **Step 4: Verify GREEN and add fallback tests**

Add tests for an unknown leaf whose parent is `AXScrollArea`, and for a native lookup exception. Run all `tests/macos/test_ui_context.py` tests.

- [ ] **Step 5: Write a failing macOS factory test**

```python
# tests/test_platform_factory.py
from platform_services.factory import create_platform_services


def test_factory_returns_macos_services_for_darwin():
    services = create_platform_services(system_name="Darwin")

    assert services.capabilities.platform == "macos"
    assert "move_cursor" in services.capabilities.supported_actions
```

- [ ] **Step 6: Verify RED then implement the factory**

The macOS factory must use native services only when native dependencies can initialize; otherwise return unavailable services with `platform="macos"` and nonempty capability reasons. The non-macOS factory must not import macOS modules.

- [ ] **Step 7: Run factory/context tests**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_platform_factory.py tests/macos/test_ui_context.py -q
```

Expected: PASS.

## Task 5: Extract the pure gesture coordinator

**Files:**
- Create: `core/gesture_engine.py`
- Create: `tests/test_gesture_engine.py`
- Modify: `core/action_state_machine.py`
- Modify: `core/combo_detector.py`

**Interfaces:**
- Produces `GestureEngine(config, clock=time.monotonic)` with `process(landmarks, frame_size, screen_size)` returning a pure `GestureFrameResult` containing gesture, display position, optional `ActionRequest`, lock state, and status.
- Uses injected clock in stateful components where time-dependent behavior is tested.
- Does not import PyQt, OpenCV, PyObjC, Windows APIs, or PyAutoGUI.

- [ ] **Step 1: Write a failing engine test for a pointer action intent**

```python
# tests/test_gesture_engine.py
from core.gesture_engine import GestureEngine


def test_point_gesture_produces_move_cursor_request():
    engine = GestureEngine.default_for_test()
    result = engine.process_landmarks(
        landmarks=engine.test_landmarks_for("point"),
        frame_size=(640, 480),
        screen_size=(1920, 1080),
    )

    assert result.gesture == "point"
    assert result.action_request.action == "move_cursor"
```

- [ ] **Step 2: Verify RED**

Run the specific test. Expected: FAIL because `GestureEngine` does not exist.

- [ ] **Step 3: Implement minimal pure coordinator**

Move gesture classification, tracker/smoother coordinate mapping, combo detection, and action-state handling out of `MainWindow.execute_action()`. Maintain existing behavior but return `ActionRequest` rather than calling a controller. Keep image drawing and Qt UI updates out of this module. Extract or add deterministic test landmark fixtures rather than relying on actual camera data.

- [ ] **Step 4: Verify GREEN**

Run the point-intent test. Expected: PASS.

- [ ] **Step 5: Add behavior tests in separate RED→GREEN cycles**

Add tests for:

- no landmarks produces no action request;
- a disabled gesture produces no action request;
- a configured non-core gesture produces its configured action once;
- a context-denied action is not dispatched by the coordinator integration seam;
- pinch locking and release produces one `left_click` request at the locked location;
- drag starts after the configured duration/movement and always yields `drag_end` when pinch ends.

Inject clock values rather than sleeping in tests.

- [ ] **Step 6: Run all pure-core tests**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_gesture_engine.py tests/test_context_policy.py -q
```

Expected: PASS.

## Task 6: Version configuration and replace Windows-coupled execution usage

**Files:**
- Modify: `utils/config_manager.py`
- Modify: `core/system_controller.py`
- Modify: `utils/ui_context.py`
- Create: `platform_services/windows/__init__.py`
- Create: `platform_services/windows/input_controller.py`
- Create: `platform_services/windows/ui_context.py`
- Create: `tests/test_config_manager.py`
- Create: `tests/windows/test_windows_imports.py`

**Interfaces:**
- `ConfigManager` exposes validated versioned settings and no shallow mutation of global defaults.
- Legacy `SystemController` becomes a compatibility facade or is removed from the main execution path; it cannot be imported by shared engine code.
- Windows-specific modules are imported only by the Windows platform factory.

- [ ] **Step 1: Write a failing config-version test**

```python
# tests/test_config_manager.py
from utils.config_manager import CURRENT_SCHEMA_VERSION, ConfigManager


def test_missing_config_creates_current_versioned_defaults(tmp_path):
    manager = ConfigManager(config_path=tmp_path / "settings.json")

    assert manager.get("schema_version") == CURRENT_SCHEMA_VERSION
    assert manager.get("gestures", "point")["action"] == "move_cursor"
```

- [ ] **Step 2: Verify RED**

Run the specific test. Expected: FAIL because constructor injection/schema version are absent.

- [ ] **Step 3: Implement versioned, deep-copied configuration**

Use `copy.deepcopy(DEFAULT_CONFIG)`. Add `CURRENT_SCHEMA_VERSION = 1`, `schema_version`, injectable `config_path`, deep recursive merging, and defensive handling for obsolete/malformed files. Preserve stored unsupported action strings; UI capability filtering happens at presentation time.

- [ ] **Step 4: Verify GREEN and add invalid-action validation test**

Add a test that unknown action identifiers resolve to `none` during execution lookup without deleting the configuration entry. Run `tests/test_config_manager.py`.

- [ ] **Step 5: Write a failing cross-platform import test**

```python
# tests/windows/test_windows_imports.py
import importlib
import sys


def test_shared_platform_modules_import_without_windows_native_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctypes", __import__("ctypes"))
    importlib.import_module("platform_services.contracts")
    importlib.import_module("platform_services.policy")
    importlib.import_module("core.gesture_engine")
```

- [ ] **Step 6: Verify RED where legacy coupling remains, then move native imports**

Ensure only `platform_services/windows/*` imports `windll`, comtypes, win32 APIs, or PyAutoGUI. `utils/ui_context.py` must become a compatibility forwarding module or be replaced entirely by the Windows adapter. Do not execute input in this test.

- [ ] **Step 7: Run configuration and import tests**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_config_manager.py tests/windows/test_windows_imports.py -q
```

Expected: PASS on macOS.

## Task 7: Introduce the MediaPipe VIDEO worker and integrate the macOS-first UI

**Files:**
- Create: `core/mediapipe_worker.py`
- Create: `tests/test_mediapipe_worker.py`
- Modify: `core/hand_detector.py`
- Modify: `gui/main_window.py`
- Modify: `gui/settings_dialog.py`
- Modify: `gui/gesture_card.py`
- Modify: `utils/camera_utils.py`
- Create: `tests/test_main_window_coordinator.py`

**Interfaces:**
- `MediaPipeVideoWorker` owns capture and MediaPipe `detect_for_video()` in a Qt worker thread and emits latest `LandmarkFrame` results and typed errors.
- `MainWindow` receives result signals, asks platform services for capability/context permission, and passes `ActionRequest` to the platform input controller.
- UI exposes camera/accessibility readiness and explicit accessibility-prompt/recheck controls.

- [ ] **Step 1: Write a failing worker timestamp test**

```python
# tests/test_mediapipe_worker.py
from core.mediapipe_worker import MediaPipeVideoWorker


def test_video_worker_uses_strictly_increasing_millisecond_timestamps():
    worker = MediaPipeVideoWorker.for_test()

    assert worker.next_timestamp_ms(1000.0) < worker.next_timestamp_ms(1000.0)
```

- [ ] **Step 2: Verify RED**

Run the test. Expected: FAIL because the worker is absent.

- [ ] **Step 3: Implement minimum worker and test seam**

Create a worker with injected capture factory, detector facade, and monotonic clock. The detector facade exposes `detect_for_video(rgb_frame, timestamp_ms)`. The test-only constructor must not import Qt camera APIs or open a device. Ensure timestamps strictly increase even if a test clock returns the same value.

- [ ] **Step 4: Verify GREEN and add bounded-latest-frame test**

Add a test proving that a pending result is replaced by a newer result rather than accumulating unbounded queue items. Run worker tests.

- [ ] **Step 5: Convert HandDetector to VIDEO mode**

Write a new failing unit test around a fake MediaPipe facade that asserts `running_mode="VIDEO"` and calls `detect_for_video`. Implement `HandDetector.detect_for_video(frame_rgb, timestamp_ms)`. Keep the legacy `detect()` temporarily only as a compatibility wrapper for tests/dialogs, but do not invoke it from the worker path.

- [ ] **Step 6: Integrate MainWindow one boundary at a time**

Refactor constructor dependencies so tests can instantiate a coordinator with fake platform services and fake worker. Remove direct construction of `SystemController` and direct calls to `ui_context`. In result handling:

1. Update preview and gesture status.
2. Ask context provider about gesture/action permission.
3. Dispatch the engine result through `input_controller.execute()` only when capabilities allow it.
4. Show `ActionResult.reason` in status text when execution is denied/unavailable.
5. On stop/close/worker-error, invoke `input_controller.release_drag()` before releasing resources.

- [ ] **Step 7: Add a failing coordinator safety test, then make it pass**

```python
# tests/test_main_window_coordinator.py

def test_stopping_control_releases_active_drag(fake_window):
    fake_window.input_controller.dragging = True

    fake_window.stop_control()

    assert fake_window.input_controller.release_drag_calls == 1
```

The test must avoid constructing a visible Qt window when the platform lacks display access; use a small extracted coordinator if required.

- [ ] **Step 8: Make settings capability-aware**

Add tests for an action choice marked unsupported. Update gesture cards/settings to show platform-supported actions first and label unavailable entries with reasons. Add a permission panel with: current Camera state, current Accessibility state, Recheck, and an explicit request/open-settings action. No UI handler may prompt automatically during startup or frame processing.

- [ ] **Step 9: Make camera backend portable**

Change `utils/camera_utils.detect_cameras()` to select `CAP_DSHOW` only on Windows; use a macOS-safe backend/default otherwise. Add a pure helper test for backend selection by injected platform name.

- [ ] **Step 10: Run automated suite**

Run:

```bash
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m pytest -q
/Users/cyk/.hermes/hermes-agent/venv/bin/python3 -m compileall -q core gui platform_services utils tests
```

Expected: all tests pass and syntax compilation exits 0.

- [ ] **Step 11: Perform manual local Apple Silicon verification**

With the Python 3.11 project venv and macOS optional dependencies installed:

```bash
python main.py
```

Manually verify and record each result:

1. app launches and shows readiness without native import crash;
2. Camera and Accessibility status are visible;
3. permission prompt is initiated only by an explicit button;
4. selected camera opens and VIDEO-mode landmarks render;
5. point moves cursor after Accessibility is granted;
6. pinch clicks and pinch-hold drag ends when Stop is pressed;
7. scroll and a configured `cmd` shortcut operate;
8. AX context blocks drag over a text field but permits point/pinch;
9. denied permission and unsupported actions show clear non-success feedback;
10. closing the app releases camera, MediaPipe, and any held drag.

If an item fails, stop the phase, capture the exact symptom and logs, write a failing regression test when practical, and use systematic debugging before continuing.

## Task 8: Windows adapter parity and final local validation report

**Files:**
- Modify: `platform_services/windows/input_controller.py`
- Modify: `platform_services/windows/ui_context.py`
- Create: `tests/windows/test_input_controller.py`
- Create: `tests/windows/test_ui_context.py`
- Create: `docs/VALIDATION.md`

**Interfaces:**
- Windows input/context providers satisfy the same contract tests as macOS providers.
- `docs/VALIDATION.md` is an evidence-based matrix that distinguishes automated test status from unperformed manual macOS/Windows checks.

- [ ] **Step 1: Write a failing Windows input contract test**

```python
# tests/windows/test_input_controller.py
from platform_services.contracts import ActionRequest
from platform_services.windows.input_controller import WindowsInputController


def test_windows_controller_reports_unsupported_action_without_success():
    result = WindowsInputController.for_test().execute(ActionRequest(action="not_real"))

    assert result.executed is False
    assert result.reason
```

- [ ] **Step 2: Verify RED then implement the safe Windows adapter**

Windows-only native imports must remain lazy/isolated. Port basic pointer/hotkey/drag handling behind an injectable native facade. Do not assert real OS input behavior in automated tests.

- [ ] **Step 3: Add context category contract tests and run Windows tests**

Test Windows UIA role identifiers map to the same categories as AX roles. Run under a Windows 10/11 host:

```bash
python -m pytest tests/windows -q
```

- [ ] **Step 4: Run final automated checks on the local macOS host**

Run:

```bash
python -m pytest -q
python -m compileall -q core gui platform_services utils tests
```

Document the exact output and interpreter version in `docs/VALIDATION.md`.

- [ ] **Step 5: Complete manual validation matrix without overclaiming**

Record macOS manual test outcomes from Task 7. Record Windows checks as `not run` until performed on a real Windows 10/11 host; do not infer them from macOS tests.

- [ ] **Step 6: Re-read the specification and check requirement coverage**

Verify each section of `docs/superpowers/specs/2026-08-14-cross-platform-macos-first-design.md` against implemented files and validation evidence. Add omissions to `docs/VALIDATION.md` as explicit remaining work rather than claiming completion.

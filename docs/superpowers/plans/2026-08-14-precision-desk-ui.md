# Precision Desk UI and macOS Device Foundation Implementation Plan

> **Historical record (PyQt5 / Python 3.11 era).** This document describes the
> stack as it was on 2026-08-14. The project has since moved to PySide6 6.12
> and Python 3.13 — see [../PYSIDE6-MIGRATION.md](../PYSIDE6-MIGRATION.md).
> Python/Qt versions mentioned below are no longer current.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a macOS-first, stable app identity, selectable camera foundation, configurable control-session activation, Precision Desk UI, and pointer-adjacent feedback HUD while preserving MediaPipe 1.0.0 and the current Python 3.11 runtime.

**Architecture:** A macOS development `.app` owns TCC identity and camera-purpose declarations. A platform CameraService exposes stable device objects and opens the user-selected device before MediaPipe VIDEO inference. A pure ControlSession state machine gates pointer action intents. PyQt presentation is rebuilt around a two-column operational console and sidebar settings, while a mouse-transparent HUD renders state feedback near the screen pointer.

**Tech Stack:** Python 3.11; MediaPipe 1.0.0; PyQt5; OpenCV for interim selected-device capture; PyObjC ApplicationServices/AVFoundation/Quartz; PyInstaller; pytest; ad-hoc code signing for local development only.

**Spec:** `docs/superpowers/specs/2026-08-14-precision-desk-ui-design.md`

## Global Constraints

- Keep Python 3.11 as the product runtime; do not change to Python 3.14.
- Keep MediaPipe at the current verified 1.0.0 release unless a later explicit upgrade is validated.
- Target Apple Silicon macOS 15+; local development `.app` only in this milestone.
- Shared gesture/session modules must not import PyQt, AppKit, Quartz, AVFoundation, Windows APIs, or PyAutoGUI.
- Camera and Accessibility prompts occur only after explicit user actions.
- Preserve a testable adapter boundary: all AVFoundation, Quartz, and AppKit calls use injectable native facades.
- Do not claim real Windows camera/input parity before validation on a Windows 10/11 host.
- No dynamic custom gesture recording in this milestone; only static custom activation templates are included.
- Existing `settings.json` migration is not required; configuration schema may advance and regenerate defaults.
- The directory has no Git metadata; do not add commit steps until a repository exists.

---

## File Structure

| Path | Responsibility |
|---|---|
| `app_build/macos_bundle.py` | Stable macOS bundle identity and privacy-purpose metadata. |
| `pyproject.toml` | PyInstaller build optional dependency and macOS Python 3.11 constraints. |
| `scripts/build_macos_app.sh` | Reproducible development `.app` build and ad-hoc signing command. |
| `docs/DEVELOPMENT.md` | Bundle build, TCC reset/regrant workflow, and local validation instructions. |
| `platform_services/contracts.py` | `CameraDevice`, `CameraService`, capability extensions. |
| `platform_services/macos/camera.py` | AVFoundation device enumeration, stable identity, selected-device opening facade. |
| `platform_services/macos/native.py` | Native AVFoundation camera enumeration/open calls and AppKit screen helpers. |
| `platform_services/windows/camera.py` | Safe contract-compatible placeholder; no unverified native claims. |
| `platform_services/factory.py` | Assemble platform camera service with the rest of the platform services. |
| `utils/config_manager.py` | Versioned `camera.device_id`, control-session, feedback, and static-trigger configuration. |
| `core/control_session.py` | Pure activation/exit/session state machine. |
| `core/static_gesture_template.py` | Landmark normalization, template capture, similarity match, and persistence-ready data shape. |
| `core/gesture_engine.py` | Apply control-session gating before emitting pointer action requests. |
| `gui/theme.py` | Precision Desk semantic tokens and all shared QSS primitives. |
| `gui/main_window.py` | Two-column operational console, readiness-derived primary action, selected-device worker launch. |
| `gui/settings_dialog.py` | Sidebar configuration shell and dedicated Control/Camera/Feedback/Permissions/Advanced pages. |
| `gui/gesture_list.py` | Grouped compact gesture rows and edit-panel contract. |
| `gui/control_settings_page.py` | Activation mode, exit behavior, shortcut capture, custom-trigger recording entry. |
| `gui/camera_settings_page.py` | Selectable device list, refresh, availability, resolution settings. |
| `gui/feedback_settings_page.py` | HUD mode, scale, opacity, and reduced-motion configuration. |
| `gui/permission_settings_page.py` | Camera/Accessibility explanation, status, and explicit authorization controls. |
| `gui/static_gesture_record_dialog.py` | Record/preview/name/save static activation templates. |
| `gui/overlay.py` | Pointer-adjacent, transparent, non-activating state HUD. |
| `gui/gesture_icons_svg.py` | Unified outline core hand-state assets; no temporary filled-hand vocabulary. |
| `tests/` | Unit, contract, Qt offscreen, and build metadata tests. |
| `docs/VALIDATION.md` | Automated and manual validation evidence, including external-camera and full-screen HUD checks. |

## Task 1: Build a stable macOS development application identity

**Files:**
- Create: `app_build/macos_bundle.py`
- Create: `scripts/build_macos_app.sh`
- Create: `tests/test_macos_bundle_metadata.py`
- Modify: `pyproject.toml`
- Modify: `docs/DEVELOPMENT.md`

**Interfaces:**
- Produces `dist/Gesture Control.app` with bundle id `com.cyk.gesturecontroller.dev`.
- Produces a bundle Info.plist containing `NSCameraUsageDescription` and `NSAccessibilityUsageDescription`.
- Includes `models/hand_landmarker.task` in the produced app bundle.

- [ ] **Step 1: Write failing metadata tests**

```python
# tests/test_macos_bundle_metadata.py
from setup import APP_NAME, BUNDLE_ID, PLIST


def test_development_bundle_has_a_stable_identity():
    assert APP_NAME == "Gesture Control"
    assert BUNDLE_ID == "com.cyk.gesturecontroller.dev"


def test_development_bundle_declares_camera_and_accessibility_purposes():
    assert "NSCameraUsageDescription" in PLIST
    assert "NSAccessibilityUsageDescription" in PLIST
```

- [ ] **Step 2: Verify RED**

Run:

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests/test_macos_bundle_metadata.py -v
```

Expected: FAIL because the macOS bundle metadata module does not exist.

- [ ] **Step 3: Add PyInstaller bundle metadata and build script**

Create `app_build/macos_bundle.py` with constants:

```python
APP_NAME = "Gesture Control"
BUNDLE_ID = "com.cyk.gesturecontroller.dev"
PLIST = {
    "CFBundleIdentifier": BUNDLE_ID,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleName": APP_NAME,
    "CFBundleShortVersionString": "0.1.0-dev",
    "CFBundleVersion": "1",
    "NSCameraUsageDescription": "Gesture Control uses the camera locally to recognize hand gestures.",
    "NSAccessibilityUsageDescription": "Gesture Control needs Accessibility access to move the pointer and perform configured hand gestures.",
    "LSMinimumSystemVersion": "15.0",
}
```

Use PyInstaller to bundle `main.py` as a windowed `.app`, include the MediaPipe task file at `models/hand_landmarker.task`, collect MediaPipe and PyQt5 runtime assets, and explicitly include native ApplicationServices, AVFoundation, and Quartz imports.

- [ ] **Step 4: Add build dependency and script**

Add `pyinstaller` to a `macos-build` optional dependency group. Create executable `scripts/build_macos_app.sh` that:

```bash
#!/usr/bin/env bash
set -euo pipefail
rm -rf build dist
python -m PyInstaller --windowed --osx-bundle-identifier com.cyk.gesturecontroller.dev main.py
codesign --force --deep --sign - "dist/Gesture Control.app"
```

The script must not notarize, package a DMG, or claim distribution readiness.

- [ ] **Step 5: Verify GREEN**

Run the metadata test again. Expected: PASS.

- [ ] **Step 6: Build and inspect the local app bundle**

Run:

```bash
env -u PYTHONPATH .venv/bin/python -m pip install -e ".[macos,macos-build,test]"
./scripts/build_macos_app.sh
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "dist/Gesture Control.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :NSCameraUsageDescription' "dist/Gesture Control.app/Contents/Info.plist"
test -f "dist/Gesture Control.app/Contents/Resources/models/hand_landmarker.task"
codesign --verify --deep --strict "dist/Gesture Control.app"
```

Expected: bundle identity/purpose text/model file are present and ad-hoc signature verifies.

- [ ] **Step 7: Update development documentation**

Document the exact build command, the fact that TCC is attached to `Gesture Control.app`, and the development-only nature of ad-hoc signing. Include a note that authorization may need to be toggled/regranted after a rebuilt bundle replaces an older copy.

## Task 2: Add stable camera-service contracts and macOS AVFoundation device discovery

**Files:**
- Modify: `platform_services/contracts.py`
- Create: `platform_services/macos/camera.py`
- Create: `platform_services/windows/camera.py`
- Modify: `platform_services/macos/native.py`
- Modify: `platform_services/factory.py`
- Create: `tests/macos/test_camera_service.py`
- Create: `tests/windows/test_camera_service.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class CameraDevice:
    device_id: str
    display_name: str
    kind: str
    available: bool

class CameraService(Protocol):
    def list_devices(self) -> list[CameraDevice]: ...
    def open_selected(self, device_id: str, width: int, height: int): ...
```

- [ ] **Step 1: Write a failing stable-device test**

```python
# tests/macos/test_camera_service.py
from platform_services.macos.camera import MacOSCameraService


class CameraNative:
    def list_video_devices(self):
        return [
            {"unique_id": "builtin-001", "name": "FaceTime HD Camera", "kind": "built_in", "available": True},
            {"unique_id": "usb-001", "name": "Logitech Brio 4K", "kind": "external", "available": True},
        ]


def test_macos_camera_service_preserves_stable_avfoundation_ids():
    devices = MacOSCameraService(CameraNative()).list_devices()

    assert [(d.device_id, d.display_name) for d in devices] == [
        ("builtin-001", "FaceTime HD Camera"),
        ("usb-001", "Logitech Brio 4K"),
    ]
```

- [ ] **Step 2: Verify RED**

Run the specific test. Expected: FAIL because `CameraDevice` and `MacOSCameraService` do not exist.

- [ ] **Step 3: Implement contracts and native facade**

Add `CameraDevice` and `CameraService` to contracts. `MacOSNativeFacade.list_video_devices()` must enumerate AVFoundation video devices and return dictionaries containing stable `uniqueID`, localized name, inferred kind, and connected/available state. Keep AVFoundation calls inside the native facade.

- [ ] **Step 4: Implement CameraService and verify GREEN**

`MacOSCameraService.list_devices()` maps native data to `CameraDevice`, preserving the stable device ID. Add tests for an empty result and an unavailable external device. Run all macOS camera-service tests.

- [ ] **Step 5: Add a Windows contract-safe implementation**

Create `platform_services/windows/camera.py` that satisfies the contract but returns no devices/unavailable opening until a Windows-native enumeration backend is implemented and validated. Add a test proving it does not claim devices/actions on macOS.

- [ ] **Step 6: Add camera service to PlatformServices**

Extend `PlatformServices` and both platform factory paths to include `camera_service`. Update fake/null platform services in existing tests. Run the full platform contract suite.

## Task 3: Persist selected camera identity and make configuration schema explicit

**Files:**
- Modify: `utils/config_manager.py`
- Create: `tests/test_camera_configuration.py`

**Interfaces:**
- `camera.device_id` is the preferred stored device identifier.
- `camera.id` is retained only as a temporary OpenCV fallback during transition.
- `schema_version` advances to `2`.

- [ ] **Step 1: Write a failing selected-camera test**

```python
# tests/test_camera_configuration.py
from utils.config_manager import ConfigManager


def test_camera_device_id_round_trips_without_using_open_cv_index(tmp_path):
    path = tmp_path / "settings.json"
    manager = ConfigManager(config_path=path)
    manager.set("camera", "device_id", "usb-001")
    manager.save()

    reloaded = ConfigManager(config_path=path)
    assert reloaded.get("camera", "device_id") == "usb-001"
```

- [ ] **Step 2: Verify RED**

Run the test. Expected: FAIL because the versioned default lacks `camera.device_id`.

- [ ] **Step 3: Implement schema v2 defaults and safe transition**

Add `device_id: ""` to default camera configuration. Retain the existing numeric `id` fallback for current development capture, but make new UI/CameraService reads prefer nonempty `device_id`. Never overwrite a valid saved `device_id` during load.

- [ ] **Step 4: Verify GREEN and malformed configuration behavior**

Add tests for missing `device_id`, malformed camera object, and saved unavailable device ID. Run config tests and full suite.

## Task 4: Introduce a pure ControlSession activation state machine

**Files:**
- Create: `core/control_session.py`
- Create: `tests/test_control_session.py`
- Modify: `core/gesture_engine.py`
- Modify: `utils/config_manager.py`

**Interfaces:**

```python
class ActivationMode(StrEnum):
    GESTURE = "gesture"
    HOLD_SHORTCUT = "hold_shortcut"
    GESTURE_OR_SHORTCUT = "gesture_or_shortcut"
    ALWAYS = "always"

class ControlSession:
    def update(self, gesture: str, has_hand: bool, shortcut_held: bool, now: float) -> SessionState: ...
    def allows_pointer_actions(self) -> bool: ...
```

- [ ] **Step 1: Write a failing activation test**

```python
# tests/test_control_session.py
from core.control_session import ActivationMode, ControlSession, SessionState


def test_gesture_mode_requires_stable_activation_before_pointer_control():
    session = ControlSession(
        mode=ActivationMode.GESTURE,
        activation_gesture="open_hand",
        exit_gesture="fist",
        stability_seconds=0.3,
        no_hand_timeout_seconds=2.0,
    )

    assert session.update("open_hand", True, False, 0.0) is SessionState.INACTIVE
    assert session.update("open_hand", True, False, 0.31) is SessionState.ARMED
    assert session.update("point", True, False, 0.32) is SessionState.POINTER
    assert session.allows_pointer_actions() is True
```

- [ ] **Step 2: Verify RED**

Run the focused test. Expected: FAIL because the session module does not exist.

- [ ] **Step 3: Implement minimal pure session behavior**

Implement the four activation modes, explicit exit gesture, no-hand timeout, and idempotent reset. `ALWAYS` permits pointer behavior without a trigger; all other modes gate pointer actions. Inject monotonic time through method parameters; do not sleep in tests.

- [ ] **Step 4: Verify GREEN and add boundary tests**

Add separate RED→GREEN cycles for hold-shortcut release, gesture-or-shortcut behavior, exit gesture, no-hand timeout, and always-active mode. Run `tests/test_control_session.py`.

- [ ] **Step 5: Gate GestureEngine requests**

Write a failing `GestureEngine` test showing that `point` yields no `ActionRequest` while session state is inactive, then integrate `ControlSession`. Ensure lock/drag state is reset as soon as session exits. Run pure engine and session tests.

- [ ] **Step 6: Add v2 control configuration defaults**

Add configuration fields:

```json
"control_session": {
  "mode": "gesture",
  "activation_gesture": "open_hand",
  "exit_gesture": "fist",
  "hold_shortcut": "",
  "stability_seconds": 0.3,
  "no_hand_timeout_seconds": 2.0
}
```

Do not make any legacy gesture automatically dangerous; the UI controls defaults explicitly.

## Task 5: Build static custom activation-template capture and matching

**Files:**
- Create: `core/static_gesture_template.py`
- Create: `tests/test_static_gesture_template.py`
- Modify: `core/control_session.py`
- Modify: `utils/config_manager.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class StaticGestureTemplate:
    template_id: str
    name: str
    feature_vector: tuple[float, ...]
    threshold: float

class StaticGestureMatcher:
    def normalize(self, landmarks) -> tuple[float, ...] | None: ...
    def match(self, landmarks, template: StaticGestureTemplate) -> bool: ...
```

- [ ] **Step 1: Write a failing normalization invariance test**

```python
# tests/test_static_gesture_template.py
from core.static_gesture_template import StaticGestureMatcher


def test_template_features_ignore_translation_and_scale():
    matcher = StaticGestureMatcher()
    original = [(i * 2.0, i * 3.0, 0.0) for i in range(21)]
    translated_scaled = [(100 + i * 6.0, 50 + i * 9.0, 0.0) for i in range(21)]

    assert matcher.normalize(original) == matcher.normalize(translated_scaled)
```

- [ ] **Step 2: Verify RED**

Run the test. Expected: FAIL because static-template module is missing.

- [ ] **Step 3: Implement feature normalization and matching**

Normalize around the wrist and divide by a nonzero palm-size reference. Quantize/round only if required for stable equality tests. Matching must compute a deterministic distance and compare it with a user-configured threshold. Reject incomplete landmarks and degenerate palms.

- [ ] **Step 4: Verify GREEN and add rejection tests**

Add tests for incomplete landmarks, template mismatch, and threshold boundary. Run the static-template suite.

- [ ] **Step 5: Connect custom templates to ControlSession configuration**

Add `custom_static_templates` and optional `activation_template_id` / `exit_template_id` configuration fields. The session accepts a matcher result as equivalent to a named configured activation/exit gesture. Keep dynamic recording out of scope.

## Task 6: Build Precision Desk shared visual primitives and main window shell

**Files:**
- Modify: `gui/theme.py`
- Create: `gui/precision_widgets.py`
- Modify: `gui/main_window.py`
- Create: `tests/test_precision_main_window.py`

**Interfaces:**
- `StatusChip`, `SummaryRow`, `PermissionRow`, `PrimaryControlButton`, and `SectionCard` become reusable Qt widgets.
- `MainWindow` exposes readiness-derived primary action and uses no main-window training button.

- [ ] **Step 1: Write a failing readiness-button test**

```python
# tests/test_precision_main_window.py
from gui.main_window import control_button_model
from platform_services.contracts import AuthorizationState, PermissionSnapshot


def test_missing_accessibility_yields_authorization_primary_action():
    model = control_button_model(
        is_running=False,
        permissions=PermissionSnapshot(
            camera=AuthorizationState.GRANTED,
            accessibility=AuthorizationState.DENIED,
        ),
    )

    assert model.label == "Grant Accessibility access"
    assert model.intent == "request_accessibility"
```

- [ ] **Step 2: Verify RED**

Run the focused test. Expected: FAIL because the pure model helper does not exist.

- [ ] **Step 3: Implement Precision Desk token system and pure readiness model**

Replace current purple/green gradient-card QSS with Precision Desk tokens. Use macOS system font priority and Chinese fallback. Implement a pure `control_button_model` that maps permission/running status to label, intent, and semantic state.

- [ ] **Step 4: Verify GREEN and add all readiness branches**

Add tests for missing camera, ready/inactive, and running states. Run focused tests.

- [ ] **Step 5: Recompose the main window**

Refactor `MainWindow.init_ui()` into:

- app header with title, subtitle, status chip, and Settings action;
- left live-camera verification surface;
- compact bottom hand/tracking state;
- right Control Session card with activation/camera/permission summaries;
- one primary button driven by `control_button_model`.

Move training out of the main window. Each `Change` summary action opens the matching settings sidebar page.

- [ ] **Step 6: Verify offscreen UI construction and primary action mapping**

Use `QT_QPA_PLATFORM=offscreen` tests to verify visible primary-action label/intent, camera summary, permission summary, and absence of the training main button. Run full tests and compile checks.

## Task 7: Replace settings tabs with Precision Desk sidebar pages

**Files:**
- Modify: `gui/settings_dialog.py`
- Create: `gui/control_settings_page.py`
- Create: `gui/camera_settings_page.py`
- Create: `gui/feedback_settings_page.py`
- Create: `gui/permission_settings_page.py`
- Create: `gui/gesture_list.py`
- Create: `tests/test_settings_navigation.py`
- Create: `tests/test_camera_settings_page.py`

**Interfaces:**
- `SettingsDialog.open_section(section_id: str)` selects a sidebar page.
- `CameraSettingsPage` consumes a `CameraService`, displays `CameraDevice` rows, and writes `camera.device_id` only after Save.
- `GestureList` groups core pointer and optional command rows.

- [ ] **Step 1: Write a failing sidebar-navigation test**

```python
# tests/test_settings_navigation.py
from gui.settings_dialog import SettingsDialog


def test_settings_can_open_camera_section(qapp, temporary_config):
    dialog = SettingsDialog(temporary_config)

    dialog.open_section("camera")

    assert dialog.current_section_id == "camera"
```

- [ ] **Step 2: Verify RED**

Run the focused test. Expected: FAIL because sidebar navigation is absent.

- [ ] **Step 3: Implement sidebar shell and page composition**

Replace horizontal tabs with a fixed left navigation list. Add Control, Gestures, Camera, Feedback, Permissions, Advanced pages. Preserve existing save/cancel semantics: no live mutation after opening except explicit authorization requests.

- [ ] **Step 4: Verify GREEN and add page selection tests**

Test all sidebar destinations and the Settings `Change` deep-link contract.

- [ ] **Step 5: Implement Camera page using CameraService**

Write a failing test with fake devices, then implement device rows, selected marker, refresh, unavailable status, resolution controls, and Save persistence by stable device ID. The page must not open a camera merely to list devices.

- [ ] **Step 6: Implement grouped Gesture list**

Write a failing test asserting core gestures appear in the Core group and optional gestures in Optional Commands. Replace the tall cards in the standard settings flow with compact rows. Keep detailed editing in a side pane/dialog with enablement, action, shortcut, sensitivity, feedback, and context-policy options.

- [ ] **Step 7: Implement Control, Feedback, Permissions, Advanced pages**

Control saves session mode, gesture/shortcut, timeout, and static-template choices. Feedback saves Quiet/Standard/Learn and HUD sizing values. Permissions displays authoritative values and triggers only explicit request methods. Advanced contains training and diagnostics entry points.

- [ ] **Step 8: Run all settings tests and offscreen smoke test**

Run relevant settings tests, full suite, and an offscreen construction script that visits every sidebar page.

## Task 8: Add custom static-trigger recording dialog

**Files:**
- Create: `gui/static_gesture_record_dialog.py`
- Create: `tests/test_static_gesture_record_dialog.py`
- Modify: `gui/control_settings_page.py`
- Modify: `core/mediapipe_worker.py`

**Interfaces:**
- `StaticGestureRecordDialog` accepts landmark frames from a dedicated preview session and returns a named `StaticGestureTemplate` only after user confirmation.
- The recording preview owns a camera session independently; it cannot run alongside control capture.

- [ ] **Step 1: Write a failing dialog state test**

```python
# tests/test_static_gesture_record_dialog.py
from gui.static_gesture_record_dialog import RecordingState, StaticGestureRecordDialog


def test_dialog_requires_enough_valid_frames_before_confirmation(qapp):
    dialog = StaticGestureRecordDialog(required_frames=3)

    assert dialog.state is RecordingState.WAITING
    dialog.accept_landmarks([(0, 0, 0)] * 21)
    dialog.accept_landmarks([(0, 0, 0)] * 21)
    assert dialog.can_confirm is False
```

- [ ] **Step 2: Verify RED**

Run the focused test. Expected: FAIL because the dialog/state is absent.

- [ ] **Step 3: Implement recording state and frame-quality checks**

States: Waiting, Capturing, ReadyToConfirm, Saved, Failed. Capture only visible, valid 21-landmark frames. Normalize and average valid feature vectors once the required frame count is reached. The user must name/confirm or retry; no auto-save.

- [ ] **Step 4: Verify GREEN and add invalid/retry tests**

Add tests for incomplete landmarks, inconsistent/degenerated palm data, retry clearing samples, and named-template creation.

- [ ] **Step 5: Connect the dialog to Control settings**

`Record custom trigger` must disable or safely stop an active control session, open a dedicated preview capture, store the confirmed template in config, and refresh activation/exit options. Restore no camera session automatically until the user explicitly starts control again.

## Task 9: Replace the central hand popup with a pointer-adjacent global HUD

**Files:**
- Modify: `gui/overlay.py`
- Modify: `gui/gesture_icons_svg.py`
- Create: `gui/hud_state.py`
- Create: `tests/test_hud_state.py`
- Create: `tests/test_overlay_window_flags.py`
- Modify: `gui/main_window.py`

**Interfaces:**

```python
class HudState(StrEnum):
    HIDDEN = "hidden"
    POINTER = "pointer"
    LOCKING = "locking"
    CLICKED = "clicked"
    DRAGGING = "dragging"
    SECONDARY_CLICK = "secondary_click"
    VOLUME = "volume"
    ERROR = "error"
```

- [ ] **Step 1: Write a failing HUD state-duration test**

```python
# tests/test_hud_state.py
from gui.hud_state import HudController, HudState


def test_click_feedback_expires_after_220ms():
    hud = HudController()
    hud.show_click(now=1.0)

    assert hud.current_state(now=1.10) is HudState.CLICKED
    assert hud.current_state(now=1.23) is HudState.HIDDEN
```

- [ ] **Step 2: Verify RED**

Run the test. Expected: FAIL because the HUD state controller does not exist.

- [ ] **Step 3: Implement pure HUD controller**

Implement state-specific duration, state priority, lock/drag persistence, quiet/standard/learn feedback modes, and no-op behavior in inactive session state. Use injected timestamps.

- [ ] **Step 4: Verify GREEN and state-priority tests**

Add tests that dragging overrides pointer, error overrides transient click, and quiet mode hides noncritical pointer feedback.

- [ ] **Step 5: Implement non-intercepting overlay behavior**

Update `GestureOverlay` to set:

```python
Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
Qt.WA_TranslucentBackground
Qt.WA_TransparentForMouseEvents
Qt.WA_ShowWithoutActivating
```

Write an offscreen test verifying flags and mouse transparency. Position it relative to pointer/lock coordinates with screen-edge avoidance. Do not use a central fixed placement.

- [ ] **Step 6: Replace icon asset contract**

Replace current filled/mixed icons with unified outline assets for point, pinch, grab, secondary click, and thumb volume. Retain action symbols from a MIT-compatible set only when attribution/license source is documented in source comments or `docs/ATTRIBUTIONS.md`. Remove temporary custom filled hand shapes from core HUD use.

- [ ] **Step 7: Connect engine/action state to HUD state**

Map session, action machine, and action result to HUD states:

- pointer when session permits pointer control;
- locking when state machine locks;
- clicked only after an executed click result;
- dragging while drag is held;
- errors when permission/platform dispatch fails.

Avoid showing classifier-only gesture names on every gesture transition.

- [ ] **Step 8: Manual macOS HUD verification**

Check normal desktop apps, a full-screen app, and a second Space. Record whether Qt’s overlay stays above all relevant surfaces without intercepting clicks. If not, stop and design a minimal AppKit `NSPanel` adapter before attempting visual workarounds.

## Task 10: Complete focused validation and document unverified platform limits

**Files:**
- Modify: `docs/VALIDATION.md`
- Modify: `docs/DEVELOPMENT.md`
- Create: `tests/test_precision_integration.py`

**Interfaces:**
- Integration tests use fake camera/platform services and validate readiness → session gating → HUD event transitions without real input injection.

- [ ] **Step 1: Write an integration regression test**

```python
# tests/test_precision_integration.py

def test_inactive_session_does_not_dispatch_pointer_actions_or_show_click_hud(fake_precision_controller):
    fake_precision_controller.process_gesture("point")

    assert fake_precision_controller.input_requests == []
    assert fake_precision_controller.hud_state == "hidden"
```

- [ ] **Step 2: Verify RED, implement minimal integration seam, verify GREEN**

Use fake services and deterministic clocks. Do not invoke native mouse or camera APIs in automated tests.

- [ ] **Step 3: Run complete automated validation**

Run:

```bash
env -u PYTHONPATH .venv/bin/python -m compileall -q core gui platform_services utils tests
env -u PYTHONPATH .venv/bin/python -m pytest -q
```

Record fresh output in `docs/VALIDATION.md`.

- [ ] **Step 4: Perform manual macOS development-app validation**

Run the app from `dist/Gesture Control.app`, then verify:

1. macOS Privacy & Security identifies Gesture Control rather than Python or a script;
2. camera purpose wording appears when permission is absent;
3. external/virtual/Continuity camera devices list with names and stable selection persists;
4. start opens the selected camera only;
5. Accessibility permission is only requested by explicit UI action;
6. each Control activation mode gates pointer movement correctly;
7. static recorded trigger enters/exits session only after configured stability;
8. pointer/lock/click/drag HUD remains non-intercepting and does not steal focus;
9. stop/timeout/hand-loss releases drag safely;
10. full-screen and multi-Space HUD behavior is recorded honestly.

- [ ] **Step 5: Update validation matrix without extrapolation**

Mark Windows real-device behavior `not run` until performed on Windows. Mark signed/notarized distribution `not done`. Include exact versions and any remaining macOS overlay limitations.

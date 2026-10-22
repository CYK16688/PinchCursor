# Precision Desk UI Design Specification

> **Historical record (PyQt5 / Python 3.11 era).** This document describes the
> stack as it was on 2026-08-14. The project has since moved to PySide6 6.12
> and Python 3.13 — see [../PYSIDE6-MIGRATION.md](../PYSIDE6-MIGRATION.md).
> Python/Qt versions mentioned below are no longer current.

**Status:** User-approved visual direction; ready for implementation-plan review

**Goal:** Redesign the desktop hand-gesture controller as a polished macOS-first control console that makes camera, permissions, control-session activation, and feedback clear without turning the desktop into an XR imitation.

## Product Position

Gesture Control is a desktop pointer-control tool. It uses camera-based hand tracking to supplement or replace mouse input. It does not assume eye tracking, depth sensing, 3D spatial anchors, or a headset display.

The interaction model remains pointer-first:

```text
hand landmarks → screen pointer → desktop target → pointer action
```

XR products are reference material only for progressive feedback, target locking, action confirmation, and low-distraction status signaling. They are not templates for the desktop interaction model.

## User Outcomes

A user must be able to answer the following in under a few seconds:

1. Is Gesture Control ready to run?
2. Which camera is selected?
3. Are Camera and Accessibility permissions granted?
4. Which activation method currently gates hand input?
5. Is hand control currently inactive, armed, locked, dragging, or unavailable?
6. What action did the last deliberate gesture perform?

## Visual Direction

**Name:** Precision Desk

**Character:** restrained desktop utility; dark, calm, precise, and legible. The product should resemble a high-quality macOS utility rather than a game HUD, an XR demo, or a generic card dashboard.

### Design tokens

| Token | Value | Use |
|---|---|---|
| Canvas | `#0B0C0F` | window/page background |
| Surface | `#121419` | main surfaces |
| Elevated surface | `#1A1D24` | cards, sheets, selected areas |
| Hairline | `rgba(255,255,255,0.08)` | dividers and quiet boundaries |
| Primary text | `#F5F7FA` | headings and primary values |
| Secondary text | `#8B93A1` | labels and help copy |
| Accent | `#5E8CFF` | active selection and primary interaction |
| Ready | `#47D7A1` | granted/running/healthy state |
| Warning | `#F5B942` | attention state |
| Danger | `#FF6B6B` | denied/error state |
| Radius small | `12px` | controls and grouped rows |
| Radius medium | `16px` | primary cards |
| Radius large | `20px` | camera viewport and large sheets |

Typography uses system UI typography: SF Pro on macOS, Segoe UI on Windows, with PingFang SC and Microsoft YaHei fallback for Chinese. Avoid display fonts, gradients, or heavy shadows. Use one accent color and semantic states rather than assigning each card a unique color.

## Main Window

### Surface archetype

The main window is an **Operate** surface. Its primary question is: “Is hand control ready, and can I start it safely?” Its primary action is “Start control” or “Stop control.”

### Layout

At desktop width, use a two-column adaptive layout:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Gesture Control                           status chip   Settings    │
│ Desktop hand input                                                  │
├──────────────────────────────┬──────────────────────────────────────┤
│                              │ CONTROL SESSION                      │
│ Live Camera                  │ status: Ready / Needs permission     │
│ rounded viewport             │                                      │
│ hand skeleton + status       │ Activation                           │
│                              │ Gesture / Hold shortcut / Always     │
│                              │ selected method summary              │
│                              │                                      │
│                              │ Camera                               │
│                              │ current device                       │
│                              │                                      │
│                              │ Permissions                          │
│                              │ Camera and Accessibility rows        │
│                              │                                      │
│                              │ [Start control]                      │
├──────────────────────────────┤                                      │
│ Hand detected · Point        │                                      │
│ Tracking / lost / idle       │                                      │
└──────────────────────────────┴──────────────────────────────────────┘
```

### Main window rules

- The camera preview is a verification surface, not the visual center of the whole product.
- The right panel presents current configuration as summaries with `Change` links that open the relevant Settings section.
- There is exactly one dominant control button. Its label and color are derived from readiness:
  - `Grant camera access` when camera permission is missing;
  - `Grant Accessibility access` when pointer control is blocked;
  - `Start control` when ready and inactive;
  - `Stop control` when active.
- Advanced model training is not a main-window action. It moves to Advanced settings.
- The existing prominent raw gesture text becomes a compact bottom status line.

## Settings Information Architecture

Replace the horizontal tab strip with a left sidebar and one settings content pane.

```text
Control
Gestures
Camera
Feedback
Permissions
Advanced
```

### Control

Purpose: configure how the user enters and exits a control session.

Fields:

- Activation mode:
  - Gesture trigger;
  - Hold shortcut;
  - Gesture or hold shortcut;
  - Always active.
- Activation gesture: built-in gesture or recorded custom static gesture.
- Exit gesture: built-in gesture or recorded custom static gesture.
- Hold shortcut capture.
- Auto-exit timeout when no hand is detected.
- Optional activation confirmation delay.

### Gestures

Purpose: map gestures to actions only after control is active.

Use grouped, compact rows instead of 140px cards:

```text
CORE POINTER CONTROL
Enabled  Gesture          Action              Feedback
●        Point            Move pointer        Cursor halo
●        Pinch            Click               Pulse
●        Pinch and hold   Drag                Lock ring

OPTIONAL COMMANDS
○        Peace            Secondary click     Secondary pulse
○        Thumb up         Volume up           Volume meter
○        Thumb down       Volume down         Volume meter
```

Selecting a row opens an edit sheet/pane with enablement, action, shortcut, sensitivity, context policy, and feedback choice. No gesture action is silently enabled if it is unsupported on the active platform.

### Camera

Purpose: select and validate the input device.

It must show real device names, availability, selected device, resolution, and refresh. The persisted device identity is a platform-stable identifier, not a transient OpenCV index. The macOS implementation will use AVFoundation device identifiers; the Windows implementation will use an equivalent Windows device identity.

### Feedback

Purpose: control how much visual guidance is shown.

Modes:

- Quiet: only drag lock and errors;
- Standard: pointer state, lock, click, drag, and media feedback;
- Learn: adds brief gesture/action labels and guidance.

It also includes HUD scale and opacity controls.

### Permissions

Purpose: show authoritative Camera and Accessibility state, explain why each is needed, and expose only explicit user-initiated authorization actions. The page never asks the user to choose a source file or script.

### Advanced

Purpose: model diagnostics, data collection, training, import/export, reset, and developer logging. These controls are not part of daily operation.

## Control Session Model

The application must distinguish application running from pointer control active.

```text
App stopped
  ↓ start application
Ready / inactive
  ↓ activation trigger satisfies configured policy
Armed
  ↓ point gesture
Pointer control
  ↓ pinch trend
Locked
  ↓ release or hold/move
Click / Dragging
  ↓ configured exit trigger, timeout, hand loss, or stop
Ready / inactive
```

No pointer action is emitted in `Ready / inactive`. The configurable activation mode gates the existing point/pinch/drag state machine.

### Custom activation gesture recording

Phase 1 supports recorded **static** gestures only:

1. User chooses “Record custom trigger.”
2. UI guides the user to hold a hand pose for a short sample period.
3. The application validates landmark visibility and collects several normalized 21-point frames.
4. The user previews, names, saves, or retries the trigger.
5. Runtime matching compares normalized current landmarks against the user template with a configurable confidence threshold and stability duration.

Dynamic gesture recording is excluded from this phase. It requires temporal-template matching or a trained sequence model and will be designed separately.

## Global Gesture HUD

### Purpose

The HUD communicates control state and action confirmation close to the desktop pointer. It does not represent every raw classifier output and does not block desktop interaction.

### Placement and window behavior

- Position near the pointer or action lock position, with screen-edge avoidance.
- Always on top of desktop applications.
- Transparent background.
- Mouse-event transparent.
- Does not activate or steal keyboard focus.
- Must be validated on macOS normal windows, full-screen applications, and multiple Spaces.
- If Qt top-level behavior cannot reliably satisfy macOS window-level requirements, use a minimal AppKit `NSPanel` adapter rather than changing the gesture engine.

### Feedback states

| State | Visual | Persistence |
|---|---|---|
| Inactive | none | hidden |
| Armed / pointing | low-contrast cursor halo | while active |
| Locking | accent ring contracts around lock point | until click/cancel |
| Clicked | 220ms pulse | transient |
| Dragging | persistent grab ring and short connector | while dragging |
| Secondary click | secondary pulse | transient |
| Volume | compact meter | 400–700ms |
| Permission/error | concise status chip near current pointer or app panel | until resolved/dismissed |

### Icon system

Retire the mixed Phosphor-fill and hand-built SVG vocabulary. Introduce a consistent icon contract:

- Action affordances use a MIT icon set such as Lucide or Tabler where appropriate.
- Core hand states use five custom outline SVG assets: point, pinch, grab, secondary-click/peace, and thumb-volume.
- Icons use a fixed grid, consistent rounded stroke, no filled hand silhouettes, and semantic color supplied by the HUD theme.
- Extension gestures without an action binding do not get a HUD icon by default.

## Accessibility and Input Safety

- HUD never intercepts pointer events.
- Every interaction has a keyboard-accessible equivalent in Settings.
- Permission controls explain status; prompts occur only after user action.
- Use at least 44×44 logical-pixel controls in the main window and settings.
- Respect macOS reduced-motion preference by replacing ring transitions with immediate state changes.
- Avoid color-only status; use text and icons as well.

## Non-Goals

- Reproduce Vision Pro, Android XR, or Samsung XR environment UI.
- Depend on eye tracking, 3D input, headset cameras, or spatial anchors.
- Add every recognized hand pose to the default control vocabulary.
- Implement dynamic custom gesture recording in this phase.
- Redesign the core gesture model while changing visual composition.

## Delivery Order

1. Build an app-identity and CameraService milestone so permissions and device selection are stable.
2. Add Control Session model and settings page before enabling more default gestures.
3. Replace the main window shell and migrate status, readiness, and the single primary action.
4. Replace gesture-card list with grouped configurable gesture rows.
5. Build global pointer-adjacent, input-transparent HUD and unified icon system.
6. Add static custom trigger recording and its calibration UI.
7. Perform manual macOS validation across external cameras, permissions, desktop apps, full-screen apps, and long-running interaction.
8. Apply the same design contract to Windows after native device/input verification.

## Acceptance Criteria

- A user can identify readiness, selected camera, permission status, activation method, and primary action without opening Settings.
- A user can select and persist an external camera by stable platform identity.
- Pointer actions cannot run until the configured control-session activation condition is satisfied.
- A user can use built-in or static custom recorded gestures as activation/exit triggers.
- HUD feedback is on top, mouse transparent, non-activating, pointer-adjacent, and state-specific.
- No raw/temporary hand SVG is used in the core HUD.
- Existing MediaPipe landmark output, shared gesture engine, and platform action contracts remain valid.

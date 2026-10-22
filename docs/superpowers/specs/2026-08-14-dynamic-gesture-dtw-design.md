# Dynamic Gesture Recording and DTW Design

> **Historical record (PyQt5 / Python 3.11 era).** This document describes the
> stack as it was on 2026-08-14. The project has since moved to PySide6 6.12
> and Python 3.13 — see [../PYSIDE6-MIGRATION.md](../PYSIDE6-MIGRATION.md).
> Python/Qt versions mentioned below are no longer current.

## Goal

Add a macOS-first dynamic gesture feature that lets a user record a continuous hand movement, bind it to a safe semantic action, and trigger that action accurately during an active control session.

## Product boundary

Core pointer control remains deterministic:

- Point moves the pointer.
- Pinch lifecycle drives lock, click, drag, release, and cancellation.
- Static templates remain activation/exit triggers.

Dynamic templates are optional shortcut gestures only. They never start pointer control, never replace the pinch state machine, and never directly perform destructive actions.

## User flow

1. User opens Settings → Gestures → Dynamic shortcuts.
2. User starts recording and sees a countdown/status plus camera preview.
3. The app captures a bounded sequence of valid landmark frames while the user performs a motion.
4. The user names the motion and selects a safe semantic action.
5. The user repeats the same motion several times; each accepted take is retained under one template.
6. After Save, the template is available at runtime only while the control session is active.
7. The matcher detects one completion, dispatches its configured action once, enters cooldown, and requires neutral motion before a new trigger.

## Data model

A dynamic template stores:

```text
DynamicGestureTemplate
- template_id
- name
- action
- samples: tuple of fixed-length normalized feature sequences
- threshold
- cooldown_seconds
- min_motion_energy
```

A frame feature is wrist-relative, palm-scale-normalized 21×3 landmarks plus a compact motion representation. Sequences are causally resampled to a fixed frame count before matching.

Templates serialize into `control_session.dynamic_templates` only after explicit Save.

## Matching policy

- Feature extraction rejects incomplete, degenerate, non-finite landmarks.
- Recording rejects too-short, too-long, and low-motion sequences.
- Live matching operates over a bounded trailing frame window.
- DTW compares the live sequence to every sample of each template using normalized local feature distance and a Sakoe–Chiba band.
- A candidate requires: active ControlSession, minimum motion energy, distance under threshold, a margin over the next best template, no cooldown, and a neutral/rearm condition after firing.
- A match produces exactly one `ActionRequest`; it does not emit repeats for a sustained pose.

## Safety

First version action whitelist:

- scroll_up
- scroll_down
- back
- forward
- media_play_pause
- volume_up
- volume_down
- custom_hotkey

No first-version dynamic binding for deletion, window closing, lock screen, click, drag lifecycle, or pointer movement.

## Integration

- `core/dynamic_gesture_template.py`: pure feature, DTW, recording and runtime matcher.
- `gui/dynamic_gesture_record_dialog.py`: record/status/preview/name/action workflow.
- `gui/dynamic_gesture_settings_page.py`: manage saved templates and bindings.
- `utils/config_manager.py`: schema defaults and serialization-safe configuration.
- `gui/main_window.py`: live sequence ingestion only after the ControlSession permits actions; dispatch through `GestureActionCoordinator`.
- `gui/settings_dialog.py`: Settings section integration and staged Save behavior.

## Acceptance criteria

- A synthetic recorded sequence matches after time variation but rejects different or low-motion sequences.
- The same detected gesture cannot fire twice until it returns to neutral and cooldown expires.
- Inactive control sessions dispatch no dynamic action.
- Only whitelisted actions can be persisted or dispatched.
- Templates persist and hot-reload after Settings Save.
- Existing core pointer behavior and safety-release tests remain green.
- Full automated suite, compile check, macOS app build, and signature validation pass before manual user validation.

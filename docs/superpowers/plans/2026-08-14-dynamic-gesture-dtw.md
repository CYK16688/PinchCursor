# Dynamic Gesture DTW Implementation Plan

> **Historical record (PyQt5 / Python 3.11 era).** This document describes the
> stack as it was on 2026-08-14. The project has since moved to PySide6 6.12
> and Python 3.13 — see [../PYSIDE6-MIGRATION.md](../PYSIDE6-MIGRATION.md).
> Python/Qt versions mentioned below are no longer current.

## Binding design

- Core pointer actions remain in the existing deterministic state machine.
- Dynamic templates are optional, action-whitelisted, and only active after ControlSession activation.
- DTW is the first dynamic recognizer; no TensorFlow/LSTM dependency is introduced.

## Tasks

1. Create pure dynamic feature, recording validation, DTW matcher, neutral/cooldown state, and deterministic tests.
2. Add schema-safe persistence and action whitelist enforcement.
3. Add dynamic recording dialog and staged settings management for recording, naming, binding, delete, and Save.
4. Integrate live matching into MainWindow after active session gating and through the existing action coordinator.
5. Add replay/integration tests: time-warp match, mismatch rejection, inactive-session suppression, cooldown/rearm, hot reload, and action whitelist.
6. Run full suite, compileall, PyInstaller rebuild, codesign verification, then start the app for final user validation.

## Constraints

- macOS-first; keep shared pure matcher portable.
- No LSTM/TensorFlow dependency.
- No direct destructive action binding.
- User will not perform intermediate testing; autonomous tests and build verification must be completed before requesting final manual validation.
- The working directory has no Git metadata, so do not claim commits or clean worktree state.

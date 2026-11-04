# Change log

All notable changes to PinchCursor are recorded here. The project is pre-1.0, so
the format stays light: newest first, grouped as Added / Changed / Fixed /
Removed, and every entry names the file or subsystem it touches so the notes stay
useful during review.

## Unreleased

### Added

- `capture/` — a top-level capture package holding `mediapipe_worker.py`. Camera
  frames and MediaPipe landmark inference are Qt-thread coupled, so they no
  longer live under `core/`.
- `core/pointer_projection.py` — one stateless rule for turning a hand position
  into a screen point, shared by the control engine and the main window. It
  replaces two drifting copies of the same mapping maths.
- `core/pointer_gate.py`, `core/power_policy.py`, `core/ir_presence.py` —
  isolated policies extracted from the control engine so each can be tested
  without a camera.
- `utils/settings.py` — a typed read path over the config manager: one section
  reader, one snapshot, and one place where defaults such as the assist gain are
  declared.
- Tests for the extracted units: `tests/test_pointer_gate.py`,
  `tests/test_power_policy.py`, `tests/test_ir_presence.py`,
  `tests/test_settings.py`.
- A real CI gate in `.github/workflows/tests.yml`: a blocking job that compiles
  and runs the whole suite, and a separate lint job that runs `ruff` on the
  Python files a push or pull request actually touches.
- `.pre-commit-config.yaml` so the same lint runs before a commit lands.
- `ruff` and type-check configuration under `pyproject.toml`, documented in
  `docs/DEVELOPMENT.md`.

### Changed

- The dependency direction is now one-way: `capture/` and `platform_services/`
  feed `core/`, `core/` uses `utils/`, and `gui/` sits on top. `core/` contains
  no Qt import at all, and `utils/` no longer imports `core/`.
- `utils/dynamic_gesture_template.py` moved out of `core/`, which removed the
  reverse `utils -> core` dependency that made the old layering claim false.
- `utils/settings.py` is the single read path for every settings section that a
  fixed record can describe: pointer mapping, assist, sensitivity,
  stabilization, scroll, stability, context-aware, temporal, action-mode,
  performance and the learned pinch calibration. That removes the duplicated
  defaults (the mapping gain, the scroll timings, the dead zone, the action
  thresholds) and makes an unusable value fall back to the documented default;
  a saved pinch calibration is returned only when both ratios are usable, so
  "not calibrated" is one explicit rule instead of an exception path. What still
  reads its own mapping is what a fixed record cannot hold: the per-gesture
  lookup table, list settings, the config file path, and the learn-time override
  that a raw assist mapping carries.
- The context, intent-action and transition-guard defaults are defined once
  beside the schema, so the schema, the typed reader and the engine's
  hot-path reads fall back to the same value instead of three literals
  that could drift apart.
- The conversion of recorded static and dynamic shortcuts into runtime templates
  lives in `core/dynamic_config.py`. The control engine and the main window both
  call it, so the window no longer borrows the engine's private restore methods;
  its own constructor restores shortcuts directly.
- The window no longer declares `= ControlEngine._x` aliases. The three it
  kept (snap provider, candidate recorder, observation reset) are called on
  the window explicitly, bound to the real engine class captured at import.
- Documentation: `docs/DEVELOPMENT.md` gained a static-checks section, and
  `docs/CONTROL_ARCHITECTURE.md` records the new module boundaries.

### Fixed

- `core/control_engine.py` keeps validated pinch termination separate from
  pointer-position rejection: an outlier on release cannot erase a click or
  postpone cancelling an active drag. Rejected positions cannot start another
  action or become a click target.
- CI lint checks the whole push or pull-request range, handles deleted and
  renamed files, and passes file paths without shell splitting. The local hook
  uses the same pinned Ruff version; formatting remains optional until the
  existing formatting debt is resolved.
- A corrupted batch of words in the README (`mailbox`, `context`, `text`,
  `index`, `experimental`, `explicitly` and `requirements.txt` had letters
  replaced) is repaired.
- The recorded test count matches the suite again (1482 passing).

## 0.2.0 — 2026-10-29

### Added

- Predictive pinch targeting: while a pinch is only a candidate the visible
  pointer keeps following the fingertip, and the confirmed click is applied to
  the aim reconstructed before closure, so moving fingers no longer pull the
  click away from the intended point.
- A Simplified Chinese README next to the English one.
- A related-projects section naming the dependencies, prior art and adjacent
  implementations the project builds on.

### Changed

- The README was rebuilt around the runtime flows (a frame becoming an intent,
  the pinch lifecycle, and failure safety) instead of a feature table alone.

## 0.1.x — 2026-10-22 to 2026-10-25

### Added

- The learning loop became observable: a diagnostics surface reports what the
  adaptive pieces actually learned.
- Pinch episodes are recorded, so the transition boundary can be learned from
  real interactions rather than assumed.
- Aim assist is tuned from the clicks a user had to redo.

### Fixed

- A crash where AVFoundation invoked its callback on a dispatch queue.
- Permission handling: requests follow the documented macOS order, the
  permission page can be re-checked, and a restart hint appears when a grant
  needs one. The docs now explain why an ad-hoc build loses its permissions on
  every rebuild.

## 0.1.0 — 2026-10-22

### Added

- First working release: webcam hand tracking driving pointer movement, clicks,
  drag and scroll on macOS, with deterministic intent arbitration,
  watchdog-protected native input and release-on-loss safety.
- The product is renamed to PinchCursor and ships a new mark.

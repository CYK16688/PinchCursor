# Contributing

PinchCursor is a small, safety-sensitive desktop application: it moves a real
pointer and clicks real buttons. A change that looks harmless can leave a mouse
button held down on someone else's machine, so this guide is mostly about the
evidence a change has to carry with it.

## Set up

The full environment, build and manual-prerequisite steps live in the
[development guide](docs/DEVELOPMENT.md). In short: Python 3.13, a virtual
environment at `.venv`, and `pip install -e ".[macos,test]"`. macOS 15+ on Apple
Silicon is the supported development target.

## The gate your change has to pass

```bash
env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```
Read the summary line, not only the exit code: the suite ends the process early
on purpose, so a run is green only when it reports every collected test passing.
The current baseline is 1434 passed.

Also required:

- `ruff check` on the files you touched reports nothing new. The CI lint job is
  scoped to changed files, and a pre-commit hook runs the same check.
- the type-check configuration under `tool.mypy` does not gain findings.

## Layering contract

The dependency direction is one way. A change that reverses an arrow is a design
change, not a detail, and has to say so in its description.

- `core/` holds deterministic decisions. It must not import Qt and must not
  reach into `gui/`.
- `capture/` owns camera frames and MediaPipe inference, which are Qt-thread
  coupled.
- `utils/` is dependency-free helpers. It must not import `core/`.
- `platform_services/` is the only place that talks to the operating system.
- All native pointer and keyboard side effects go through that single boundary.

```
capture/   platform_services/
      \         /
       v       v
         core/ -> utils/
          ^
          |
        gui/
```

## Behaviour that must not regress

These are the guarantees the suite exists to protect. If a change touches them,
add a test that fails without it:

- a held button is released on stop, tracking loss, stale frames, camera stall
  and hand opening;
- only fresh evidence may dispatch input, and a late frame cannot renew a
  revoked session;
- a pending mouse-up blocks another press;
- the learned target ranker starts in shadow mode and cannot move the pointer
  until it is explicitly promoted.

## Tests

- Add or update tests in `tests/`. The suite uses fake OS sinks and synthetic
  landmark replays, so no camera is needed.
- Prefer a test that encodes the invariant over a test that pins an
  implementation detail.
- Do not weaken an existing assertion to make a change pass. If an assertion is
  genuinely wrong, fix it in its own commit and say why.

## Commits and pull requests

- Write the subject line as a sentence about the effect of the change, not as a
  file list. For example: `Let the permission page be re-checked, and say when a
  restart is needed`.
- Keep refactors and behaviour changes in separate commits where the split is
  clean; it makes review and revert tractable.
- State what you verified and what still needs a real device. Synthetic coverage
  cannot prove camera accuracy, physical mouse equivalence or long-session
  comfort; those stay in `docs/`.

## Documentation

- `docs/` is written in English, and the top-level README is bilingual, so a
  user-visible change usually touches both README languages.
- Record a user-visible change in the change log at the repo root.
- Prefer short, concrete statements over marketing adjectives. If a limit is
  real, write the limit down instead of implying it away.

## License

Contributions are accepted under AGPL-3.0, the license this project already
ships with.

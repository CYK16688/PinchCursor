# Local Development

## Supported development environment

- Python **3.13** — required: `numpy` 2.5.4 needs >= 3.12, and the project targets
  the current stable interpreter
- **PySide6 6.12.0** (LGPL-3.0) — Qt 6 widget toolkit
- **MediaPipe 1.1.1** hand landmarker, **numpy 2.5.4**,
  **opencv-contrib-python 5.0.0.93**
- macOS 15+ on Apple Silicon (`arm64`) — primary platform
- Windows 10/11 x64 — adapter layer, requires real-host validation
- Local development validation only; this project does not yet produce a signed,
  notarized, or DMG-distributed application by default.

`opencv-contrib-python` (not `opencv-python`) is the OpenCV distribution MediaPipe
1.1.1 depends on. Both provide the `cv2` module, so installing both corrupts the
import path — keep only the contrib build.

## Create the environment

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[macos,test,macos-build]"
```

Without `uv`:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[macos,test,macos-build]"
```

If `python3.13` is not on `PATH`, install it first and use its absolute path.

## Run locally

```bash
. .venv/bin/activate
python main.py
```

## Run the test suite

```bash
env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

**Check the exit code, not just the pass count.** The suite reports its verdict
and then `tests/conftest.py` exits the process before CPython interpreter
finalization, because PySide6 6.12 aborts there on macOS (see the comment block
in that file). A run is only green when all collected tests pass **and** it exits `0`.

## Build the macOS development app

```bash
. .venv/bin/activate
python -m pip install -e ".[macos,macos-build]"
./scripts/build_macos_app.sh
open "dist/PinchCursor.app"
```

Both platforms build from the single shared spec `PinchCursor.spec`, so the
module lists and Qt excludes cannot drift apart.

The development bundle uses the identifier `com.cyk16688.pinchcursor` and is
ad-hoc signed by default. macOS Privacy & Security grants Camera and
Accessibility permissions to **PinchCursor**, not to `main.py` or Homebrew
Python.

An ad-hoc signature changes on every rebuild, so macOS re-prompts for both
permissions each time. To keep grants stable, sign with a Developer ID:

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
  ./scripts/build_macos_app.sh
```

Add `NOTARY_PROFILE=<notarytool-profile>` to also notarize and staple. That path
is required before handing the app to anyone else.

## Build the Windows app

PyInstaller cannot cross-compile — run this on Windows 10/11:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pip install "pyinstaller==6.22.3"
pwsh .\scripts\build_windows.ps1
```

Output: `dist\PinchCursor\PinchCursor.exe` (onedir, windowed).

## Manual macOS prerequisites

1. Confirm the runtime architecture is Apple Silicon:

   ```bash
   python -c "import platform; print(platform.machine())"
   ```

   Expected output: `arm64`.

2. Allow camera access when the application explicitly requests it.
3. In **System Settings → Privacy & Security → Accessibility**, allow the launched Python/app process before enabling desktop input control.
4. Start the app and confirm its readiness UI reports the current camera and Accessibility states.
5. Test pointer movement, click, drag stop safety, scrolling, configured Command-key shortcuts, and cross-application UI-context filtering.

Never expect a permission prompt during continuous hand tracking; permission requests must result from an explicit UI action.

## Product icon

Use `gui/resources/pinchcursor.png` as the only source. See [Branding](BRANDING.md)
for regeneration instructions and the generation record. Platform exports are
tracked; `build/`, `dist/` and Python caches are disposable local output.

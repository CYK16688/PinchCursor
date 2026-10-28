#!/usr/bin/env bash
# Build the macOS development app bundle.
#
# Requires the project environment (Python 3.13 + PySide6 + mediapipe). PyInstaller
# cannot cross-compile, so this script only runs on macOS.
#
# Signing:
#   AD-HOC (default)        no identity needed, but macOS re-prompts for Camera and
#                          Accessibility after every rebuild because the TCC grant
#                          is keyed to the code signature.
#   DEVELOPER ID            set CODESIGN_IDENTITY="Developer ID Application: ..."
#                          to keep TCC grants stable across rebuilds.
#   NOTARIZATION            additionally set NOTARY_PROFILE (a `notarytool`
#                          keychain profile) to staple a notarization ticket.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Project environment is missing: $PYTHON" >&2
  echo "Create it with:  uv venv --python 3.13 .venv && uv pip install -e '.[macos,test,macos-build]'" >&2
  exit 1
fi

APP_NAME="$("$PYTHON" -c 'from app_build.macos_bundle import APP_NAME; print(APP_NAME)')"
BUNDLE_ID="$("$PYTHON" -c 'from app_build.macos_bundle import BUNDLE_ID; print(BUNDLE_ID)')"
CAMERA_USAGE="$("$PYTHON" -c 'from app_build.macos_bundle import CAMERA_USAGE_DESCRIPTION; print(CAMERA_USAGE_DESCRIPTION)')"
ACCESSIBILITY_USAGE="$("$PYTHON" -c 'from app_build.macos_bundle import ACCESSIBILITY_USAGE_DESCRIPTION; print(ACCESSIBILITY_USAGE_DESCRIPTION)')"
MIN_VERSION="$("$PYTHON" -c 'from app_build.macos_bundle import MINIMUM_SYSTEM_VERSION; print(MINIMUM_SYSTEM_VERSION)')"

rm -rf build dist

# The spec file owns the module list, Qt excludes, and data files so that the
# macOS and Windows builds cannot drift apart.
env -u PYTHONPATH "$PYTHON" -m PyInstaller --noconfirm --clean "PinchCursor.spec"

APP_PATH="dist/$APP_NAME.app"
INFO_PLIST="$APP_PATH/Contents/Info.plist"

# Usage strings must exist before signing; they are part of the sealed bundle.
/usr/libexec/PlistBuddy -c "Add :NSCameraUsageDescription string $CAMERA_USAGE" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :NSAccessibilityUsageDescription string $ACCESSIBILITY_USAGE" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string $MIN_VERSION" "$INFO_PLIST"

# Auto-detect a stable identity. Ad-hoc signatures derive their designated
# requirement from the cdhash, which changes on every build, so macOS forgets
# every Camera/Accessibility grant after each rebuild -- and silently keeps
# showing the old switch as ON while the running app is denied. A Developer ID
# certificate pins the requirement to Bundle ID + Team ID instead, so one grant
# survives all subsequent rebuilds.
if [[ -z "${CODESIGN_IDENTITY:-}" ]]; then
  DETECTED_IDENTITY="$(
    security find-identity -v -p codesigning 2>/dev/null \
      | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' \
      | head -1
  )"
  if [[ -n "$DETECTED_IDENTITY" ]]; then
    CODESIGN_IDENTITY="$DETECTED_IDENTITY"
    echo "Auto-detected signing identity: $CODESIGN_IDENTITY"
  fi
fi

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  echo "Signing with Developer ID: $CODESIGN_IDENTITY"
  codesign --force --deep --options runtime --timestamp \
    --sign "$CODESIGN_IDENTITY" "$APP_PATH"
  codesign --verify --deep --strict --verbose=2 "$APP_PATH"
else
  echo "WARNING: no Developer ID found -- signing ad-hoc."
  echo "         Camera and Accessibility grants will be lost on every rebuild,"
  echo "         and macOS may keep showing them as enabled while denying access."
  echo "         Install a Developer ID certificate, or pass CODESIGN_IDENTITY."
  codesign --force --deep --sign - "$APP_PATH"
fi

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
  echo "Notarizing via profile: $NOTARY_PROFILE"
  ditto -c -k --keepParent "$APP_PATH" "dist/$APP_NAME.zip"
  xcrun notarytool submit "dist/$APP_NAME.zip" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_PATH"
fi

# --- release gate ------------------------------------------------------------
# A bundle that carries runtime state is broken even though it was just built
# correctly: the app writes its settings and event log under the per-user data
# directory, and any of those files appearing inside Contents/ means a stale
# in-bundle copy got picked up. Worse than the mistake is shipping it silently —
# adding a file to a sealed bundle invalidates the signature, so Gatekeeper
# refuses the next launch and every TCC grant keyed to it is lost.
echo "Verifying the bundle seal..."
STRAY_STATE="$(find "$APP_PATH" \( -name 'settings.json' -o -name 'telemetry.sqlite3*' \
  -o -name '*.corrupt-*' -o -name 'pinchcursor.lock' \) 2>/dev/null || true)"
if [[ -n "$STRAY_STATE" ]]; then
  echo "ERROR: runtime state was bundled inside the app:" >&2
  echo "$STRAY_STATE" >&2
  echo "Remove it before shipping; settings belong in ~/Library/Application Support/$APP_NAME/." >&2
  exit 1
fi

if ! codesign --verify --deep --strict "$APP_PATH"; then
  echo "ERROR: the signature does not verify. The bundle was modified after signing." >&2
  exit 1
fi

if [[ -n "${NOTARY_PROFILE:-}" ]] && ! xcrun stapler validate "$APP_PATH"; then
  echo "ERROR: no notarization ticket is stapled to the bundle." >&2
  exit 1
fi

echo "Seal verified: no runtime state in the bundle, signature intact."
echo "Built: $APP_PATH"

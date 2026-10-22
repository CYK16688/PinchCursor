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
env -u PYTHONPATH "$PYTHON" -m PyInstaller --noconfirm --clean "Gesture Control.spec"

APP_PATH="dist/$APP_NAME.app"
INFO_PLIST="$APP_PATH/Contents/Info.plist"

# Usage strings must exist before signing; they are part of the sealed bundle.
/usr/libexec/PlistBuddy -c "Add :NSCameraUsageDescription string $CAMERA_USAGE" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :NSAccessibilityUsageDescription string $ACCESSIBILITY_USAGE" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string $MIN_VERSION" "$INFO_PLIST"

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  echo "Signing with Developer ID: $CODESIGN_IDENTITY"
  codesign --force --deep --options runtime --timestamp \
    --sign "$CODESIGN_IDENTITY" "$APP_PATH"
  codesign --verify --deep --strict --verbose=2 "$APP_PATH"
else
  echo "Signing ad-hoc (TCC grants reset on every rebuild)."
  codesign --force --deep --sign - "$APP_PATH"
fi

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
  echo "Notarizing via profile: $NOTARY_PROFILE"
  ditto -c -k --keepParent "$APP_PATH" "dist/$APP_NAME.zip"
  xcrun notarytool submit "dist/$APP_NAME.zip" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_PATH"
fi

echo "Built: $APP_PATH"

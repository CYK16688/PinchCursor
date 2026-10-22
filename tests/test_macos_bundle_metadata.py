from app_build.macos_bundle import (
    ACCESSIBILITY_USAGE_DESCRIPTION,
    APP_NAME,
    BUNDLE_ID,
    CAMERA_USAGE_DESCRIPTION,
)


def test_development_bundle_has_a_stable_identity():
    assert APP_NAME == "Gesture Control"
    assert BUNDLE_ID == "com.cyk.gesturecontroller.dev"


def test_development_bundle_declares_camera_and_accessibility_purposes():
    assert CAMERA_USAGE_DESCRIPTION
    assert ACCESSIBILITY_USAGE_DESCRIPTION

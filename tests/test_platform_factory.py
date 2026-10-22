from platform_services.factory import create_platform_services


def test_factory_returns_macos_services_for_darwin():
    services = create_platform_services(system_name="Darwin")

    assert services.capabilities.platform == "macos"
    assert "move_cursor" in services.capabilities.supported_actions


def test_macos_raises_a_camera_prompt_but_windows_does_not():
    """Only macOS has an in-app camera consent prompt the UI can offer."""
    macos = create_platform_services(system_name="Darwin")
    windows = create_platform_services(system_name="Windows")

    assert macos.capabilities.camera_permission_promptable is True
    assert windows.capabilities.camera_permission_promptable is False

from platform_services.windows.ui_context import WindowsUIContextProvider


class UiaNative:
    def role_at_position(self, x, y):
        return "Edit"


def test_windows_edit_role_maps_to_shared_text_input_category():
    context = WindowsUIContextProvider(UiaNative()).get_context(1, 1)

    assert context.category == "text_input"

from platform_services.macos.native import MacOSNativeFacade
from platform_services.macos.ui_context import MacOSUIContextProvider
from platform_services.policy import ContextPolicy
import pytest


@pytest.mark.parametrize(
    "shortcut",
    ("cmd+bogus+p", "bogus+p", "cmd+cmd+p", "cmd+command+p", "cmd+", "+p"),
)
def test_hotkey_parser_rejects_malformed_shortcuts(shortcut):
    with pytest.raises(ValueError):
        MacOSNativeFacade._parse_hotkey(shortcut)


def test_hotkey_parser_normalizes_supported_aliases():
    assert MacOSNativeFacade._parse_hotkey("command + shift + p") == ([55, 56], "p")


def test_malformed_hotkey_posts_no_native_events():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)
    posted = []
    native._post_key = lambda keycode, down: posted.append((keycode, down))

    with pytest.raises(ValueError):
        native.post_hotkey("cmd+bogus+p")

    assert posted == []


def test_input_monitoring_native_access_uses_listen_event_apis(monkeypatch):
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class Quartz:
        @staticmethod
        def CGPreflightListenEventAccess():
            return True

        @staticmethod
        def CGRequestListenEventAccess():
            return False

    native.quartz = Quartz()

    assert native.input_monitoring_trusted() is True
    assert native.request_input_monitoring_prompt() is False


def test_accessibility_prompt_passes_the_documented_option_dictionary():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"

        @staticmethod
        def AXIsProcessTrustedWithOptions(options):
            # Apple documents a CFDictionary carrying the prompt key; PyObjC
            # bridges a plain dict with the CF callbacks it needs.
            assert isinstance(options, dict)
            assert options == {"AXTrustedCheckOptionPrompt": True}
            return False

    native.application_services = ApplicationServices()

    assert native.request_accessibility_prompt() is False


def test_the_privacy_panel_deep_link_targets_the_right_anchor():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)
    opened = []

    class _URL:
        @staticmethod
        def URLWithString_(url):
            return url

    class _Workspace:
        @staticmethod
        def sharedWorkspace():
            class Workspace:
                @staticmethod
                def openURL_(url):
                    opened.append(url)
                    return True

            return Workspace()

    class AppKit:
        NSURL = _URL
        NSWorkspace = _Workspace

    native.appkit = AppKit()

    assert native.open_privacy_settings("accessibility") is True
    assert native.open_privacy_settings("input_monitoring") is True
    assert opened == [
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    ]
    assert native.open_privacy_settings("nonsense") is False


def test_accessibility_serialization_includes_a_bounded_identifier_without_title_or_value():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"

    native.application_services = ApplicationServices()
    values = {
        "role": "AXButton",
        "subrole": "",
        "parent": None,
        "identifier": "x" * 200,
        "title": "Private button title",
        "value": "Private value",
    }
    native._attribute = lambda _element, attribute: values.get(attribute)

    serialized = native._serialize_accessibility_element(object())

    assert serialized["identifier"] == "x" * 128
    assert "title" not in serialized
    assert "value" not in serialized


def test_accessibility_serialization_bounds_the_parent_chain():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"

    native.application_services = ApplicationServices()
    nodes = [{"depth": index} for index in range(20)]
    for index in range(len(nodes) - 1):
        nodes[index]["parent"] = nodes[index + 1]
    nodes[-1]["parent"] = None
    native._attribute = lambda element, attribute: {
        "role": "AXGroup",
        "subrole": "",
        "identifier": str(element["depth"]),
        "parent": element["parent"],
    }.get(attribute)

    serialized = native._serialize_accessibility_element(nodes[0])
    depth = 0
    while serialized.get("parent") is not None:
        depth += 1
        serialized = serialized["parent"]

    assert depth == 8


def test_accessibility_serialization_marks_duplicate_sibling_identifiers_unverified():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

    native.application_services = ApplicationServices()
    parent = {"role": "AXGroup", "subrole": "", "identifier": "container"}
    first = {"role": "AXButton", "subrole": "", "identifier": "shared", "parent": parent}
    second = {"role": "AXButton", "subrole": "", "identifier": "shared", "parent": parent}
    parent["children"] = [first, second]
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(first)

    assert serialized["identifier"] == "shared"
    assert serialized["identity_verified"] is False


def test_categorized_ancestor_with_duplicate_sibling_identifier_is_not_verified():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (0, 420)

    native.application_services = ApplicationServices()
    group = {"role": "AXGroup", "subrole": "", "identifier": "toolbar"}
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": group}
    duplicate = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": group}
    label = {"role": "AXStaticText", "subrole": "", "identifier": "caption", "parent": button}
    group["children"] = [button, duplicate]
    button["children"] = [label]
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(label)

    assert serialized["parent"]["identity_verified"] is False


def test_accessibility_serialization_includes_a_positive_process_identifier():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (0, 420)

    native.application_services = ApplicationServices()
    parent = {"role": "AXGroup", "subrole": "", "identifier": "toolbar"}
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": parent}
    parent["children"] = [button]
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(button)

    assert serialized["process_id"] == 420
    assert serialized["identity_verified"] is True


def test_accessibility_serialization_fails_closed_when_process_identifier_is_unavailable():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (1, 0)

    native.application_services = ApplicationServices()
    parent = {"role": "AXGroup", "subrole": "", "identifier": "toolbar"}
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": parent}
    parent["children"] = [button]
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(button)

    assert serialized["process_id"] is None
    assert serialized["identity_verified"] is False


def test_accessibility_serialization_rejects_a_boolean_process_identifier():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (0, True)

    native.application_services = ApplicationServices()
    parent = {"role": "AXGroup", "subrole": "", "identifier": "toolbar"}
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": parent}
    parent["children"] = [button]
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(button)

    assert serialized["process_id"] is None
    assert serialized["identity_verified"] is False


def test_accessibility_serialization_does_not_verify_a_direct_control_without_parent():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (0, 420)

    native.application_services = ApplicationServices()
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": None}
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(button)

    assert serialized["identity_verified"] is False


def test_verified_native_identity_flows_through_context_provider():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (0, 420)

    native.application_services = ApplicationServices()
    # An AXApplication root is a process-local structural anchor: its process
    # ID is already part of the fingerprint, so it need not masquerade as a
    # sibling-unique control. Every identity-bearing node below it is unique.
    root = {"role": "AXApplication", "subrole": "", "identifier": ""}
    parent = {"role": "AXGroup", "subrole": "", "identifier": "toolbar", "parent": root}
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": parent}
    root["children"] = [parent]
    parent["children"] = [button]
    native._attribute = lambda element, attribute: element.get(attribute)
    native.element_at_position = lambda _x, _y: native._serialize_accessibility_element(button)
    provider = MacOSUIContextProvider(native, ContextPolicy.default())

    first = provider.get_context(10, 10)
    second = provider.get_context(10, 10)

    assert first.category == "clickable"
    assert first.target_id
    assert first.target_id == second.target_id


def test_nested_hit_with_duplicate_categorized_ancestor_fails_closed():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXUIElementGetPid(_element, _pid_out):
            return (0, 420)

    native.application_services = ApplicationServices()
    root = {"role": "AXApplication", "subrole": "", "identifier": ""}
    group = {"role": "AXGroup", "subrole": "", "identifier": "toolbar", "parent": root}
    button = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": group}
    duplicate = {"role": "AXButton", "subrole": "", "identifier": "confirm", "parent": group}
    label = {"role": "AXStaticText", "subrole": "", "identifier": "caption", "parent": button}
    root["children"] = [group]
    group["children"] = [button, duplicate]
    button["children"] = [label]
    native._attribute = lambda element, attribute: element.get(attribute)
    native.element_at_position = lambda _x, _y: native._serialize_accessibility_element(label)
    provider = MacOSUIContextProvider(native, ContextPolicy.default())

    context = provider.get_context(10, 10)

    assert context.category == "clickable"
    assert context.target_id == ""


def test_accessibility_serialization_stops_on_a_cyclic_parent_graph():
    native = MacOSNativeFacade.__new__(MacOSNativeFacade)

    class ApplicationServices:
        kAXRoleAttribute = "role"
        kAXSubroleAttribute = "subrole"
        kAXParentAttribute = "parent"
        kAXIdentifierAttribute = "identifier"
        kAXChildrenAttribute = "children"

    native.application_services = ApplicationServices()
    first = {"role": "AXGroup", "subrole": "", "identifier": "first"}
    second = {"role": "AXGroup", "subrole": "", "identifier": "second", "parent": first}
    first["parent"] = second
    native._attribute = lambda element, attribute: element.get(attribute)

    serialized = native._serialize_accessibility_element(first)

    assert serialized["parent"]["parent"] is None
    assert serialized["identity_path_verified"] is False

from platform_services.macos.ui_context import MacOSUIContextProvider
from platform_services.policy import ContextPolicy


def _trusted_element(role, identifier, *, parent=None, process_id=420):
    return {
        "role": role,
        "subrole": "",
        "identifier": identifier,
        "identity_verified": True,
        "identity_path_verified": True,
        "process_id": process_id,
        "parent": parent,
    }


class AccessibilityNative:
    def element_at_position(self, x, y):
        return _trusted_element("AXTextField", "search-field")


def test_ax_text_field_maps_to_text_input_with_a_stable_verified_identity():
    provider = MacOSUIContextProvider(AccessibilityNative(), ContextPolicy.default())

    first = provider.get_context(15, 20)
    second = provider.get_context(15, 20)

    assert first.category == "text_input"
    assert first.native_role == "AXTextField"
    assert first.target_id
    assert first.target_id == second.target_id


def test_parent_category_uses_a_verified_parent_accessibility_identity():
    class NestedAccessibilityNative:
        def element_at_position(self, x, y):
            return {
                "role": "AXStaticText",
                "subrole": "",
                "identifier": "nested-label",
                "identity_verified": True,
                "identity_path_verified": True,
                "parent": _trusted_element("AXButton", "continue-button"),
            }

    provider = MacOSUIContextProvider(NestedAccessibilityNative(), ContextPolicy.default())

    context = provider.get_context(15, 20)

    assert context.category == "clickable"
    assert context.native_role == "AXButton"
    assert context.target_id


def test_ambiguous_duplicate_identifier_fails_closed_for_contextual_candidates():
    class DuplicateIdentifierNative:
        def element_at_position(self, x, y):
            element = _trusted_element("AXButton", "shared-button-id")
            element["identity_verified"] = False
            return element

    provider = MacOSUIContextProvider(DuplicateIdentifierNative(), ContextPolicy.default())

    context = provider.get_context(15, 20)

    assert context.category == "clickable"
    assert context.target_id == ""


def test_same_control_identifier_in_different_verified_containers_has_distinct_target_ids():
    class SeparateContainersNative:
        def element_at_position(self, x, y):
            container_identifier = "toolbar-a" if x < 50 else "toolbar-b"
            return _trusted_element(
                "AXButton",
                "confirm",
                parent=_trusted_element("AXGroup", container_identifier),
            )

    provider = MacOSUIContextProvider(SeparateContainersNative(), ContextPolicy.default())

    first = provider.get_context(15, 20)
    second = provider.get_context(80, 20)

    assert first.target_id
    assert second.target_id
    assert first.target_id != second.target_id


def test_same_control_identifier_below_distinct_anonymous_containers_fails_closed():
    class AnonymousContainersNative:
        def element_at_position(self, x, y):
            return _trusted_element(
                "AXButton",
                "confirm",
                parent={
                    "role": "AXGroup",
                    "subrole": "",
                    "identifier": "",
                    "identity_verified": True,
                    "identity_path_verified": True,
                    "process_id": 420,
                    "parent": None,
                },
            )

    provider = MacOSUIContextProvider(AnonymousContainersNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_same_control_identifier_below_verified_anonymous_container_fails_closed():
    class AnonymousContainerNative:
        def element_at_position(self, x, y):
            return _trusted_element(
                "AXButton",
                "confirm",
                parent={
                    "role": "AXGroup",
                    "subrole": "",
                    "identifier": "",
                    "identity_verified": True,
                    "identity_path_verified": True,
                    "process_id": 420,
                    "parent": None,
                },
            )

    provider = MacOSUIContextProvider(AnonymousContainerNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_unverified_ancestor_identity_fails_closed_for_contextual_candidates():
    class UnverifiedAncestorNative:
        def element_at_position(self, x, y):
            parent = _trusted_element("AXGroup", "unreadable-container")
            parent["identity_verified"] = False
            return _trusted_element("AXButton", "confirm", parent=parent)

    provider = MacOSUIContextProvider(UnverifiedAncestorNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_cross_process_parent_identity_fails_closed_for_contextual_candidates():
    class CrossProcessParentNative:
        def element_at_position(self, x, y):
            return _trusted_element(
                "AXButton",
                "confirm",
                parent=_trusted_element("AXGroup", "foreign-container", process_id=421),
            )

    provider = MacOSUIContextProvider(CrossProcessParentNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_cross_process_parent_without_identifier_fails_closed_for_contextual_candidates():
    class CrossProcessStructuralParentNative:
        def element_at_position(self, x, y):
            return _trusted_element(
                "AXButton",
                "confirm",
                parent={
                    "role": "AXGroup",
                    "subrole": "",
                    "identifier": "",
                    "identity_verified": False,
                    "identity_path_verified": True,
                    "process_id": 421,
                    "parent": None,
                },
            )

    provider = MacOSUIContextProvider(CrossProcessStructuralParentNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_cyclic_or_truncated_identity_path_fails_closed_for_contextual_candidates():
    class CyclicPathNative:
        def element_at_position(self, x, y):
            element = _trusted_element("AXButton", "confirm")
            element["identity_path_verified"] = False
            return element

    provider = MacOSUIContextProvider(CyclicPathNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_missing_identity_verification_metadata_fails_closed():
    class LegacyNative:
        def element_at_position(self, x, y):
            return {"role": "AXButton", "identifier": "confirm", "parent": None}

    provider = MacOSUIContextProvider(LegacyNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""


def test_boolean_process_identity_fails_closed_for_contextual_candidates():
    class BooleanProcessNative:
        def element_at_position(self, x, y):
            return _trusted_element("AXButton", "confirm", process_id=True)

    provider = MacOSUIContextProvider(BooleanProcessNative(), ContextPolicy.default())

    assert provider.get_context(15, 20).target_id == ""

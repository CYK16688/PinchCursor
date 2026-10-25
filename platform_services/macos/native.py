from __future__ import annotations

from typing import Any

from utils.hotkey_validation import MACOS_KEYCODES, normalize_hotkey


class MacOSNativeFacade:
    """Thin lazy-native bridge used only by macOS platform services."""

    def __init__(self):
        import AppKit
        import ApplicationServices
        import AVFoundation
        import Quartz

        self.appkit = AppKit
        self.application_services = ApplicationServices
        self.avfoundation = AVFoundation
        self.quartz = Quartz

    def accessibility_trusted(self) -> bool:
        return bool(self.application_services.AXIsProcessTrusted())

    def request_accessibility_prompt(self) -> bool:
        """Ask macOS for Accessibility, in the shape Apple documents.

        ``AXIsProcessTrustedWithOptions`` takes a CFDictionary carrying
        ``kAXTrustedCheckOptionPrompt``. Handing it a dictionary built with
        NULL callbacks passes an object that does not own its keys, which is
        both outside the documented contract and a heap-corruption hazard;
        PyObjC bridges a plain dict with the correct CF callbacks.

        The prompt is shown at most once per app identity per login. After
        that the call simply returns false, which is why every caller also
        opens the Privacy pane.
        """
        options = {self.application_services.kAXTrustedCheckOptionPrompt: True}
        return bool(self.application_services.AXIsProcessTrustedWithOptions(options))

    def open_privacy_settings(self, pane: str) -> bool:
        """Open the exact Privacy & Security pane for one service.

        This is the documented fallback: when the prompt has already been
        answered (or suppressed), the switch in System Settings is the only
        way to grant access, and hunting for the right pane is the part users
        get wrong.
        """
        anchors = {
            "camera": "Privacy_Camera",
            "accessibility": "Privacy_Accessibility",
            "input_monitoring": "Privacy_ListenEvent",
        }
        anchor = anchors.get(str(pane))
        if anchor is None:
            return False
        url = f"x-apple.systempreferences:com.apple.preference.security?{anchor}"
        try:
            workspace = self.appkit.NSWorkspace.sharedWorkspace()
            return bool(workspace.openURL_(self.appkit.NSURL.URLWithString_(url)))
        except Exception:  # noqa: BLE001 - a failed deep link must not surface
            return False

    def input_monitoring_trusted(self) -> bool:
        return bool(self.quartz.CGPreflightListenEventAccess())

    def request_input_monitoring_prompt(self) -> bool:
        return bool(self.quartz.CGRequestListenEventAccess())

    @property
    def shortcut_keycodes(self) -> dict[str, int]:
        """Return the shared source-controlled virtual-key table."""
        return dict(MACOS_KEYCODES)

    @property
    def shortcut_modifier_keycodes(self) -> dict[str, frozenset[int]]:
        return {
            "cmd": frozenset({54, 55}),
            "ctrl": frozenset({59, 62}),
            "alt": frozenset({58, 61}),
            "shift": frozenset({56, 60}),
        }

    def create_listen_only_event_tap(self, callback):
        event_mask = (
            (1 << self.quartz.kCGEventKeyDown)
            | (1 << self.quartz.kCGEventKeyUp)
            | (1 << self.quartz.kCGEventFlagsChanged)
        )

        def tap_callback(_proxy, event_type, event, _refcon):
            if event_type == self.quartz.kCGEventTapDisabledByTimeout:
                callback("tap_disabled_timeout")
            elif event_type == self.quartz.kCGEventTapDisabledByUserInput:
                callback("tap_disabled_user_input")
            elif event_type in {
                self.quartz.kCGEventKeyDown,
                self.quartz.kCGEventKeyUp,
                self.quartz.kCGEventFlagsChanged,
            }:
                names = {
                    self.quartz.kCGEventKeyDown: "key_down",
                    self.quartz.kCGEventKeyUp: "key_up",
                    self.quartz.kCGEventFlagsChanged: "flags_changed",
                }
                callback(names[event_type], int(self.quartz.CGEventGetIntegerValueField(
                    event, self.quartz.kCGKeyboardEventKeycode
                )))
            # Returning the original event guarantees this monitor never consumes input.
            return event

        tap = self.quartz.CGEventTapCreate(
            self.quartz.kCGSessionEventTap,
            self.quartz.kCGHeadInsertEventTap,
            self.quartz.kCGEventTapOptionListenOnly,
            event_mask,
            tap_callback,
            None,
        )
        return (tap, tap_callback) if tap is not None else None

    def start_event_tap(self, tap) -> bool:
        event_tap, _callback = tap
        source = self.quartz.CFMachPortCreateRunLoopSource(None, event_tap, 0)
        if source is None:
            return False
        self.quartz.CFRunLoopAddSource(
            self.quartz.CFRunLoopGetMain(), source, self.quartz.kCFRunLoopCommonModes
        )
        self.quartz.CGEventTapEnable(event_tap, True)
        return True

    def stop_event_tap(self, tap) -> None:
        event_tap, _callback = tap
        self.quartz.CGEventTapEnable(event_tap, False)

    def camera_authorization(self) -> str:
        status = self.avfoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            self.avfoundation.AVMediaTypeVideo
        )
        states = {
            self.avfoundation.AVAuthorizationStatusNotDetermined: "not_determined",
            self.avfoundation.AVAuthorizationStatusRestricted: "restricted",
            self.avfoundation.AVAuthorizationStatusDenied: "denied",
            self.avfoundation.AVAuthorizationStatusAuthorized: "authorized",
        }
        return states.get(status, "unavailable")

    def request_camera_access(self, completion) -> None:
        self.avfoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            self.avfoundation.AVMediaTypeVideo,
            completion,
        )

    def list_video_devices(self) -> list[dict[str, object]]:
        devices = self.avfoundation.AVCaptureDevice.devicesWithMediaType_(
            self.avfoundation.AVMediaTypeVideo
        )
        return [
            {
                "unique_id": str(device.uniqueID()),
                "name": str(device.localizedName()),
                "kind": self._camera_kind(device),
                "available": bool(device.isConnected()),
            }
            for device in devices
        ]

    def open_cv_index_for_device(self, device_id: str) -> int | None:
        """Temporary bridge until AVFoundation frame capture replaces OpenCV."""
        devices = self.list_video_devices()
        for index, device in enumerate(devices):
            if device["unique_id"] == device_id and device["available"]:
                return index
        return None

    def _camera_kind(self, device) -> str:
        device_type = str(device.deviceType())
        if device_type == str(self.avfoundation.AVCaptureDeviceTypeContinuityCamera):
            return "continuity"
        if device_type == str(self.avfoundation.AVCaptureDeviceTypeExternalUnknown):
            return "external"
        if "BuiltIn" in device_type:
            return "built_in"
        return "unknown"

    @property
    def status_window_level(self) -> int:
        return int(self.quartz.CGWindowLevelForKey(self.quartz.kCGStatusWindowLevelKey))

    @property
    def collection_behavior(self) -> int:
        return (
            self.appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | self.appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | self.appkit.NSWindowCollectionBehaviorTransient
        )

    def panel_for_widget(self, widget):
        """Return the Cocoa panel backing a shown Qt top-level widget."""
        import objc

        view = objc.objc_object(c_void_p=int(widget.winId()))
        return view.window() if view is not None else None

    def post_mouse(self, event_type: str, x: int, y: int, button: str) -> None:
        event_map = {
            "move": self.quartz.kCGEventMouseMoved,
            "left_down": self.quartz.kCGEventLeftMouseDown,
            "left_up": self.quartz.kCGEventLeftMouseUp,
            "left_dragged": self.quartz.kCGEventLeftMouseDragged,
            "right_down": self.quartz.kCGEventRightMouseDown,
            "right_up": self.quartz.kCGEventRightMouseUp,
            "center_down": self.quartz.kCGEventOtherMouseDown,
            "center_up": self.quartz.kCGEventOtherMouseUp,
        }
        button_map = {
            "left": self.quartz.kCGMouseButtonLeft,
            "right": self.quartz.kCGMouseButtonRight,
            "center": self.quartz.kCGMouseButtonCenter,
        }
        event = self.quartz.CGEventCreateMouseEvent(
            None, event_map[event_type], (x, y), button_map[button]
        )
        self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, event)

    def post_scroll(self, vertical: int, horizontal: int) -> None:
        if horizontal:
            event = self.quartz.CGEventCreateScrollWheelEvent(
                None, self.quartz.kCGScrollEventUnitLine, 2, vertical, horizontal
            )
        else:
            event = self.quartz.CGEventCreateScrollWheelEvent(
                None, self.quartz.kCGScrollEventUnitLine, 1, vertical
            )
        self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, event)

    def post_hotkey(self, hotkey: str) -> None:
        modifiers, key = self._parse_hotkey(hotkey)
        keycode = self._keycode_for(key)
        for modifier in modifiers:
            self._post_key(modifier, True)
        self._post_key(keycode, True)
        self._post_key(keycode, False)
        for modifier in reversed(modifiers):
            self._post_key(modifier, False)

    def element_at_position(self, x: int, y: int) -> dict[str, Any] | None:
        system = self.application_services.AXUIElementCreateSystemWide()
        error, element = self.application_services.AXUIElementCopyElementAtPosition(
            system, x, y, None
        )
        if error != 0 or element is None:
            return None
        return self._serialize_accessibility_element(element)

    def element_box_at_position(self, x: int, y: int) -> dict[str, Any] | None:
        """Return role and frame at a point without identity attestation.

        Point assist only needs geometry, and it probes several points per
        click. Reusing the attested serializer would pay its sibling walkdown
        for every probe, so this stays a deliberately shallow read.
        """
        system = self.application_services.AXUIElementCreateSystemWide()
        error, element = self.application_services.AXUIElementCopyElementAtPosition(
            system, x, y, None
        )
        if error != 0 or element is None:
            return None
        role = self._attribute(element, self.application_services.kAXRoleAttribute)
        enabled = self._attribute(element, self.application_services.kAXEnabledAttribute)
        return {
            "role": str(role or ""),
            "bounds": self._bounds_for_element(element),
            "enabled": True if enabled is None else bool(enabled),
        }

    def _bounds_for_element(self, element: Any) -> tuple[int, int, int, int] | None:
        """Return an element frame in screen points, or None when unavailable.

        Attribute symbols are looked up defensively: test facades and older
        ApplicationServices bindings do not expose the AXValue constants, and a
        missing frame must degrade to "no geometry", never to an exception.
        """
        services = self.application_services
        position_attribute = getattr(services, "kAXPositionAttribute", None)
        size_attribute = getattr(services, "kAXSizeAttribute", None)
        getter = getattr(services, "AXValueGetValue", None)
        point_type = getattr(services, "kAXValueCGPointType", None)
        size_type = getattr(services, "kAXValueCGSizeType", None)
        if None in (position_attribute, size_attribute, getter, point_type, size_type):
            return None
        position = self._attribute(element, position_attribute)
        size = self._attribute(element, size_attribute)
        if position is None or size is None:
            return None
        try:
            point_ok, point = getter(position, point_type, None)
            size_ok, extent = getter(size, size_type, None)
        except (AttributeError, TypeError, ValueError):
            return None
        if not point_ok or not size_ok:
            return None
        width, height = int(extent.width), int(extent.height)
        if width <= 0 or height <= 0:
            return None
        return (int(point.x), int(point.y), width, height)

    def _serialize_accessibility_element(
        self,
        element: Any,
        depth: int = 0,
        seen: set[int] | None = None,
    ) -> dict[str, Any] | None:
        serialized, _identity_path_verified = self._serialize_accessibility_node(
            element, depth, seen, is_target=True
        )
        return serialized

    def _serialize_accessibility_node(
        self,
        element: Any,
        depth: int,
        seen: set[int] | None,
        *,
        is_target: bool,
    ) -> tuple[dict[str, Any] | None, bool]:
        if element is None:
            return None, True
        if depth > 8:
            return None, False
        seen = seen if seen is not None else set()
        element_key = id(element)
        if element_key in seen:
            return None, False
        seen.add(element_key)
        role = self._attribute(element, self.application_services.kAXRoleAttribute)
        subrole = self._attribute(element, self.application_services.kAXSubroleAttribute)
        parent = self._attribute(element, self.application_services.kAXParentAttribute)
        identifier_attribute = getattr(
            self.application_services, "kAXIdentifierAttribute", None
        )
        identifier = self._attribute(element, identifier_attribute) if identifier_attribute else None
        bounded_identifier = identifier[:128] if isinstance(identifier, str) else ""
        process_id = self._process_id_for_element(element)
        serialized_parent, identity_path_verified = self._serialize_accessibility_node(
            parent, depth + 1, seen, is_target=False
        )
        # Every serialized node may later become the categorized ancestor used
        # for contextual dispatch. Require the same bounded sibling uniqueness
        # proof for targets and ancestors; otherwise target identity is unsafe.
        identity_verified = self._has_unique_sibling_identity(
            element, parent, str(role or ""), bounded_identifier
        )
        identity_verified = identity_verified and self._valid_process_id(process_id)
        return {
            "role": str(role or ""),
            "subrole": str(subrole or ""),
            # Identifier is a bounded, non-content fingerprint for live target
            # continuity only. Never serialize labels, values, or text content.
            "identifier": bounded_identifier,
            # Contextual candidates require a unique sibling identity. A
            # repeated AXIdentifier is ambiguous across frames, so callers
            # must fail closed rather than preserve an armed candidate.
            "identity_verified": identity_verified,
            "process_id": process_id,
            # False means the recursive parent walk hit a cycle or depth cap;
            # the provider must not derive contextual identity from a partial
            # structural path.
            "identity_path_verified": identity_path_verified,
            "bounds": self._bounds_for_element(element) if is_target else None,
            "parent": serialized_parent,
        }, identity_path_verified

    def _process_id_for_element(self, element: Any) -> int | None:
        """Return the owning AX process ID, or None when the native query is uncertain."""
        getter = getattr(self.application_services, "AXUIElementGetPid", None)
        if getter is None:
            return None
        try:
            result = getter(element, None)
        except Exception:
            return None
        if not isinstance(result, tuple) or len(result) != 2:
            return None
        error, process_id = result
        if error != 0 or not self._valid_process_id(process_id):
            return None
        return process_id

    @staticmethod
    def _valid_process_id(value: object) -> bool:
        """Accept only genuine positive native process identifiers."""
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    def _has_unique_sibling_identity(
        self,
        element: Any,
        parent: Any,
        role: str,
        identifier: str,
    ) -> bool:
        """Verify a non-content AX identifier is unique among bounded siblings."""
        if not role or not identifier:
            return False
        # Without a parent and a bounded sibling list, the identifier cannot
        # prove that a same-role control is unique. Contextual actions must
        # fail closed; ordinary deterministic pointer controls remain intact.
        if parent is None:
            return False
        children_attribute = getattr(self.application_services, "kAXChildrenAttribute", None)
        if not children_attribute:
            return False
        try:
            children = self._attribute(parent, children_attribute)
        except Exception:
            return False
        if not isinstance(children, (list, tuple)) or not children or len(children) > 64:
            return False

        matches = 0
        identifier_attribute = getattr(self.application_services, "kAXIdentifierAttribute", None)
        for sibling in children:
            try:
                sibling_role = self._attribute(
                    sibling, self.application_services.kAXRoleAttribute
                )
                sibling_identifier = (
                    self._attribute(sibling, identifier_attribute)
                    if identifier_attribute
                    else None
                )
            except Exception:
                return False
            if sibling_role == role and sibling_identifier == identifier:
                matches += 1
                if matches > 1:
                    return False
        # AX sibling queries can materialize a new Python proxy for the same
        # native element, so Python object identity cannot prove membership.
        # A complete sibling list with exactly one matching role/identifier is
        # the safe native-level uniqueness proof.
        return matches == 1

    def _attribute(self, element: Any, attribute: str) -> Any:
        error, value = self.application_services.AXUIElementCopyAttributeValue(element, attribute, None)
        return value if error == 0 else None

    def _post_key(self, keycode: int, down: bool) -> None:
        event = self.quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, event)

    @staticmethod
    def _parse_hotkey(hotkey: str) -> tuple[list[int], str]:
        normalized = normalize_hotkey(hotkey)
        parts = normalized.split("+")
        modifier_codes = {"cmd": 55, "ctrl": 59, "alt": 58, "shift": 56}
        return [modifier_codes[token] for token in parts[:-1]], parts[-1]

    @staticmethod
    def _keycode_for(key: str) -> int:
        try:
            return MACOS_KEYCODES[key]
        except KeyError as exc:
            raise ValueError("Unsupported macOS shortcut key") from exc

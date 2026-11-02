import AppKit
import ApplicationServices
import Carbon
import CoreGraphics
import CryptoKit

/// Keyboard targets share SystemControl's principal/worker-bound AX store.
@MainActor
enum SystemKeyboard {
    static let maxValueBytes = 4 * 1024 * 1024
    struct Field {
        let value: String
        let selection: CFRange
        let metadata: [String: Any]
    }
    struct Snapshot {
        let application: NSRunningApplication
        let window: AXUIElement
        let element: AXUIElement
        let field: Field
        let response: [String: Any]
    }
    static func require(_ condition: Bool, _ message: String) throws {
        guard condition else { throw SystemControl.failure("keyboard_unsupported", message) }
    }
    static func timeout(_ element: AXUIElement) throws {
        try require(AXUIElementSetMessagingTimeout(element, 1.0) == .success,
                    "Keyboard AX timeout could not be configured")
    }
    static func observeField(prepare: () throws -> Void,
                             read: (String) -> CFTypeRef?) throws -> Field {
        try prepare()
        let role = read(kAXRoleAttribute) as? String
        let subrole = read(kAXSubroleAttribute) as? String
        try require(["AXTextField", "AXTextArea"].contains(role ?? "")
                    && ["", "AXSearchField"].contains(subrole ?? "unknown"),
                    "Secure or unknown keyboard field is unsupported")
        try require((read(kAXEnabledAttribute) as? NSNumber)?.boolValue == true
                    && (read(kAXFocusedAttribute) as? NSNumber)?.boolValue == true,
                    "Keyboard field is not enabled and focused")
        guard let count = read(kAXNumberOfCharactersAttribute) as? NSNumber,
              CFGetTypeID(count) != CFBooleanGetTypeID(), count.doubleValue.isFinite,
              count.doubleValue == Double(count.intValue), count.intValue >= 0,
              count.intValue <= maxValueBytes / 2,
              let rawRange = read(kAXSelectedTextRangeAttribute),
              CFGetTypeID(rawRange) == AXValueGetTypeID() else {
            throw SystemControl.failure("keyboard_unsupported", "Bounded UTF-16 field metadata is unavailable")
        }
        let wrapped = unsafeBitCast(rawRange, to: AXValue.self)
        var selection = CFRange()
        try require(AXValueGetType(wrapped) == .cfRange
                    && AXValueGetValue(wrapped, .cfRange, &selection)
                    && selection.location >= 0 && selection.length >= 0
                    && selection.location <= count.intValue
                    && selection.length <= count.intValue - selection.location,
                    "Keyboard UTF-16 selection is invalid")
        guard let value = read(kAXValueAttribute) as? String else {
            throw SystemControl.failure("keyboard_unsupported", "Readable keyboard field value is unavailable")
        }
        try require(value.utf8.count <= maxValueBytes,
                    "Keyboard field exceeds the value byte limit")
        let units = Array(value.utf16)
        try require(units.count == count.intValue,
                    "Keyboard field exceeds the value limit or UTF-16 metadata changed")
        for offset in [selection.location, selection.location + selection.length] where offset > 0 && offset < units.count {
            try require(!(0xD800...0xDBFF).contains(units[offset - 1])
                        || !(0xDC00...0xDFFF).contains(units[offset]),
                        "Keyboard selection splits a UTF-16 surrogate pair")
        }
        return Field(value: value, selection: selection, metadata: [
            "role": role!, "subrole": subrole!, "focused": true, "enabled": true,
            "secure": false, "value_utf8_bytes": value.utf8.count,
            "value_utf16_units": units.count, "value_sha256_encoding": "utf-8",
            "value_sha256": SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined(),
            "selection_utf16": ["location": selection.location, "length": selection.length],
        ])
    }
    static func inputSource() throws -> [String: Any] {
        guard let source = TISCopyCurrentKeyboardInputSource()?.takeRetainedValue(),
              let layout = TISCopyCurrentKeyboardLayoutInputSource()?.takeRetainedValue(),
              let sourceID = TISGetInputSourceProperty(source, kTISPropertyInputSourceID),
              let layoutID = TISGetInputSourceProperty(layout, kTISPropertyInputSourceID) else {
            throw SystemControl.failure("keyboard_unsupported", "Current input source/layout is unavailable")
        }
        let sourceText = Unmanaged<CFString>.fromOpaque(sourceID).takeUnretainedValue() as String
        let layoutText = Unmanaged<CFString>.fromOpaque(layoutID).takeUnretainedValue() as String
        try require(!sourceText.isEmpty && !layoutText.isEmpty
                    && sourceText.utf8.count <= 1024 && layoutText.utf8.count <= 1024,
                    "Current input source/layout identity is invalid")
        return ["input_source_id": sourceText, "layout_id": layoutText,
                "keyboard_type": Int(LMGetKbdType())]
    }
    static func revision(application: [String: Any], window: String, element: String,
                         field: Field, layout: [String: Any]) throws -> String {
        try SystemControl.hash(["application": application, "window_token": window,
                                "field_token": element, "field": field.metadata, "layout": layout])
    }
    static func snapshot(_ args: [String: Any]) throws -> Snapshot {
        // Reuse protection checks without performing a mutation or changing focus.
        let app = try SystemControl.target(args, mutating: true)
        try SystemControl.axGranted()
        let root = AXUIElementCreateApplication(app.processIdentifier)
        try timeout(root)
        func focused() throws -> (AXUIElement, AXUIElement) {
            try require(app.isActive
                        && (SystemControl.attribute(root, kAXFrontmostAttribute) as? NSNumber)?.boolValue == true,
                        "Keyboard app is not frontmost")
            guard let window = SystemControl.attribute(root, kAXFocusedWindowAttribute),
                  let element = SystemControl.attribute(root, kAXFocusedUIElementAttribute),
                  CFGetTypeID(window) == AXUIElementGetTypeID(),
                  CFGetTypeID(element) == AXUIElementGetTypeID() else {
                throw SystemControl.failure("keyboard_unsupported", "Exact focused window/field is unavailable")
            }
            return (unsafeBitCast(window, to: AXUIElement.self), unsafeBitCast(element, to: AXUIElement.self))
        }
        let (window, element) = try focused()
        for target in [window, element] {
            try timeout(target)
            try SystemControl.checkElementOwner(target, pid: app.processIdentifier)
        }
        try require(SystemControl.string(window, kAXRoleAttribute) == "AXWindow"
                    && (SystemControl.attribute(window, kAXMinimizedAttribute) as? NSNumber)?.boolValue == false,
                    "Focused keyboard window is unavailable")
        guard let ownerWindow = SystemControl.attribute(element, kAXWindowAttribute),
              CFGetTypeID(ownerWindow) == AXUIElementGetTypeID(),
              CFEqual(ownerWindow, window) else {
            throw SystemControl.failure("keyboard_unsupported", "Focused field/window ownership is unavailable")
        }
        let field = try observeField(prepare: { try timeout(element) },
                                     read: { SystemControl.attribute(element, $0) })
        let layout = try inputSource(), application = try SystemControl.appIdentity(app)
        let windowToken = try SystemControl.remember(window, app: app)
        let token = try SystemControl.remember(element, app: app)
        let before = try revision(application: application, window: windowToken,
                                  element: token, field: field, layout: layout)
        _ = try SystemControl.target(args, mutating: true)
        let (finalWindow, finalElement) = try focused()
        let finalField = try observeField(prepare: { try timeout(element) },
                                          read: { SystemControl.attribute(element, $0) })
        try require(CFEqual(finalWindow, window) && CFEqual(finalElement, element)
                    && before == revision(application: SystemControl.appIdentity(app), window: windowToken,
                                          element: token, field: finalField, layout: inputSource()),
                    "Keyboard focus, field, selection or layout changed during inspection")
        let target: [String: Any] = ["pid": Int(app.processIdentifier),
            "expected_started_at": application["started_at"]!, "target_token": token,
            "helper_pid": Int(getpid()), "worker_generation": SystemBridgeRuntime.generation,
            "expected_revision": before]
        return Snapshot(application: app, window: window, element: element, field: field, response: [
            "target": target, "application": application, "window_token": windowToken,
            "field": field.metadata, "layout": layout,
            "permissions": ["accessibility": true, "post_events": CGPreflightPostEventAccess()],
            "supported": true, "input_attempted": false, "permission_requested": false, "effect": "none",
        ])
    }
    static let namedKeys: [String: CGKeyCode] = [
        "enter": CGKeyCode(kVK_Return), "keypad_enter": CGKeyCode(kVK_ANSI_KeypadEnter),
        "escape": CGKeyCode(kVK_Escape), "tab": CGKeyCode(kVK_Tab), "space": CGKeyCode(kVK_Space),
        "backspace": CGKeyCode(kVK_Delete), "delete": CGKeyCode(kVK_ForwardDelete),
        "left": CGKeyCode(kVK_LeftArrow), "right": CGKeyCode(kVK_RightArrow),
        "up": CGKeyCode(kVK_UpArrow), "down": CGKeyCode(kVK_DownArrow),
        "home": CGKeyCode(kVK_Home), "end": CGKeyCode(kVK_End),
        "page_up": CGKeyCode(kVK_PageUp), "page_down": CGKeyCode(kVK_PageDown),
        "f1": CGKeyCode(kVK_F1), "f2": CGKeyCode(kVK_F2), "f3": CGKeyCode(kVK_F3),
        "f4": CGKeyCode(kVK_F4), "f5": CGKeyCode(kVK_F5), "f6": CGKeyCode(kVK_F6),
        "f7": CGKeyCode(kVK_F7), "f8": CGKeyCode(kVK_F8), "f9": CGKeyCode(kVK_F9),
        "f10": CGKeyCode(kVK_F10), "f11": CGKeyCode(kVK_F11), "f12": CGKeyCode(kVK_F12),
    ]
    static func namedKey(_ key: [String: Any]) throws -> (String, CGKeyCode) {
        guard let name = key["named"] as? String, let code = namedKeys[name],
              key.allSatisfy({ $0.key == "named" ||
                  (["character", "key_code"].contains($0.key) && $0.value is NSNull) }) else {
            throw SystemControl.failure("keyboard_unsupported", "Only one supported named key is available")
        }
        return (name, code)
    }
    static func matchingBinding(_ expected: [String: Any], _ current: [String: Any]) throws {
        for key in ["pid", "expected_started_at", "target_token", "helper_pid", "worker_generation", "expected_revision"] {
            guard let old = expected[key] as? NSObject, let fresh = current[key] as? NSObject,
                  old.isEqual(fresh) else {
                throw SystemControl.failure("macos_element_changed", "Keyboard target or revision changed")
            }
        }
    }
    static func boundSnapshot(_ target: [String: Any]) throws -> Snapshot {
        let app = try SystemControl.target(target, mutating: true)
        try SystemControl.axGranted()
        var reference = target
        reference["element_token"] = target["target_token"]
        // Authenticate expiry/principal/worker BEFORE snapshot.remember can refresh an entry.
        let original = try SystemControl.element(reference, app: app)
        let current = try snapshot(target)
        try matchingBinding(target, current.response["target"] as? [String: Any] ?? [:])
        try require(CFEqual(original, current.element), "Keyboard focused element changed")
        return current
    }
    static func inputAllowed(postAccess: Bool, flags: CGEventFlags, keyHeld: Bool) throws {
        guard postAccess else {
            throw SystemControl.failure("macos_permission_denied", "Native event post access is absent; no request was made")
        }
        try require(flags.intersection([.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn]).isEmpty
                    && !keyHeld, "Held user keys or modifiers conflict with this key pair")
    }
    /// The callback is an attempted native post, not a processing acknowledgement.
    static func postPair(validate: () throws -> Void, sameGeneration: () -> Bool,
                         post: (Bool) throws -> Void) throws -> [String: Any] {
        try validate()
        try require(sameGeneration(), "Keyboard application generation changed before input")
        do {
            try post(true)
            try require(sameGeneration(), "Keyboard application generation changed after key down")
            try post(false)
            return ["scope": "native_post_calls", "post_calls_returned": 2,
                    "input_attempted": true, "app_processing_confirmed": false,
                    "permission_requested": false, "effect": "keyboard_events_dispatched"]
        } catch {
            // Only our own nonmodifier key is released, and never into a reused PID.
            if sameGeneration() { try? post(false) }
            throw SystemControl.failure("keyboard_input_unknown",
                "Keyboard post attempt is uncertain; no replay is permitted", unknown: true)
        }
    }
    static func key(_ args: [String: Any]) throws -> [String: Any] {
        guard let target = args["target"] as? [String: Any], let spec = args["key"] as? [String: Any] else {
            throw SystemControl.failure("invalid_arguments", "Keyboard key requires an exact target and named key")
        }
        let (name, code) = try namedKey(spec)
        guard let source = CGEventSource(stateID: .privateState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else {
            throw SystemControl.failure("keyboard_unsupported", "Native key pair could not be created")
        }
        for event in [down, up] {
            event.flags = []
            event.setIntegerValueField(.keyboardEventAutorepeat, value: 0)
        }
        var result = try postPair(validate: {
            _ = try boundSnapshot(target)
            try inputAllowed(postAccess: CGPreflightPostEventAccess(),
                flags: CGEventSource.flagsState(.combinedSessionState),
                keyHeld: CGEventSource.keyState(.hidSystemState, key: code))
        }, sameGeneration: { (try? SystemControl.target(target)) != nil }, post: { isDown in
            // Last generation check immediately before every post, including cleanup.
            let app = try SystemControl.target(target)
            (isDown ? down : up).postToPid(app.processIdentifier)
        })
        result["requested"] = ["named": name]
        return result
    }
    static func handle(_ operation: String, arguments: [String: Any]) throws -> [String: Any]? {
        switch operation {
        case "keyboard.inspect": return try snapshot(arguments).response
        case "keyboard.key": return try key(arguments)
        default: return nil
        }
    }
}

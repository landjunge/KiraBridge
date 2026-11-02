import AppKit
import ApplicationServices
import Carbon
import CoreGraphics
import CryptoKit

/// Read-only keyboard targets share SystemControl's principal/worker-bound AX store.
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
    static func handle(_ operation: String, arguments: [String: Any]) throws -> [String: Any]? {
        guard operation == "keyboard.inspect" else { return nil }
        return try snapshot(arguments).response
    }
}

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
    struct Context {
        let field: Field?
        let metadata: [String: Any]
    }
    struct Snapshot {
        let application: NSRunningApplication
        let window: AXUIElement
        let element: AXUIElement
        let field: Field?
        let response: [String: Any]
    }
    static func require(_ condition: Bool, _ message: String) throws {
        guard condition else { throw SystemControl.failure("keyboard_unsupported", message) }
    }
    static func timeout(_ element: AXUIElement) throws {
        try require(AXUIElementSetMessagingTimeout(element, 1.0) == .success,
                    "Keyboard AX timeout could not be configured")
    }
    static func optionalSubrole(status: AXError, value: CFTypeRef?) throws -> CFTypeRef? {
        switch status {
        case .success:
            try require(value == nil || value is String, "Keyboard subrole has an invalid value")
            return value
        case .attributeUnsupported, .noValue: return nil
        default: throw SystemControl.failure("keyboard_unsupported", "Keyboard subrole observation failed")
        }
    }
    static func subrole(_ element: AXUIElement) throws -> CFTypeRef? {
        try timeout(element)
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &value)
        return try optionalSubrole(status: status, value: value)
    }
    static func textClassification(role: String?, subrole: String?) -> Bool {
        ["AXTextField", "AXTextArea"].contains(role ?? "")
            && (subrole == "" || subrole == "AXSearchField" || (role == "AXTextArea" && subrole == nil))
    }
    /// A key pair needs an exact focused element, not a readable editable value.
    static func observeContext(prepare: () throws -> Void,
                               read: (String) -> CFTypeRef?) throws -> Context {
        try prepare()
        guard let role = read(kAXRoleAttribute) as? String,
              role.range(of: "\\AAX[A-Za-z0-9]{1,126}\\z", options: .regularExpression) != nil else {
            throw SystemControl.failure("keyboard_unsupported", "Reliable keyboard focus role is unavailable")
        }
        let rawSubrole = read(kAXSubroleAttribute)
        let subrole = rawSubrole as? String
        try require(rawSubrole == nil || (subrole != nil && subrole!.utf8.count <= 128),
                    "Keyboard focus subrole is invalid")
        try require(!role.contains("Secure") && !(subrole?.contains("Secure") ?? false)
                    && (read("AXProtectedContent") as? NSNumber)?.boolValue != true,
                    "Protected keyboard focus is unsupported")
        let rawFocused = read(kAXFocusedAttribute)
        let focused = rawFocused as? NSNumber
        try require(rawFocused == nil || focused != nil, "Keyboard focused state is invalid")
        // The surrounding snapshot proves focus using AXFocusedUIElement identity.
        // Some non-text elements omit their own optional focused attribute.
        try require(focused?.boolValue != false, "Keyboard element is not focused")
        let rawEnabled = read(kAXEnabledAttribute)
        let enabled = rawEnabled as? NSNumber
        try require(rawEnabled == nil || enabled != nil, "Keyboard enabled state is invalid")
        try require(enabled?.boolValue != false, "Keyboard element is disabled")
        var metadata: [String: Any] = ["role": role, "subrole": subrole as Any? ?? NSNull(),
            "focused": focused.map { $0.boolValue } as Any? ?? NSNull(),
            "enabled": enabled.map { $0.boolValue } as Any? ?? NSNull(),
            "secure": NSNull(), "text_supported": false]
        // Missing/unsupported text metadata must not prevent a non-text key command.
        // Only the established strict observer may read an eligible field's value.
        if textClassification(role: role, subrole: subrole) {
            do {
                let field = try observeField(prepare: {}, read: read)
                metadata = field.metadata
                metadata["text_supported"] = true
                return Context(field: field, metadata: metadata)
            } catch let error as SystemBridgeFailure where error.code == "keyboard_unsupported" && !error.effectUnknown {
                // Text remains unavailable; no input has been attempted.
                let currentFocused = read(kAXFocusedAttribute)
                try require(read(kAXRoleAttribute) as? String == role
                            && read(kAXSubroleAttribute) as? String == subrole
                            && (currentFocused == nil || currentFocused is NSNumber)
                            && (currentFocused as? NSNumber)?.boolValue != false
                            && (read(kAXEnabledAttribute) as? NSNumber)?.boolValue != false
                            && (read("AXProtectedContent") as? NSNumber)?.boolValue != true,
                            "Keyboard classification changed during text capability observation")
            }
        }
        return Context(field: nil, metadata: metadata)
    }
    static func requireField(_ field: Field?) throws -> Field {
        guard let field = field else {
            throw SystemControl.failure("keyboard_unsupported", "Exact readable text field metadata is unavailable")
        }
        return field
    }
    static func observeField(prepare: () throws -> Void,
                             read: (String) -> CFTypeRef?) throws -> Field {
        try prepare()
        let role = read(kAXRoleAttribute) as? String
        let rawSubrole = read(kAXSubroleAttribute), subrole = rawSubrole as? String
        try require((rawSubrole == nil || subrole != nil) && textClassification(role: role, subrole: subrole),
                    "Secure or unknown keyboard field is unsupported")
        try require((read("AXProtectedContent") as? NSNumber)?.boolValue != true,
                    "Protected keyboard field is unsupported")
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
            "role": role!, "subrole": subrole as Any? ?? NSNull(), "focused": true, "enabled": true,
            "secure": false, "value_utf8_bytes": value.utf8.count,
            "value_utf16_units": units.count, "value_sha256_encoding": "utf-8",
            "value_sha256": SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined(),
            "selection_utf16": ["location": selection.location, "length": selection.length],
        ])
    }
    struct Layout {
        let metadata: [String: Any]
        let translate: (CGKeyCode, CGEventFlags) -> String?
    }
    static func translate(_ data: CFData, code: CGKeyCode, flags: CGEventFlags,
                          keyboardType: UInt32) -> String? {
        guard CFDataGetLength(data) >= MemoryLayout<UCKeyboardLayout>.size,
              let bytes = CFDataGetBytePtr(data) else { return nil }
        var modifiers: UInt32 = 0, dead: UInt32 = 0, count = 0
        // Control changes the command, not the logical key label.
        for (flag, carbon) in [(CGEventFlags.maskCommand, cmdKey), (.maskShift, shiftKey), (.maskAlternate, optionKey)] {
            if flags.contains(flag) { modifiers |= UInt32(carbon) }
        }
        var units = [UniChar](repeating: 0, count: 8)
        let status = UCKeyTranslate(UnsafeRawPointer(bytes).assumingMemoryBound(to: UCKeyboardLayout.self),
            code, UInt16(kUCKeyActionDown), modifiers >> 8, keyboardType, 0, &dead, units.count, &count, &units)
        // A dead key is not a directly generated character; never resolve a sequence as one pair.
        guard status == noErr, dead == 0, count > 0, count <= units.count else { return nil }
        let text = String(decoding: units.prefix(count), as: UTF16.self)
        return Array(text.utf16) == Array(units.prefix(count)) ? text : nil
    }
    static func currentLayout() throws -> Layout {
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
        let keyboardType = UInt32(LMGetKbdType())
        var data: CFData?
        if let raw = TISGetInputSourceProperty(layout, kTISPropertyUnicodeKeyLayoutData) {
            let value = Unmanaged<CFData>.fromOpaque(raw).takeUnretainedValue()
            if CFDataGetLength(value) <= maxValueBytes { data = value }
        }
        let digest = data.map { SHA256.hash(data: $0 as Data).map { String(format: "%02x", $0) }.joined() } ?? ""
        return Layout(metadata: ["input_source_id": sourceText, "layout_id": layoutText,
            "keyboard_type": Int(keyboardType), "layout_sha256": digest], translate: { code, flags in
                guard sourceText == layoutText, let data = data else { return nil }
                return translate(data, code: code, flags: flags, keyboardType: keyboardType)
            })
    }
    static func inputSource() throws -> [String: Any] { try currentLayout().metadata }
    static func revision(application: [String: Any], window: String, element: String,
                         field: Field, layout: [String: Any]) throws -> String {
        try revision(application: application, window: window, element: element,
                     metadata: field.metadata, layout: layout)
    }
    static func revision(application: [String: Any], window: String, element: String,
                         metadata: [String: Any], layout: [String: Any]) throws -> String {
        try SystemControl.hash(["application": application, "window_token": window,
                                "field_token": element, "field": metadata, "layout": layout])
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
        func context() throws -> Context {
            let observedSubrole = try subrole(element)
            return try observeContext(prepare: {
                try timeout(element)
                try require(!SystemControl.secure(element), "Secure keyboard focus is unsupported")
            }, read: { $0 == kAXSubroleAttribute ? observedSubrole : SystemControl.attribute(element, $0) })
        }
        let observed = try context()
        let layout = try inputSource(), application = try SystemControl.appIdentity(app)
        let windowToken = try SystemControl.remember(window, app: app)
        let token = try SystemControl.remember(element, app: app)
        let before = try revision(application: application, window: windowToken,
                                  element: token, metadata: observed.metadata, layout: layout)
        _ = try SystemControl.target(args, mutating: true)
        let (finalWindow, finalElement) = try focused()
        let finalContext = try context()
        try require(CFEqual(finalWindow, window) && CFEqual(finalElement, element)
                    && before == revision(application: SystemControl.appIdentity(app), window: windowToken,
                                          element: token, metadata: finalContext.metadata, layout: inputSource()),
                    "Keyboard focus, field, selection or layout changed during inspection")
        let target: [String: Any] = ["pid": Int(app.processIdentifier),
            "expected_started_at": application["started_at"]!, "target_token": token,
            "helper_pid": Int(getpid()), "worker_generation": SystemBridgeRuntime.generation,
            "expected_revision": before]
        return Snapshot(application: app, window: window, element: element, field: observed.field, response: [
            "target": target, "application": application, "window_token": windowToken,
            "field": observed.metadata, "layout": layout,
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
    static let modifierFlags: [(String, CGEventFlags)] = [
        ("command", .maskCommand), ("control", .maskControl), ("option", .maskAlternate), ("shift", .maskShift),
    ]
    // Ordinary ANSI/ISO positions (0...50), named keys, printable keypad and JIS positions only.
    // Modifier/CapsLock/Fn/media/language-switch/power positions are deliberately absent.
    static let physicalKeys = Set((0...50).map { CGKeyCode($0) }).union(namedKeys.values).union([
        kVK_ANSI_KeypadDecimal, kVK_ANSI_KeypadMultiply, kVK_ANSI_KeypadPlus, kVK_ANSI_KeypadDivide,
        kVK_ANSI_KeypadMinus, kVK_ANSI_KeypadEquals, kVK_ANSI_Keypad0, kVK_ANSI_Keypad1,
        kVK_ANSI_Keypad2, kVK_ANSI_Keypad3, kVK_ANSI_Keypad4, kVK_ANSI_Keypad5, kVK_ANSI_Keypad6,
        kVK_ANSI_Keypad7, kVK_ANSI_Keypad8, kVK_ANSI_Keypad9, kVK_JIS_Yen, kVK_JIS_Underscore,
        kVK_JIS_KeypadComma,
    ].map { CGKeyCode($0) })
    struct ResolvedKey {
        let code: CGKeyCode
        let flags: CGEventFlags
        let representation: String
    }
    static func resolve(_ spec: [String: Any], modifiers: [String], layout: Layout) throws -> ResolvedKey {
        try require(modifiers.count <= 4 && Set(modifiers).count == modifiers.count
                    && modifiers.allSatisfy { name in modifierFlags.contains { $0.0 == name } },
                    "Keyboard modifiers are unsupported or duplicated")
        let flags = modifierFlags.reduce(CGEventFlags()) { modifiers.contains($1.0) ? $0.union($1.1) : $0 }
        let values = spec.filter { !($0.value is NSNull) }
        try require(values.count == 1, "Choose exactly one keyboard key representation")
        if values["named"] != nil {
            let (_, code) = try namedKey(spec)
            return ResolvedKey(code: code, flags: flags, representation: "named")
        }
        if let number = values["key_code"] as? NSNumber,
           CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite,
           number.doubleValue == Double(number.intValue), number.intValue >= 0, number.intValue <= 127 {
            let code = CGKeyCode(number.intValue)
            try require(physicalKeys.contains(code), "Physical modifier/system key is unsupported")
            return ResolvedKey(code: code, flags: flags, representation: "physical")
        }
        guard let character = values["character"] as? String, character.unicodeScalars.count == 1,
              let scalar = character.unicodeScalars.first, !CharacterSet.controlCharacters.contains(scalar) else {
            throw SystemControl.failure("keyboard_unsupported", "Logical key must be one supported Unicode scalar")
        }
        let letter = CharacterSet.letters.contains(scalar)
        // Letters name a BASE KEY: case-insensitive, never an implicit Shift (Cmd+Z is not Redo).
        // Explicit Shift/Option/Control remain on the posted chord, outside this base-label lookup.
        let base = letter ? flags.intersection(.maskCommand) : flags.subtracting(.maskControl)
        let additions: [CGEventFlags] = letter ? [[]] : [[], .maskShift, .maskAlternate, [.maskShift, .maskAlternate]]
        var matches: [(CGKeyCode, CGEventFlags, Int)] = []
        var seen: Set<UInt64> = []
        for addition in additions {
            let lookup = base.union(addition)
            guard seen.insert(lookup.rawValue).inserted else { continue }
            let extra = addition.subtracting(base).rawValue.nonzeroBitCount
            // Logical glyphs use ordinary positions; keypad ambiguity requires an explicit physical code.
            for code in (0...50).map({ CGKeyCode($0) }) {
                guard let text = layout.translate(code, lookup) else { continue }
                if letter ? text.lowercased() == character.lowercased() : text == character {
                    matches.append((code, flags.union(addition), extra))
                }
            }
        }
        guard let least = matches.map({ $0.2 }).min(), matches.filter({ $0.2 == least }).count == 1,
              let match = matches.first(where: { $0.2 == least }) else {
            throw SystemControl.failure("keyboard_unsupported", "Logical key is absent or ambiguous in the current layout")
        }
        return ResolvedKey(code: match.0, flags: match.1, representation: "logical")
    }
    static func matchingLayout(_ expected: [String: Any], _ current: [String: Any]) throws {
        try require(SystemControl.hash(expected) == SystemControl.hash(current), "Keyboard layout changed before input")
    }
    static func matchingBinding(_ expected: [String: Any], _ current: [String: Any], revision: Bool = true) throws {
        for key in ["pid", "expected_started_at", "target_token", "helper_pid", "worker_generation", "expected_revision"] {
            if key == "expected_revision" && !revision { continue }
            guard let old = expected[key] as? NSObject, let fresh = current[key] as? NSObject,
                  old.isEqual(fresh) else {
                throw SystemControl.failure("macos_element_changed", "Keyboard target or revision changed")
            }
        }
    }
    static func boundSnapshot(_ target: [String: Any], revision: Bool = true) throws -> Snapshot {
        let app = try SystemControl.target(target, mutating: true)
        try SystemControl.axGranted()
        var reference = target
        reference["element_token"] = target["target_token"]
        // Authenticate expiry/principal/worker BEFORE snapshot.remember can refresh an entry.
        let original = try SystemControl.element(reference, app: app)
        let current = try snapshot(target)
        try matchingBinding(target, current.response["target"] as? [String: Any] ?? [:], revision: revision)
        try require(CFEqual(original, current.element), "Keyboard focused element changed")
        return current
    }
    static func inputAllowed(postAccess: Bool, flags: CGEventFlags, keyHeld: Bool) throws {
        guard postAccess else {
            throw SystemControl.failure("macos_permission_denied", "Native event post access is absent; no request was made")
        }
        let conflict = flags.intersection([.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn])
        try require(conflict.isEmpty && !keyHeld,
                    "Held user keys or modifiers conflict with this key pair (conflict_mask=\(conflict.rawValue), key_held=\(keyHeld))")
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
    static func events(_ layout: [String: Any], code: CGKeyCode,
                       flags: CGEventFlags) throws -> (CGEvent, CGEvent) {
        guard let type = layout["keyboard_type"] as? NSNumber,
              CFGetTypeID(type) != CFBooleanGetTypeID(), type.doubleValue.isFinite,
              type.doubleValue >= 0, type.doubleValue <= Double(UInt32.max),
              type.doubleValue.rounded(.towardZero) == type.doubleValue,
              let source = CGEventSource(stateID: .privateState),
              let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else {
            throw SystemControl.failure("keyboard_unsupported", "Bounded native keyboard type or event source is unavailable")
        }
        for event in [down, up] {
            event.flags = flags
            event.setIntegerValueField(.keyboardEventAutorepeat, value: 0)
            event.setIntegerValueField(.keyboardEventKeyboardType, value: Int64(type.doubleValue))
            try require(event.getIntegerValueField(.keyboardEventKeyboardType) == Int64(type.doubleValue),
                        "Native key event did not retain its bound keyboard type")
        }
        return (down, up)
    }
    static func profileString(_ value: Any?, pattern: String, maxBytes: Int) -> Bool {
        guard let text = value as? String, text.utf8.count <= maxBytes else { return false }
        return text.range(of: "\\A(?:" + pattern + ")\\z", options: .regularExpression) != nil
    }
    static func profileContext(_ value: Any?, application: [String: Any], layout: [String: Any],
                               field: [String: Any]) throws -> [String: Any] {
        let invalid = SystemControl.failure("keyboard_profile_context_invalid", "Private profile context is invalid")
        guard let context = value as? [String: Any], Set(context.keys) == Set(["id", "revision", "action", "app"]),
              profileString(context["id"], pattern: "[a-z][a-z0-9_-]{0,63}", maxBytes: 64),
              stageHex(context["revision"], length: 64),
              profileString(context["action"], pattern: "[a-z][a-z0-9_.-]{0,79}", maxBytes: 80),
              let raw = context["app"] as? [String: Any],
              Set(raw.keys).isSubset(of: Set(["bundle_id", "version", "build", "signing_team_id", "language", "layout_id", "keyboard_type", "field_roles"])) else { throw invalid }
        // ProfileApp's optional null values are unconstrained; no unknown keys are accepted.
        let constraints = raw.filter { !($0.value is NSNull) }
        guard profileString(constraints["bundle_id"], pattern: "[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+", maxBytes: 255) else { throw invalid }
        for key in ["version", "build", "language", "layout_id"] where constraints[key] != nil {
            guard profileString(constraints[key], pattern: "[A-Za-z0-9_.+-]+", maxBytes: 128) else { throw invalid }
        }
        if let team = constraints["signing_team_id"], !profileString(team, pattern: "[A-Z0-9]{10}", maxBytes: 10) { throw invalid }
        if let type = constraints["keyboard_type"] {
            guard let number = type as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite,
                  number.doubleValue >= 0, number.doubleValue <= Double(UInt32.max), number.doubleValue.rounded(.towardZero) == number.doubleValue else { throw invalid }
        }
        if let value = constraints["field_roles"] {
            guard let roles = value as? [String], !roles.isEmpty, roles.count <= 16, Set(roles).count == roles.count,
                  roles.allSatisfy({ profileString($0, pattern: "AX[A-Za-z0-9]{1,62}", maxBytes: 64) }) else { throw invalid }
        }
        guard !["version", "build", "signing_team_id", "language"].contains(where: { constraints[$0] != nil }) else {
            throw SystemControl.failure("keyboard_profile_context_unavailable", "Required profile context is not natively observed")
        }
        for (key, observed) in [("bundle_id", application["bundle_id"]), ("layout_id", layout["layout_id"])] where constraints[key] != nil {
            guard let actual = observed as? String, !actual.isEmpty else {
                throw SystemControl.failure("keyboard_profile_context_unavailable", "Required profile context is unavailable")
            }
            guard actual.utf8.elementsEqual((constraints[key] as! String).utf8) else {
                throw SystemControl.failure("keyboard_profile_context_mismatch", "Profile app or layout no longer matches")
            }
        }
        if let expected = constraints["keyboard_type"] as? NSNumber {
            guard let actual = layout["keyboard_type"] as? NSNumber, CFGetTypeID(actual) != CFBooleanGetTypeID() else {
                throw SystemControl.failure("keyboard_profile_context_unavailable", "Keyboard type is unavailable")
            }
            guard expected == actual else { throw SystemControl.failure("keyboard_profile_context_mismatch", "Profile keyboard type changed") }
        }
        if let roles = constraints["field_roles"] as? [String] {
            guard let actual = field["role"] as? String, !actual.isEmpty else {
                throw SystemControl.failure("keyboard_profile_context_unavailable", "Field role is unavailable")
            }
            guard roles.contains(actual) else { throw SystemControl.failure("keyboard_profile_context_mismatch", "Profile field role changed") }
        }
        return ["id": context["id"]!, "revision": context["revision"]!, "action": context["action"]!]
    }
    static func profileGeneration(_ target: [String: Any], expectedIdentity: String?) -> Bool {
        do {
            let app = try SystemControl.target(target)
            guard let expected = expectedIdentity else { return false }
            return try SystemShortcuts.stableAppIdentity(SystemControl.appIdentity(app)) == expected
        } catch { return false }
    }
    static func key(_ args: [String: Any], chord: Bool = false, profile: Bool = false) throws -> [String: Any] {
        guard let target = args["target"] as? [String: Any], let spec = args["key"] as? [String: Any] else {
            throw SystemControl.failure("invalid_arguments", "Keyboard key requires an exact target and key")
        }
        if !profile && args["profile_context"] != nil {
            throw SystemControl.failure("keyboard_profile_context_invalid", "Profile context requires a private profile operation")
        }
        let modifiers = args["modifiers"] as? [String] ?? []
        try require(chord ? !modifiers.isEmpty : args["modifiers"] == nil, "Keyboard chord requires explicit modifiers")
        let layout = try currentLayout(), resolved = try resolve(spec, modifiers: modifiers, layout: layout)
        let code = resolved.code
        let (down, up) = try events(layout.metadata, code: code, flags: resolved.flags)
        var binding: [String: Any]?, expectedIdentity: String?
        var result = try postPair(validate: {
            let current = try boundSnapshot(target)
            if profile {
                binding = try profileContext(args["profile_context"], application: current.response["application"] as? [String: Any] ?? [:],
                    layout: current.response["layout"] as? [String: Any] ?? [:],
                    field: current.response["field"] as? [String: Any] ?? [:])
                expectedIdentity = try SystemShortcuts.stableAppIdentity(current.response["application"] as? [String: Any] ?? [:])
            }
            try matchingLayout(layout.metadata, current.response["layout"] as? [String: Any] ?? [:])
            try inputAllowed(postAccess: CGPreflightPostEventAccess(),
                flags: CGEventSource.flagsState(.combinedSessionState),
                keyHeld: CGEventSource.keyState(.hidSystemState, key: code))
        }, sameGeneration: {
            profile ? profileGeneration(target, expectedIdentity: expectedIdentity) : (try? SystemControl.target(target)) != nil
        }, post: { isDown in
            // Last generation check immediately before every post, including cleanup.
            let app = try SystemControl.target(target)
            if profile {
                guard let expected = expectedIdentity,
                      try SystemShortcuts.stableAppIdentity(SystemControl.appIdentity(app)) == expected else {
                    throw SystemControl.failure("macos_target_changed", "Profile application identity changed before post")
                }
            }
            (isDown ? down : up).postToPid(app.processIdentifier)
        })
        result["requested"] = ["key": spec, "modifiers": modifiers]
        result["resolved"] = ["key_code": Int(code), "flags": resolved.flags.rawValue,
            "modifiers": modifierFlags.filter { resolved.flags.contains($0.1) }.map { $0.0 },
            "representation": resolved.representation, "layout": layout.metadata]
        if let binding = binding { result["profile_binding"] = binding; result["profile_binding_verified"] = true }
        return result
    }
    struct TextState {
        let value: String
        let units: [UniChar]
        let selection: CFRange
        func matches(_ field: Field) -> Bool {
            // Swift String == allows canonical equivalence; literal insertion does not.
            value.utf8.elementsEqual(field.value.utf8) && units.elementsEqual(field.value.utf16)
                && selection.location == field.selection.location && selection.length == field.selection.length
        }
    }
    static func validateText(_ text: String) throws {
        try require(!text.isEmpty && text.utf8.count <= 1024 * 1024, "Text exceeds its bounded UTF-8 limit")
        try require(text.unicodeScalars.allSatisfy { !($0.value < 32 && ![9, 10, 13].contains($0.value)) && $0.value != 127 },
                    "Text contains unsupported control characters")
    }
    static func textChunks(_ text: String, capacity: Int = 16) throws -> [[UniChar]] {
        try validateText(text)
        try require(capacity >= 2 && capacity <= 16, "Native Unicode unit capacity is unsupported")
        var chunks: [[UniChar]] = [], current: [UniChar] = []
        for character in text {
            let units = Array(String(character).utf16)
            try require(units.count <= capacity, "One grapheme exceeds the bounded native Unicode unit")
            if current.count + units.count > capacity { chunks.append(current); current = [] }
            current += units
        }
        if !current.isEmpty { chunks.append(current) }
        try require(chunks.flatMap { $0 }.elementsEqual(text.utf16), "Unicode chunking changed literal text")
        return chunks
    }
    static func expectedText(_ field: Field, inserting units: [UniChar]) throws -> TextState {
        let original = Array(field.value.utf16), start = field.selection.location, length = field.selection.length
        try require(start >= 0 && length >= 0 && start <= original.count && length <= original.count - start,
                    "Text insertion selection is invalid")
        for offset in [start, start + length] where offset > 0 && offset < original.count {
            try require(!(0xD800...0xDBFF).contains(original[offset - 1]) || !(0xDC00...0xDFFF).contains(original[offset]),
                        "Text insertion selection splits a surrogate pair")
        }
        var result = Array(original.prefix(start))
        result.append(contentsOf: units)
        result.append(contentsOf: original.dropFirst(start + length))
        let value = String(decoding: result, as: UTF16.self)
        try require(result.elementsEqual(value.utf16) && value.utf8.count <= maxValueBytes
                    && result.count <= maxValueBytes / 2, "Expected text field exceeds its bounded value limit")
        return TextState(value: value, units: result, selection: CFRange(location: start + units.count, length: 0))
    }
    static func textFieldAllowed(_ field: Field, text: String) throws {
        if text.unicodeScalars.contains(where: { [9, 10, 13].contains($0.value) }) {
            let subrole = field.metadata["subrole"] as? String
            try require(field.metadata["role"] as? String == "AXTextArea" && (subrole == nil || subrole == ""),
                        "Tab and line breaks require a supported multiline text area")
        }
    }
    static func checkedUnicode(_ expected: [UniChar], actualCount: Int, actual: [UniChar]) throws {
        try require(actualCount == expected.count && actual == expected,
                    "Native event Unicode capacity or contents differ from the literal text")
    }
    static func unicodeEvents(_ layout: [String: Any], units: [UniChar]) throws -> (CGEvent, CGEvent) {
        try require(!units.isEmpty && units.count <= 16, "Native Unicode unit is unbounded")
        let (down, up) = try events(layout, code: 0, flags: [])
        for event in [down, up] {
            units.withUnsafeBufferPointer { event.keyboardSetUnicodeString(stringLength: $0.count, unicodeString: $0.baseAddress) }
            var count = 0
            event.keyboardGetUnicodeString(maxStringLength: 0, actualStringLength: &count, unicodeString: nil)
            try require(count == units.count, "Native event Unicode capacity differs from the literal text")
            var actual = [UniChar](repeating: 0, count: count)
            actual.withUnsafeMutableBufferPointer {
                event.keyboardGetUnicodeString(maxStringLength: $0.count, actualStringLength: &count, unicodeString: $0.baseAddress)
            }
            try checkedUnicode(units, actualCount: count, actual: actual)
        }
        return (down, up)
    }
    /// No field value is read here: own insertion changes it. Identity/layout/security remain mandatory.
    static func textRoute(_ target: [String: Any], initial: Snapshot, keyCode: CGKeyCode = 0) throws {
        let field = try requireField(initial.field)
        let app = try SystemControl.target(target, mutating: true)
        try SystemControl.axGranted()
        var reference = target; reference["element_token"] = target["target_token"]
        let cached = try SystemControl.element(reference, app: app)
        let root = AXUIElementCreateApplication(app.processIdentifier)
        for element in [root, initial.window, initial.element] { try timeout(element) }
        try require(app.isActive && (SystemControl.attribute(root, kAXFrontmostAttribute) as? NSNumber)?.boolValue == true,
                    "Text target is no longer frontmost")
        guard let window = SystemControl.attribute(root, kAXFocusedWindowAttribute),
              let element = SystemControl.attribute(root, kAXFocusedUIElementAttribute),
              CFGetTypeID(window) == AXUIElementGetTypeID(), CFGetTypeID(element) == AXUIElementGetTypeID(),
              CFEqual(window, initial.window), CFEqual(element, initial.element), CFEqual(cached, initial.element) else {
            throw SystemControl.failure("macos_element_changed", "Text window or field identity changed")
        }
        try require((SystemControl.attribute(initial.window, kAXMinimizedAttribute) as? NSNumber)?.boolValue == false
                    && SystemControl.attribute(initial.element, kAXRoleAttribute) as? String == field.metadata["role"] as? String
                    && (try subrole(initial.element)) as? String == field.metadata["subrole"] as? String
                    && !SystemControl.secure(initial.element)
                    && (SystemControl.attribute(initial.element, "AXProtectedContent") as? NSNumber)?.boolValue != true
                    && (SystemControl.attribute(initial.element, kAXEnabledAttribute) as? NSNumber)?.boolValue == true
                    && (SystemControl.attribute(initial.element, kAXFocusedAttribute) as? NSNumber)?.boolValue == true,
                    "Text field classification or focus changed")
        guard let owner = SystemControl.attribute(initial.element, kAXWindowAttribute),
              CFGetTypeID(owner) == AXUIElementGetTypeID(), CFEqual(owner, initial.window) else {
            throw SystemControl.failure("macos_element_changed", "Text field moved to a different window")
        }
        try matchingLayout(initial.response["layout"] as? [String: Any] ?? [:], inputSource())
        try inputAllowed(postAccess: CGPreflightPostEventAccess(), flags: CGEventSource.flagsState(.combinedSessionState),
                         keyHeld: CGEventSource.keyState(.hidSystemState, key: keyCode))
    }
    static func finishText(method: String, textEvents: Int, verify: () async throws -> Bool,
                           submit: Bool, returnPair: (() throws -> Void)?) async throws -> [String: Any] {
        let verified = try await verify()
        try require(verified, "Literal text or final selection could not be verified")
        if submit {
            try Task.checkCancellation()
            guard let returnPair = returnPair else { throw SystemControl.failure("keyboard_unsupported", "Guarded Return pair is unavailable") }
            try returnPair()
        }
        return ["scope": "literal_text_and_selection_observed", "insertion_method": method,
                "text_event_count": textEvents, "ax_set_calls_returned": method == "ax_selected_text" ? 1 : 0,
                "post_calls_returned": textEvents + (submit ? 2 : 0),
                "text_post_calls_returned": textEvents, "return_post_calls_returned": submit ? 2 : 0,
                "input_attempted": true, "text_verified": true, "selection_verified": true,
                "verification_scope": "before_optional_return", "return_scope": submit ? "native_post_calls" : "none",
                "submitted": false, "return_posted": submit, "permission_requested": false,
                "app_processing_confirmed": false, "effect": "text_insertion_observed"]
    }
    static func textUnknown() -> SystemBridgeFailure {
        SystemControl.failure("keyboard_input_unknown", "Literal text/Return attempt is uncertain; no replay is permitted", unknown: true)
    }
    static func selectedTextWritable(status: AXError, settable: Bool) throws -> Bool {
        switch status {
        case .success: return settable
        case .attributeUnsupported, .notImplemented: return false
        default: throw SystemControl.failure("keyboard_unsupported", "Selected-text capability could not be observed")
        }
    }
    static func selectedTextWritable(_ element: AXUIElement) throws -> Bool {
        try timeout(element)
        var settable = DarwinBoolean(false)
        let status = AXUIElementIsAttributeSettable(element, kAXSelectedTextAttribute as CFString, &settable)
        return try selectedTextWritable(status: status, settable: settable.boolValue)
    }
    static func writeSelectedText(validate: () throws -> Void, setter: () throws -> AXError,
                                  verify: () async throws -> Bool, submit: Bool = false,
                                  returnPair: (() throws -> Void)? = nil) async throws -> [String: Any] {
        try validate()
        try Task.checkCancellation()
        do {
            // From this call onward an effect is possible, even if the AX status reports failure.
            try require(setter() == .success, "Selected-text setter outcome is uncertain")
            return try await finishText(method: "ax_selected_text", textEvents: 0,
                                        verify: verify, submit: submit, returnPair: returnPair)
        } catch { throw textUnknown() }
    }
    static func writeText(_ chunks: [[UniChar]], prepare: ([UniChar]) throws -> Void,
                          validate: (Int) throws -> Void, sameGeneration: () -> Bool,
                          post: (Bool) throws -> Void, verify: () async throws -> Bool,
                          submit: Bool = false, returnPair: (() throws -> Void)? = nil) async throws -> [String: Any] {
        var attempted = false
        try require(!chunks.isEmpty, "Literal text has no native units")
        do {
            for (index, units) in chunks.enumerated() {
                try Task.checkCancellation()
                try prepare(units)
                _ = try postPair(validate: { try validate(index) }, sameGeneration: sameGeneration, post: {
                    attempted = true
                    try post($0)
                })
            }
            return try await finishText(method: "cgevent_unicode", textEvents: chunks.count * 2,
                                        verify: verify, submit: submit, returnPair: returnPair)
        } catch {
            if attempted { throw textUnknown() }
            throw error
        }
    }
    static func submitIntent(_ args: [String: Any]) throws -> Bool {
        guard let value = args["submit"] else { return false }
        guard let flag = value as? NSNumber, CFGetTypeID(flag) == CFBooleanGetTypeID() else {
            throw SystemControl.failure("keyboard_unsupported", "Text submit must be a Boolean")
        }
        return flag.boolValue
    }
    static func text(_ args: [String: Any]) async throws -> [String: Any] {
        guard let target = args["target"] as? [String: Any], let text = args["text"] as? String else {
            throw SystemControl.failure("invalid_arguments", "Literal text requires an exact target and text")
        }
        let submit = try submitIntent(args)
        try validateText(text)
        let initial = try boundSnapshot(target)
        let initialField = try requireField(initial.field)
        try textFieldAllowed(initialField, text: text)
        let expected = try expectedText(initialField, inserting: Array(text.utf16))
        let layout = initial.response["layout"] as? [String: Any] ?? [:]
        let verify: () async throws -> Bool = {
            for attempt in 0..<5 {
                let current = try boundSnapshot(target, revision: false)
                try require(CFEqual(current.window, initial.window) && CFEqual(current.element, initial.element), "Text verification target changed")
                try matchingLayout(layout, current.response["layout"] as? [String: Any] ?? [:])
                if expected.matches(try requireField(current.field)) { return true }
                if attempt < 4 { try await Task.sleep(nanoseconds: 20_000_000) }
            }
            return false
        }
        let returnPair: () throws -> Void = {
            let (down, up) = try events(layout, code: CGKeyCode(kVK_Return), flags: [])
            _ = try postPair(validate: {
                let current = try boundSnapshot(target, revision: false)
                try require(CFEqual(current.window, initial.window) && CFEqual(current.element, initial.element)
                            && expected.matches(try requireField(current.field)), "Text or selection changed before optional Return")
                try textRoute(target, initial: initial, keyCode: CGKeyCode(kVK_Return))
                try Task.checkCancellation()
            }, sameGeneration: { (try? SystemControl.target(target)) != nil }, post: { isDown in
                let app = try SystemControl.target(target)
                (isDown ? down : up).postToPid(app.processIdentifier)
            })
        }
        var result: [String: Any]
        if try selectedTextWritable(initial.element) {
            result = try await writeSelectedText(validate: {
                _ = try boundSnapshot(target)
                try textRoute(target, initial: initial)
                try require(selectedTextWritable(initial.element), "Selected text is no longer writable")
                _ = try SystemControl.target(target)
            }, setter: {
                AXUIElementSetAttributeValue(initial.element, kAXSelectedTextAttribute as CFString, text as CFString)
            }, verify: verify, submit: submit, returnPair: returnPair)
        } else {
            let chunks = try textChunks(text)
            var pair: (CGEvent, CGEvent)?
            result = try await writeText(chunks, prepare: { pair = try unicodeEvents(layout, units: $0) }, validate: { index in
                if index == 0 { _ = try boundSnapshot(target) }
                try textRoute(target, initial: initial)
            }, sameGeneration: { (try? SystemControl.target(target)) != nil }, post: { down in
                let app = try SystemControl.target(target)
                guard let pair = pair else { throw SystemControl.failure("keyboard_unsupported", "Unicode pair is unavailable") }
                (down ? pair.0 : pair.1).postToPid(app.processIdentifier)
            }, verify: verify, submit: submit, returnPair: returnPair)
        }
        result["utf8_bytes"] = text.utf8.count
        result["utf16_units"] = text.utf16.count
        result["text_sha256"] = SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
        result["selection_utf16"] = ["location": expected.selection.location, "length": 0]
        return result
    }
    @MainActor final class TextTransfer {
        let id: String, principal: String, taskID: String, digest: String, epoch: String
        let target: [String: Any]
        let submit: Bool
        let byteCount: Int, unitCount: Int, chunkCount: Int, expires: Double
        var units: [UniChar] = []
        var nextIndex = 0
        init(id: String, principal: String, task: String, digest: String, target: [String: Any],
             submit: Bool, bytes: Int, units: Int, chunks: Int, now: Double) {
            self.id = id; self.principal = principal; taskID = task; self.digest = digest; self.target = target
            byteCount = bytes; unitCount = units; chunkCount = chunks; expires = now + 60
            self.submit = submit
            epoch = SystemBridgeRuntime.generation
            self.units.reserveCapacity(units)
        }
    }
    static var transfer: TextTransfer?
    // Never evict committed IDs within an epoch: exhaust the small budget instead of allowing replay.
    static var consumedTransfers: Set<String> = []
    static func stageInteger(_ args: [String: Any], _ key: String, max: Int) throws -> Int {
        guard let value = args[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite, value.doubleValue >= 0, value.doubleValue <= Double(max),
              value.doubleValue.rounded(.towardZero) == value.doubleValue else {
            throw SystemControl.failure("keyboard_staging_invalid", "Text staging integer is invalid")
        }
        return value.intValue
    }
    static func stageHex(_ value: Any?, length: Int) -> Bool {
        guard let text = value as? String, text.utf8.count == length else { return false }
        return text.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    static func purgeTransfer(_ now: Double) {
        if let current = transfer, now >= current.expires { transfer = nil }
    }
    static func beginTransfer(_ args: [String: Any], now: Double = ProcessInfo.processInfo.systemUptime) throws -> [String: Any] {
        purgeTransfer(now)
        let fields: Set<String> = ["task_id", "principal", "target", "submit", "utf8_bytes", "utf16_units", "sha256", "chunk_count", "encoding"]
        try require(Set(args.keys) == fields.union(["transfer_id", "binding_json"]), "Text staging manifest fields differ")
        guard let id = args["transfer_id"] as? String, stageHex(id, length: 64),
              let raw = args["binding_json"] as? String, raw.utf8.count <= 8192,
              let binding = (try? JSONSerialization.jsonObject(with: Data(raw.utf8))) as? [String: Any],
              SHA256.hash(data: Data(raw.utf8)).map({ String(format: "%02x", $0) }).joined() == id,
              try SystemControl.hash(binding) == SystemControl.hash(args.filter { fields.contains($0.key) }),
              let principal = args["principal"] as? String, !principal.isEmpty, principal.utf8.count <= 256,
              principal.utf8.elementsEqual(SystemBridgeRuntime.principal.utf8),
              let task = args["task_id"] as? String, !task.isEmpty, task.utf8.count <= 128,
              task.utf8.allSatisfy({ (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 || $0 == 95 }),
              let target = args["target"] as? [String: Any],
              Set(target.keys) == Set(["pid", "expected_started_at", "target_token", "helper_pid", "worker_generation", "expected_revision"]),
              let started = target["expected_started_at"] as? NSNumber, CFGetTypeID(started) != CFBooleanGetTypeID(),
              started.doubleValue.isFinite, started.doubleValue > 0,
              try stageInteger(target, "pid", max: Int(Int32.max)) > 0,
              try stageInteger(target, "helper_pid", max: Int(Int32.max)) == Int(getpid()),
              target["worker_generation"] as? String == SystemBridgeRuntime.generation,
              stageHex(target["target_token"], length: 32), stageHex(target["expected_revision"], length: 64),
              let submit = args["submit"] as? NSNumber, CFGetTypeID(submit) == CFBooleanGetTypeID(),
              args["encoding"] as? String == "utf-16-le", stageHex(args["sha256"], length: 64),
              let digest = args["sha256"] as? String else {
            throw SystemControl.failure("keyboard_staging_invalid", "Text staging binding, owner or encoding is invalid")
        }
        let bytes = try stageInteger(args, "utf8_bytes", max: 1024 * 1024)
        let units = try stageInteger(args, "utf16_units", max: 1024 * 1024)
        let count = try stageInteger(args, "chunk_count", max: 65)
        try require(bytes > 0 && units > 0 && units <= bytes && count > 0 && count <= units && units <= count * 16384,
                    "Text staging manifest exceeds the bounded quota")
        try require(transfer == nil && !consumedTransfers.contains(id) && consumedTransfers.count < 256,
                    "Text staging is occupied, consumed or its epoch budget is exhausted")
        transfer = TextTransfer(id: id, principal: principal, task: task, digest: digest, target: target,
                                submit: submit.boolValue, bytes: bytes, units: units, chunks: count, now: now)
        return ["transfer_id": id, "state": "accepted", "input_attempted": false]
    }
    static func ownedTransfer(_ args: [String: Any], now: Double) throws -> TextTransfer {
        purgeTransfer(now)
        guard let current = transfer, args["transfer_id"] as? String == current.id,
              current.principal.utf8.elementsEqual(SystemBridgeRuntime.principal.utf8),
              current.epoch == SystemBridgeRuntime.generation else {
            throw SystemControl.failure("keyboard_staging_invalid", "Text staging is absent, expired, consumed or foreign")
        }
        return current
    }
    static func chunkTransfer(_ args: [String: Any], now: Double = ProcessInfo.processInfo.systemUptime) throws -> [String: Any] {
        try require(Set(args.keys) == Set(["transfer_id", "index", "data_b64"]), "Text staging chunk fields differ")
        let current = try ownedTransfer(args, now: now)
        let index = try stageInteger(args, "index", max: current.chunkCount - 1)
        guard index == current.nextIndex, let encoded = args["data_b64"] as? String, encoded.utf8.count <= 43692,
              let data = Data(base64Encoded: encoded), data.base64EncodedString() == encoded,
              !data.isEmpty, data.count <= 32768, data.count % 2 == 0 else {
            throw SystemControl.failure("keyboard_staging_invalid", "Text staging chunk order or base64 is invalid")
        }
        let bytes = Array(data)
        let units = stride(from: 0, to: bytes.count, by: 2).map { UniChar(bytes[$0]) | (UniChar(bytes[$0 + 1]) << 8) }
        try require(String(decoding: units, as: UTF16.self).utf16.elementsEqual(units)
                    && current.units.count + units.count <= current.unitCount, "Text staging UTF-16 or cumulative quota is invalid")
        current.units.append(contentsOf: units); current.nextIndex += 1
        return ["transfer_id": current.id, "state": "received", "received_chunks": current.nextIndex,
                "received_utf16_units": current.units.count, "input_attempted": false]
    }
    static func commitTransfer(_ args: [String: Any], now: Double = ProcessInfo.processInfo.systemUptime,
                               writer: ([String: Any]) async throws -> [String: Any]) async throws -> [String: Any] {
        try require(Set(args.keys) == Set(["transfer_id"]), "Text commit fields differ")
        let current = try ownedTransfer(args, now: now)
        transfer = nil; consumedTransfers.insert(current.id) // Before validation/writer/any possible input.
        let text = String(decoding: current.units, as: UTF16.self)
        try require(current.nextIndex == current.chunkCount && current.units.count == current.unitCount
                    && text.utf16.elementsEqual(current.units) && text.utf8.count == current.byteCount
                    && SHA256.hash(data: Data(text.utf8)).map({ String(format: "%02x", $0) }).joined() == current.digest,
                    "Staged text is incomplete or its length/digest differs")
        var result = try await writer(["target": current.target, "text": text, "submit": current.submit])
        result["transfer_id"] = current.id; result["task_id"] = current.taskID; result["staging_verified"] = true
        return result
    }
    static func abortTransfer(_ args: [String: Any], now: Double = ProcessInfo.processInfo.systemUptime) throws -> [String: Any] {
        try require(Set(args.keys) == Set(["transfer_id"]), "Text abort fields differ")
        let current = try ownedTransfer(args, now: now)
        transfer = nil
        return ["transfer_id": current.id, "state": "aborted", "input_attempted": false]
    }
    static func handle(_ operation: String, arguments: [String: Any]) async throws -> [String: Any]? {
        switch operation {
        case "keyboard.inspect": return try snapshot(arguments).response
        case "keyboard.key": return try key(arguments)
        case "keyboard.chord": return try key(arguments, chord: true)
        case "keyboard.profile.key": return try key(arguments, profile: true)
        case "keyboard.profile.chord": return try key(arguments, chord: true, profile: true)
        case "keyboard.text.begin": return try beginTransfer(arguments)
        case "keyboard.text.chunk": return try chunkTransfer(arguments)
        case "keyboard.text.commit": return try await commitTransfer(arguments, writer: { try await text($0) })
        case "keyboard.text.abort": return try abortTransfer(arguments)
        default: return try SystemShortcuts.handle(operation, arguments: arguments)
        }
    }
}

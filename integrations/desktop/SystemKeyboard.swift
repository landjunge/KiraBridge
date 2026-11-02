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
    static func key(_ args: [String: Any], chord: Bool = false) throws -> [String: Any] {
        guard let target = args["target"] as? [String: Any], let spec = args["key"] as? [String: Any] else {
            throw SystemControl.failure("invalid_arguments", "Keyboard key requires an exact target and key")
        }
        let modifiers = args["modifiers"] as? [String] ?? []
        try require(chord ? !modifiers.isEmpty : args["modifiers"] == nil, "Keyboard chord requires explicit modifiers")
        let layout = try currentLayout(), resolved = try resolve(spec, modifiers: modifiers, layout: layout)
        let code = resolved.code
        let (down, up) = try events(layout.metadata, code: code, flags: resolved.flags)
        var result = try postPair(validate: {
            let current = try boundSnapshot(target)
            try matchingLayout(layout.metadata, current.response["layout"] as? [String: Any] ?? [:])
            try inputAllowed(postAccess: CGPreflightPostEventAccess(),
                flags: CGEventSource.flagsState(.combinedSessionState),
                keyHeld: CGEventSource.keyState(.hidSystemState, key: code))
        }, sameGeneration: { (try? SystemControl.target(target)) != nil }, post: { isDown in
            // Last generation check immediately before every post, including cleanup.
            let app = try SystemControl.target(target)
            (isDown ? down : up).postToPid(app.processIdentifier)
        })
        result["requested"] = ["key": spec, "modifiers": modifiers]
        result["resolved"] = ["key_code": Int(code), "flags": resolved.flags.rawValue,
            "modifiers": modifierFlags.filter { resolved.flags.contains($0.1) }.map { $0.0 },
            "representation": resolved.representation, "layout": layout.metadata]
        return result
    }
    static func handle(_ operation: String, arguments: [String: Any]) throws -> [String: Any]? {
        switch operation {
        case "keyboard.inspect": return try snapshot(arguments).response
        case "keyboard.key": return try key(arguments)
        case "keyboard.chord": return try key(arguments, chord: true)
        default: return nil
        }
    }
}

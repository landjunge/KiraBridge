import AppKit
import ApplicationServices
import Carbon
import CoreAudio
import CoreGraphics
import IOKit
import IOKit.graphics
import IOKit.hidsystem

/// Explicit system scope, separate from PID-directed application keyboard input.
/// Quartz post calls are dispatch evidence, never an acknowledgement by macOS.
@MainActor
enum SystemSpecialKeys {
    struct SpaceChanges {
        var startedAt: Double?
        var count = 0
        var lastObservedAt: Double?
        mutating func begin(at time: Double) {
            if startedAt == nil, time.isFinite, time >= 0 { startedAt = time }
        }
        mutating func observe(at time: Double) {
            guard let started = startedAt, time.isFinite, time >= started,
                  lastObservedAt == nil || time >= lastObservedAt!, count < Int.max else { return }
            count += 1
            lastObservedAt = time
        }
        var metadata: [String: Any] {
            ["observer_started_at_uptime": startedAt as Any? ?? NSNull(),
             "notification_count": count, "last_observed_at_uptime": lastObservedAt as Any? ?? NSNull(),
             "source": "NSWorkspace.activeSpaceDidChangeNotification",
             "scope": "notifications observed by this worker; no active space ID"]
        }
    }
    static var spaceChanges = SpaceChanges()
    static var spaceObserver: NSObjectProtocol?
    static func startSpaceObservation() {
        guard spaceObserver == nil else { return }
        spaceChanges.begin(at: ProcessInfo.processInfo.systemUptime)
        spaceObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main
        ) { _ in
            Task { @MainActor in
                spaceChanges.observe(at: ProcessInfo.processInfo.systemUptime)
            }
        }
    }
    struct Plan: Equatable {
        let action: String
        let route: String
        let code: Int
        let flags: CGEventFlags
        let registered: Bool
        let preferenceID: String?
        var metadata: [String: Any] {
            var result: [String: Any] = ["action": action, "route": route, "code": code, "flags": flags.rawValue,
             "modifiers": SystemSpecialKeys.modifierNames(flags),
             "registered_system_action": registered,
             "symbolic_hotkey_id": preferenceID as Any? ?? NSNull()]
            if route == "quartz_hid" { result["key"] = ["key_code": code] }
            return result
        }
    }
    // Constants come from the public SDK IOKit/hidsystem/ev_keymap.h. The SDK
    // explicitly does not guarantee these keys on every hardware implementation.
    static let special: [String: Int32] = [
        "volume_up": NX_KEYTYPE_SOUND_UP, "volume_down": NX_KEYTYPE_SOUND_DOWN,
        "mute": NX_KEYTYPE_MUTE, "brightness_up": NX_KEYTYPE_BRIGHTNESS_UP,
        "brightness_down": NX_KEYTYPE_BRIGHTNESS_DOWN,
        "keyboard_brightness_up": NX_KEYTYPE_ILLUMINATION_UP,
        "keyboard_brightness_down": NX_KEYTYPE_ILLUMINATION_DOWN,
        "keyboard_brightness_toggle": NX_KEYTYPE_ILLUMINATION_TOGGLE,
        "play_pause": NX_KEYTYPE_PLAY, "next_track": NX_KEYTYPE_NEXT,
        "previous_track": NX_KEYTYPE_PREVIOUS, "fast_forward": NX_KEYTYPE_FAST,
        "rewind": NX_KEYTYPE_REWIND, "eject": NX_KEYTYPE_EJECT,
        "display_mirror": NX_KEYTYPE_VIDMIRROR, "contrast_up": NX_KEYTYPE_CONTRAST_UP,
        "contrast_down": NX_KEYTYPE_CONTRAST_DOWN, "launch_panel": NX_KEYTYPE_LAUNCH_PANEL,
        "menu": NX_KEYTYPE_MENU,
    ]
    // A preference schema observation, not an assertion that every macOS version
    // exposes these entries. Missing, disabled and non-keyboard bindings refuse.
    static let symbolic: [String: String] = [
        "mission_control": "32", "application_windows": "33", "show_desktop": "36",
        "space_left": "79", "space_right": "81", "spotlight": "64",
        "spotlight_finder": "65", "window_next": "27",
    ]
    static let fixed: [String: (Int, CGEventFlags)] = [
        "app_next": (48, .maskCommand),
        "app_previous": (48, [.maskCommand, .maskShift]),
    ]
    static let allowedFlags: CGEventFlags = [
        .maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn, .maskNumericPad,
    ]
    nonisolated static func modifierNames(_ flags: CGEventFlags) -> [String] {
        let names: [(String, CGEventFlags)] = [("command", .maskCommand), ("control", .maskControl),
            ("option", .maskAlternate), ("shift", .maskShift), ("fn", .maskSecondaryFn)]
        return names.filter { flags.contains($0.1) }.map { $0.0 }
    }
    static func failure(_ text: String, unknown: Bool = false) -> SystemBridgeFailure {
        SystemControl.failure(unknown ? "keyboard_input_unknown" : "keyboard_unsupported",
                              text, unknown: unknown)
    }
    static func exactInteger(_ value: Any?, max: Int) throws -> Int {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue >= 0,
              number.doubleValue <= Double(max), number.doubleValue == Double(number.intValue) else {
            throw failure("System keyboard integer is invalid")
        }
        return number.intValue
    }
    static func preferences() -> [String: Any] {
        var result = CFPreferencesCopyAppValue("AppleSymbolicHotKeys" as CFString,
            "com.apple.symbolichotkeys" as CFString) as? [String: Any] ?? [:]
        var publicValues: Unmanaged<CFArray>?
        if CopySymbolicHotKeys(&publicValues) == noErr,
           let rows = publicValues?.takeRetainedValue() as? [[String: Any]], rows.count <= 4096 {
            result["_carbon_symbolic_hotkeys"] = rows
        }
        return result
    }
    static func publicPlans(_ preferences: [String: Any]) -> [Plan] {
        let known = (symbolic.keys.sorted() + fixed.keys.sorted()).compactMap {
            try? actionPlan($0, modifiers: [], preferences: preferences)
        }
        let rows = preferences["_carbon_symbolic_hotkeys"] as? [[String: Any]] ?? []
        var result: [Plan] = []
        for row in rows.prefix(4096) {
            guard let enabled = row[kHISymbolicHotKeyEnabled as String] as? NSNumber,
                  CFGetTypeID(enabled) == CFBooleanGetTypeID(), enabled.boolValue,
                  let code = try? exactInteger(row[kHISymbolicHotKeyCode as String], max: 127),
                  let raw = try? exactInteger(row[kHISymbolicHotKeyModifiers as String], max: Int(UInt32.max)) else { continue }
            let mappings: [(Int, CGEventFlags)] = [(cmdKey, .maskCommand), (controlKey, .maskControl),
                (optionKey, .maskAlternate), (shiftKey, .maskShift), (Int(kEventKeyModifierFnMask), .maskSecondaryFn)]
            let allowed = mappings.reduce(0) { $0 | $1.0 }
            guard raw & ~allowed == 0 else { continue }
            let flags = mappings.reduce(CGEventFlags()) { value, pair in
                raw & pair.0 != 0 ? value.union(pair.1) : value
            }
            // Never duplicate a named current shortcut or claim Carbon exposes
            // its semantic identity: the public API explicitly provides none.
            let duplicates = known + result
            guard !duplicates.contains(where: {
                $0.code == code && comparableFlags($0.flags, code: code) == comparableFlags(flags, code: code)
            }) else { continue }
            let name = "registered_shortcut_\(code)_\(flags.rawValue)"
            result.append(Plan(action: name, route: "quartz_hid", code: code, flags: flags,
                               registered: true, preferenceID: nil))
        }
        return result.sorted { $0.action < $1.action }
    }
    static func symbolicPlan(_ action: String, preferences: [String: Any]) throws -> Plan {
        guard let identifier = symbolic[action], let row = preferences[identifier] as? [String: Any],
              let enabled = row["enabled"] as? NSNumber,
              CFGetTypeID(enabled) == CFBooleanGetTypeID(), enabled.boolValue,
              let value = row["value"] as? [String: Any], value["type"] as? String == "standard",
              let parameters = value["parameters"] as? [Any], parameters.count == 3 else {
            throw failure("System shortcut is absent, disabled or not a keyboard binding")
        }
        let code = try exactInteger(parameters[1], max: 127)
        let rawFlags = try exactInteger(parameters[2], max: Int(UInt32.max))
        let flags = CGEventFlags(rawValue: UInt64(rawFlags))
        guard flags.subtracting(allowedFlags).isEmpty else {
            throw failure("System shortcut uses unsupported flags")
        }
        return Plan(action: action, route: "quartz_hid", code: code, flags: flags,
                    registered: true, preferenceID: identifier)
    }
    static func actionPlan(_ action: String, modifiers: [String], preferences: [String: Any]) throws -> Plan {
        if let type = special[action] {
            guard modifiers.count <= 5, Set(modifiers).count == modifiers.count else {
                throw failure("System hardware modifiers must be unique and bounded")
            }
            let lookup = Dictionary(uniqueKeysWithValues: SystemKeyboard.modifierFlags)
            var flags = CGEventFlags()
            for name in modifiers {
                guard let flag = lookup[name] else { throw failure("Unknown system hardware modifier") }
                flags.insert(flag)
            }
            return Plan(action: action, route: "system_defined_hid", code: Int(type), flags: flags,
                        registered: true, preferenceID: nil)
        }
        guard modifiers.isEmpty else { throw failure("Named system actions use their own exact modifiers") }
        if action.hasPrefix("registered_shortcut_") {
            guard let plan = publicPlans(preferences).first(where: { $0.action == action }) else {
                throw failure("Public system shortcut is no longer registered")
            }
            return plan
        }
        if action == "caps_lock" {
            return Plan(action: action, route: "modifier_lock_state", code: 57, flags: [],
                        registered: true, preferenceID: nil)
        }
        if let chord = fixed[action] {
            return Plan(action: action, route: "quartz_hid", code: chord.0, flags: chord.1,
                        registered: true, preferenceID: nil)
        }
        return try symbolicPlan(action, preferences: preferences)
    }
    static func comparableFlags(_ flags: CGEventFlags, code: Int) -> CGEventFlags {
        // Arrow/F-key entries include AppKit's function/numpad classification,
        // even when the user's chord has no physical Fn modifier.
        let classified = Set([123, 124, 125, 126, 122, 120, 99, 118, 96, 97, 98, 100,
                              101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90])
        return classified.contains(code) ? flags.subtracting([.maskSecondaryFn, .maskNumericPad]) : flags
    }
    static func registeredMatch(code: Int, flags: CGEventFlags, preferences: [String: Any]) -> Plan? {
        var plans = (symbolic.keys.sorted() + fixed.keys.sorted()).compactMap {
            try? actionPlan($0, modifiers: [], preferences: preferences)
        }
        plans += publicPlans(preferences)
        let matches = plans.compactMap { plan -> Plan? in
            guard plan.code == code,
                  comparableFlags(plan.flags, code: code) == comparableFlags(flags, code: code) else { return nil }
            return plan
        }
        return matches.count == 1 ? matches.first : nil
    }
    static func rawKeyPlan(code: Int, flags: CGEventFlags, explicitFn: Bool,
                           preferences: [String: Any]) -> Plan {
        // Fn in an explicit request is intent, not AppKit's function-key
        // classification metadata. Never erase it to gain a system-action or
        // protected-terminal exception. An explicit named action is separate.
        if !explicitFn, let matched = registeredMatch(code: code, flags: flags, preferences: preferences) {
            return matched
        }
        return Plan(action: "explicit_key", route: "quartz_hid", code: code, flags: flags,
                    registered: false, preferenceID: nil)
    }
    static func plan(_ args: [String: Any], preferences: [String: Any]) throws -> Plan {
        guard args["scope"] as? String == "system" else {
            throw failure("Global keyboard input requires explicit system scope")
        }
        let rawModifiers = args["modifiers"]
        guard rawModifiers == nil || rawModifiers is [String] else { throw failure("Invalid system key modifiers") }
        let modifiers = rawModifiers as? [String] ?? []
        if let action = args["action"] as? String {
            guard args["key"] == nil else { throw failure("Choose a system action or one key") }
            return try actionPlan(action, modifiers: modifiers, preferences: preferences)
        }
        guard args["action"] == nil, let spec = args["key"] as? [String: Any] else {
            throw failure("Choose a system action or one key")
        }
        let resolved = try SystemKeyboard.resolve(spec, modifiers: modifiers, layout: SystemKeyboard.currentLayout())
        return rawKeyPlan(code: Int(resolved.code), flags: resolved.flags,
                          explicitFn: modifiers.contains("fn"), preferences: preferences)
    }
    static func classificationKeyUpFlags(_ flags: CGEventFlags, code: Int, explicitFn: Bool) -> CGEventFlags {
        guard !explicitFn, flags.contains(.maskSecondaryFn), comparableFlags(flags, code: code) != flags else { return flags }
        return flags.subtracting(.maskSecondaryFn)
    }
    static func events(_ plan: Plan, observedCapsLock: Bool? = nil,
                       explicitFn: Bool = false) throws -> (CGEvent, CGEvent) {
        if plan.route == "system_defined_hid" {
            func event(_ down: Bool) throws -> CGEvent {
                let state = Int(down ? NX_KEYDOWN : NX_KEYUP)
                guard let event = NSEvent.otherEvent(with: .systemDefined, location: .zero,
                    modifierFlags: NSEvent.ModifierFlags(rawValue: UInt(plan.flags.rawValue) | UInt(state << 8)),
                    timestamp: 0, windowNumber: 0, context: nil,
                    subtype: Int16(NX_SUBTYPE_AUX_CONTROL_BUTTONS),
                    data1: (plan.code << 16) | (state << 8), data2: -1)?.cgEvent else {
                    throw failure("System-defined event could not be constructed")
                }
                return event
            }
            return try (event(true), event(false))
        }
        guard plan.route == "quartz_hid" else {
            throw failure("System keyboard event could not be constructed")
        }
        let pair = try SystemKeyboard.events(["keyboard_type": Int(LMGetKbdType())],
            code: CGKeyCode(plan.code), flags: plan.flags, observedCapsLock: observedCapsLock)
        // Fn on an arrow/F-key can be classification metadata. Clearing only
        // that bit on the ordinary key-up avoids synthesizing a Globe/Fn-up.
        pair.1.flags = classificationKeyUpFlags(pair.1.flags, code: plan.code, explicitFn: explicitFn)
        return pair
    }
    /// Pure orchestration also used by the injected native harness. Key-up is
    /// always attempted after our key-down; system navigation may change focus.
    struct ModifierRelease {
        let code: CGKeyCode
        let flags: CGEventFlags
    }
    static func modifierReleasePlan(_ plan: Plan, explicitFn: Bool, capsLock: Bool) -> [ModifierRelease] {
        guard plan.route == "quartz_hid" else { return [] }
        var owned = plan.flags.intersection([.maskCommand, .maskControl, .maskAlternate, .maskShift])
        if explicitFn && plan.flags.contains(.maskSecondaryFn) { owned.insert(.maskSecondaryFn) }
        let order: [(CGKeyCode, CGEventFlags)] = [(55, .maskCommand), (59, .maskControl),
            (58, .maskAlternate), (56, .maskShift), (63, .maskSecondaryFn)]
        var result: [ModifierRelease] = []
        for (code, flag) in order where owned.contains(flag) {
            owned.remove(flag)
            result.append(ModifierRelease(code: code,
                flags: capsLock ? owned.union(.maskAlphaShift) : owned))
        }
        return result
    }
    static let leftModifierKeys: [(CGKeyCode, CGEventFlags)] = [
        (55, .maskCommand), (56, .maskShift), (58, .maskAlternate), (59, .maskControl), (63, .maskSecondaryFn)
    ]
    static func modifierStateCompatible(ownedFlags: CGEventFlags, read: (CGKeyCode) -> Bool) -> Bool {
        // HID queries include our synthetic chord. Only left-key states
        // introduced by this input are allowed between transitions; no right
        // modifier is generated here. A simultaneous physical press of the
        // same owned modifier cannot be distinguished by this public API.
        let owned = Set(leftModifierKeys.filter { ownedFlags.contains($0.1) }.map { $0.0 })
        return ![54, 55, 56, 58, 59, 60, 61, 62, 63].contains {
            read(CGKeyCode($0)) && !owned.contains(CGKeyCode($0))
        }
    }
    static func physicalModifiersIdle(read: (CGKeyCode) -> Bool) -> Bool {
        // Strict pre-input query: no synthetic modifier is owned yet.
        modifierStateCompatible(ownedFlags: [], read: read)
    }
    static func settleModifierState(ownedFlags: CGEventFlags,
                                    now: () -> Double, pause: (Double) -> Void,
                                    validate: () throws -> Void,
                                    read: () -> (Set<CGKeyCode>, CGEventFlags)) throws -> Int {
        let flags = ownedFlags.intersection([.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn])
        guard !flags.isEmpty else { return 0 }
        let keys = Set(leftModifierKeys.filter { flags.contains($0.1) }.map { $0.0 })
        let started = now(), limit = 0.2
        guard started.isFinite else { throw failure("Modifier state clock is unavailable", unknown: true) }
        for poll in 1...256 {
            let before = now()
            guard before.isFinite, before >= started, before - started <= limit else {
                throw failure("Own modifier state did not settle within 200 ms; no replay is permitted", unknown: true)
            }
            try validate()
            let (held, currentFlags) = read()
            guard modifierStateCompatible(ownedFlags: flags, read: { held.contains($0) }) else {
                throw failure("Unowned modifier state changed during release observation", unknown: true)
            }
            let after = now()
            guard after.isFinite, after >= before, after - started <= limit else {
                throw failure("Own modifier state observation exceeded 200 ms", unknown: true)
            }
            if held.intersection(keys).isEmpty && currentFlags.intersection(flags).isEmpty { return poll }
            let remaining = limit - (after - started)
            guard remaining > 0 else {
                throw failure("Own modifier state did not clear; no replay is permitted", unknown: true)
            }
            pause(min(0.001, remaining))
        }
        throw failure("Own modifier state observation limit reached; no replay is permitted", unknown: true)
    }
    static func releaseModifiers(_ plan: Plan, explicitFn: Bool,
                                 capsLock: () -> Bool, validate: () throws -> Void,
                                 post: (CGEvent) throws -> Void) throws -> Int {
        // Build no events for non-Quartz routes or classification-only Fn.
        let releases = modifierReleasePlan(plan, explicitFn: explicitFn, capsLock: false)
        var returned = 0
        for release in releases {
            try validate()
            guard let source = CGEventSource(stateID: .privateState),
                  let event = CGEvent(keyboardEventSource: source, virtualKey: release.code, keyDown: false) else {
                throw failure("System modifier release event could not be constructed")
            }
            event.type = .flagsChanged
            event.flags = capsLock() ? release.flags.union(.maskAlphaShift) : release.flags
            try post(event)
            returned += 1
        }
        return returned
    }
    static func pairs(_ count: Int, validate: () throws -> Void,
                      post: (Bool) throws -> Void,
                      release: () throws -> Int = { 0 }) throws -> [String: Any] {
        guard count >= 1, count <= 20 else { throw failure("System repeat must be between 1 and 20") }
        var attempted = 0, completed = 0, releases = 0
        do {
            for _ in 0..<count {
                try validate()
                attempted += 1
                var keyUpReturned = false, releaseAttempted = false
                do {
                    try post(true)
                    try post(false)
                    keyUpReturned = true
                    releaseAttempted = true
                    releases += try release()
                } catch {
                    // Release only our own key/modifiers, once, through the
                    // same fresh-rights/ownership-aware modifier callback. Never replay a
                    // partially attempted modifier-release batch.
                    if !keyUpReturned { try? post(false) }
                    if !releaseAttempted { _ = try? release() }
                    throw error
                }
                completed += 1
            }
        } catch {
            if attempted > 0 {
                throw failure("System keyboard input is partial or uncertain; no replay is permitted (attempted_pairs=\(attempted), posted_pairs=\(completed))", unknown: true)
            }
            throw error
        }
        return ["scope": "native_post_calls", "event_scope": "system",
                "attempted_pairs": attempted, "posted_pairs": completed,
                "requested_repeat": count, "completed_repeat": completed,
                "key_pair_post_calls_returned": completed * 2, "modifier_release_post_calls_returned": releases,
                "post_calls_returned": completed * 2 + releases, "input_attempted": true,
                "system_processing_confirmed": false, "permission_requested": false]
    }
    static func withCapsLock<T>(_ operation: (io_connect_t) throws -> T) throws -> T {
        let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOHIDSystem"))
        guard service != 0 else { throw failure("Caps Lock HID service is unavailable") }
        defer { IOObjectRelease(service) }
        var handle = io_connect_t(0)
        let status = IOServiceOpen(service, mach_task_self_, UInt32(kIOHIDParamConnectType), &handle)
        guard status == KERN_SUCCESS else {
            throw failure("Caps Lock HID parameter connection is unavailable (status=\(status)); no privilege request was made")
        }
        defer { IOServiceClose(handle) }
        return try operation(handle)
    }
    static func readCapsLock(_ handle: io_connect_t) throws -> Bool {
        var state = false
        let status = IOHIDGetModifierLockState(handle, Int32(kIOHIDCapsLockState), &state)
        guard status == KERN_SUCCESS else { throw failure("Caps Lock state is not readable (status=\(status))") }
        return state
    }
    static func capsLockObservation() -> [String: Any] {
        do {
            let state = try withCapsLock { try readCapsLock($0) }
            return ["available": true, "state": state,
                    "observation_scope": "public_IOHIDGetModifierLockState; no writes",
                    "setter_access": "not_probed_until_explicit_execution"]
        } catch {
            return ["available": false, "reason": "public_modifier_lock_read_unavailable",
                    "setter_access": "not_probed; no privileges requested"]
        }
    }
    /// Testable typed state transaction. Every setter is followed by an exact
    /// kernel state read, and a partial/unknown mutation is never replayed.
    static func modifierLock(_ count: Int, validate: () throws -> Void,
                             read: () throws -> Bool, set: (Bool) throws -> Void) throws -> [String: Any] {
        guard count >= 1, count <= 20 else { throw failure("Modifier lock repeat must be between 1 and 20") }
        let before = try read()
        var expected = before, attempted = 0, completed = 0
        do {
            for _ in 0..<count {
                try validate()
                guard try read() == expected else { throw failure("Modifier lock state changed before input") }
                let desired = !expected
                attempted += 1
                try set(desired)
                guard try read() == desired else { throw failure("Modifier lock state readback differs") }
                expected = desired
                completed += 1
            }
        } catch {
            if attempted > 0 {
                throw failure("Modifier lock input is partial or uncertain; no replay is permitted (attempted=\(attempted), verified=\(completed))", unknown: true)
            }
            throw error
        }
        return ["scope": "native_state_readback", "event_scope": "system", "modifier": "caps_lock",
                "requested_repeat": count, "completed_repeat": completed,
                "state_before": before, "state_after": expected, "effect_verified": true,
                "state_set_calls_returned": completed, "post_calls_returned": 0,
                "input_attempted": true, "system_processing_confirmed": true, "permission_requested": false]
    }
    static func heldKeyConflict(route: String, read: () -> Bool) -> Bool {
        route == "quartz_hid" && read()
    }
    static func key(_ args: [String: Any]) throws -> [String: Any] {
        guard let target = args["target"] as? [String: Any] else {
            throw failure("System input requires a freshly bound frontmost PID and start time")
        }
        let count = try exactInteger(args["repeat"] ?? 1, max: 20)
        guard count >= 1 else { throw failure("System repeat must be between 1 and 20") }
        let initial = try plan(args, preferences: preferences())
        let before = observations()
        var appliedEventFlags: CGEventFlags?
        var appliedKeyUpFlags: CGEventFlags?
        let validate: () throws -> Void = {
            let current = try plan(args, preferences: preferences())
            guard current == initial else { throw failure("System shortcut changed before input") }
            let app = try SystemControl.target(target, mutating: !initial.registered)
            guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier, app.isActive else {
                throw failure("System input frontmost application changed")
            }
            try SystemControl.axGranted()
            if !initial.registered { _ = try SystemKeyboard.snapshot(target) }
            if initial.route == "quartz_hid", let applied = appliedEventFlags {
                guard SystemKeyboard.observedCapsLock() == applied.contains(.maskAlphaShift) else {
                    throw failure("Caps Lock changed before system keyboard input")
                }
            }
            let heldFlags = CGEventSource.flagsState(.hidSystemState)
            // keyState(57) reports the latched lock state, not physical pressure.
            // Keep the held-key guard for ordinary Quartz keys only.
            let heldKey = heldKeyConflict(route: initial.route) {
                CGEventSource.keyState(.hidSystemState, key: CGKeyCode(initial.code))
            }
            try SystemKeyboard.inputAllowed(postAccess: CGPreflightPostEventAccess(), flags: heldFlags, keyHeld: heldKey)
        }
        var result: [String: Any]
        if initial.route == "modifier_lock_state" {
            result = try withCapsLock { handle in
                try modifierLock(count, validate: validate, read: { try readCapsLock(handle) }, set: { value in
                    let status = IOHIDSetModifierLockState(handle, Int32(kIOHIDCapsLockState), value)
                    guard status == KERN_SUCCESS else { throw failure("Caps Lock state setter failed (status=\(status))") }
                })
            }
        } else {
            let pair = try events(initial, explicitFn: (args["modifiers"] as? [String] ?? []).contains("fn"))
            if initial.route == "quartz_hid" {
                appliedEventFlags = pair.0.flags
                appliedKeyUpFlags = pair.1.flags
            }
            var introducedFlags = CGEventFlags()
            let releaseGuard: () throws -> Void = {
                try SystemControl.axGranted()
                guard CGPreflightPostEventAccess(), modifierStateCompatible(ownedFlags: introducedFlags, read: {
                    CGEventSource.keyState(.hidSystemState, key: $0)
                }) else {
                    throw failure("Current post access or compatible unowned modifier state is absent")
                }
            }
            result = try pairs(count, validate: validate,
                post: { down in
                    try releaseGuard()
                    (down ? pair.0 : pair.1).post(tap: .cghidEventTap)
                    if down && initial.route == "quartz_hid" { introducedFlags = initial.flags }
                }, release: {
                    let returned = try releaseModifiers(initial,
                        explicitFn: (args["modifiers"] as? [String] ?? []).contains("fn"),
                        capsLock: { SystemKeyboard.observedCapsLock() }, validate: releaseGuard,
                        post: { event in
                            event.post(tap: .cghidEventTap)
                        })
                    // Post return is not a processing acknowledgement: retain
                    // the complete owned mask through every release and the
                    // bounded read-only settling phase. This proves HID state
                    // clearing only, never an application's action processing.
                    _ = try settleModifierState(ownedFlags: introducedFlags,
                        now: { ProcessInfo.processInfo.systemUptime },
                        pause: { Thread.sleep(forTimeInterval: $0) }, validate: releaseGuard,
                        read: {
                            let held = Set([54, 55, 56, 58, 59, 60, 61, 62, 63].compactMap { code -> CGKeyCode? in
                                CGEventSource.keyState(.hidSystemState, key: CGKeyCode(code)) ? CGKeyCode(code) : nil
                            })
                            return (held, CGEventSource.flagsState(.hidSystemState))
                        })
                    introducedFlags = []
                    return returned
                })
        }
        result["resolved"] = initial.metadata
        if let applied = appliedEventFlags {
            var metadata = initial.metadata
            metadata["requested_flags"] = initial.flags.rawValue
            metadata["applied_flags"] = applied.rawValue
            metadata["applied_key_down_flags"] = applied.rawValue
            metadata["applied_key_up_flags"] = appliedKeyUpFlags?.rawValue as Any? ?? NSNull()
            metadata["function_classification_cleared_on_key_up"] = applied.contains(.maskSecondaryFn)
                && appliedKeyUpFlags?.contains(.maskSecondaryFn) == false
            metadata["caps_lock_applied"] = applied.contains(.maskAlphaShift)
            result["resolved"] = metadata
        }
        var resolved = result["resolved"] as? [String: Any] ?? initial.metadata
        resolved["modifier_release_key_codes"] = modifierReleasePlan(initial,
            explicitFn: (args["modifiers"] as? [String] ?? []).contains("fn"), capsLock: false).map { Int($0.code) }
        result["resolved"] = resolved
        result["observed_before"] = before
        result["observed_after"] = observations()
        result["effect"] = initial.route == "modifier_lock_state" ? "modifier_lock_verified" : "system_events_dispatched"
        return result
    }
    static func audioObservation() -> [String: Any] {
        var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var device = AudioDeviceID(0), size = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address,
                                        0, nil, &size, &device) == noErr, device != 0 else {
            return ["available": false, "reason": "no_default_output_observed"]
        }
        var channels: [[String: Any]] = []
        for element: UInt32 in 0...2 {
            var property = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyVolumeScalar,
                mScope: kAudioDevicePropertyScopeOutput, mElement: element)
            var value: Float32 = 0, bytes = UInt32(MemoryLayout<Float32>.size), settable = DarwinBoolean(false)
            if AudioObjectHasProperty(device, &property),
               AudioObjectGetPropertyData(device, &property, 0, nil, &bytes, &value) == noErr,
               value.isFinite, value >= 0, value <= 1 {
                let allowed = AudioObjectIsPropertySettable(device, &property, &settable) == noErr && settable.boolValue
                channels.append(["element": Int(element), "volume_scalar": Double(value), "settable": allowed])
            }
        }
        var property = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyMute,
            mScope: kAudioDevicePropertyScopeOutput, mElement: kAudioObjectPropertyElementMain)
        var muted: UInt32 = 0
        size = UInt32(MemoryLayout<UInt32>.size)
        let hasMute = AudioObjectHasProperty(device, &property)
            && AudioObjectGetPropertyData(device, &property, 0, nil, &size, &muted) == noErr
        return ["available": true, "device_id": Int(device), "volume_channels": channels,
                "mute": hasMute ? muted != 0 : NSNull(),
                "observation_scope": "public_coreaudio_default_output; no writes"]
    }
    static func brightnessObservation() -> [[String: Any]] {
        var iterator = io_iterator_t(0)
        guard IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IODisplayConnect"), &iterator) == KERN_SUCCESS else { return [] }
        defer { IOObjectRelease(iterator) }
        var result: [[String: Any]] = []
        for _ in 0..<64 {
            let service = IOIteratorNext(iterator)
            if service == 0 { break }
            defer { IOObjectRelease(service) }
            var identifier: UInt64 = 0, value: Float = 0
            guard IORegistryEntryGetRegistryEntryID(service, &identifier) == KERN_SUCCESS,
                  IODisplayGetFloatParameter(service, 0, kIODisplayBrightnessKey as CFString, &value) == KERN_SUCCESS,
                  value.isFinite, value >= 0, value <= 1 else { continue }
            result.append(["registry_entry_id": String(identifier), "brightness": Double(value),
                           "observation_scope": "public_iokit; no writes"])
        }
        return result.sorted { ($0["registry_entry_id"] as? String ?? "") < ($1["registry_entry_id"] as? String ?? "") }
    }
    static func observations() -> [String: Any] {
        startSpaceObservation()
        var result: [String: Any] = ["audio": audioObservation(), "display_brightness": brightnessObservation(),
            "caps_lock": capsLockObservation(),
            "space_identity": ["available": false, "reason": "no_public_active_space_identity_api"],
            "active_space_changes": spaceChanges.metadata.merging([
                "observer_active": spaceObserver != nil, "worker_generation": SystemBridgeRuntime.generation
            ]) { _, next in next },
            "observed_at_uptime": ProcessInfo.processInfo.systemUptime]
        if let app = NSWorkspace.shared.frontmostApplication,
           let identity = try? SystemControl.appIdentity(app) { result["frontmost"] = identity }
        if let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]], rows.count <= 10000 {
            result["on_screen_window_ids"] = rows.compactMap { $0[kCGWindowNumber as String] as? Int }.sorted()
        }
        return result
    }
    static func inventory(preferenceValues: [String: Any]? = nil,
                          observationValues: [String: Any]? = nil) -> [String: Any] {
        let prefs = preferenceValues ?? preferences()
        let observed = observationValues ?? observations()
        var rows: [[String: Any]] = []
        for action in (special.keys.sorted() + symbolic.keys.sorted() + fixed.keys.sorted() + ["caps_lock"]) {
            if let value = try? actionPlan(action, modifiers: [], preferences: prefs) {
                let lockAvailable = (observed["caps_lock"] as? [String: Any])?["available"] as? Bool ?? false
                rows.append(value.metadata.merging(["available": action == "caps_lock" ? lockAvailable : true,
                    "accepts_modifiers": special[action] != nil,
                    "effect_support": action == "caps_lock" ? "modifier_lock_readback; setter_access_not_probed"
                        : special[action] != nil ? "hardware_or_media_handler_dependent" : "configured_system_shortcut",
                    "execution_requires": "explicit_system_scope; fresh_frontmost; Accessibility; post_access; idle_user_keys"
                ]) { _, next in next })
            } else {
                rows.append(["action": action, "available": false, "accepts_modifiers": false,
                             "reason": "shortcut_absent_disabled_or_unsupported"])
            }
        }
        rows += publicPlans(prefs).map { plan in
            plan.metadata.merging(["available": true, "accepts_modifiers": false,
                "effect_support": "public_registered_system_shortcut",
                "semantic_action": "unknown; public Carbon API does not expose action IDs",
                "execution_requires": "explicit_system_scope; fresh_frontmost; Accessibility; post_access; idle_user_keys"
            ]) { _, next in next }
        }
        return ["schema": "kirabridge.system-keyboard.v1", "event_scope": "system",
                "actions": rows, "observations": observed,
                "permissions": ["actor_pid": Int(getpid()), "accessibility_granted": AXIsProcessTrusted(),
                    "post_events_granted": CGPreflightPostEventAccess(),
                    "input_monitoring_granted": CGPreflightListenEventAccess(),
                    "screen_capture_granted": CGPreflightScreenCaptureAccess(),
                    "permission_requested": false],
                "function_keys": (1...20).map { "f\($0)" },
                "fn_modifier": true, "fn_hardware_key": "not_synthesized; globe_behaviour_not_guaranteed",
                "unsupported_hardware": ["touch_id", "power_button", "secure_attention"],
                "system_processing_confirmed": false, "permission_requested": false]
    }
    static func handle(_ operation: String, arguments: [String: Any]) throws -> [String: Any]? {
        switch operation {
        case "keyboard.system_inventory":
            var result = inventory()
            if let spec = arguments["key"] as? [String: Any] {
                let modifiers = arguments["modifiers"] as? [String] ?? []
                let resolved = try SystemKeyboard.resolve(spec, modifiers: modifiers,
                                                          layout: SystemKeyboard.currentLayout())
                let match = modifiers.contains("fn") ? nil : registeredMatch(
                    code: Int(resolved.code), flags: resolved.flags, preferences: preferences())
                result["shortcut_match"] = match?.metadata as Any? ?? NSNull()
            }
            return result
        case "keyboard.system_key": return try key(arguments)
        default: return nil
        }
    }
}

import Foundation
import CoreGraphics

@main
struct CapsEventFlagsHarness {
    @MainActor static func main() throws {
        var checks = 0
        let modifiers: [CGEventFlags] = [.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn]
        for bitset in 0..<32 {
            let requested = modifiers.enumerated().reduce(CGEventFlags()) {
                bitset & (1 << $1.offset) != 0 ? $0.union($1.element) : $0
            }
            for caps in [false, true] {
                for extra: CGEventFlags in [[], .maskAlphaShift] {
                    let applied = SystemKeyboard.mergedEventFlags(requested.union(extra), observedCapsLock: caps)
                    precondition(applied.subtracting(.maskAlphaShift) == requested)
                    precondition(applied.contains(.maskAlphaShift) == caps)
                    checks += 1
                }
                let pair = try SystemKeyboard.events(["keyboard_type": 40], code: 0,
                    flags: requested, observedCapsLock: caps)
                for event in [pair.0, pair.1] {
                    precondition(event.flags.subtracting(.maskAlphaShift) == requested)
                    precondition(event.flags.contains(.maskAlphaShift) == caps)
                    checks += 1
                }
            }
        }
        let literal = try SystemKeyboard.events(["keyboard_type": 40], code: 0, flags: [],
            preserveCapsLock: false, observedCapsLock: true)
        precondition(literal.0.flags.isEmpty && literal.1.flags.isEmpty)
        checks += 1
        for text in ["aA", "é😀"] {
            let units = Array(text.utf16)
            let pair = try SystemKeyboard.unicodeEvents(["keyboard_type": 40], units: units)
            for event in [pair.0, pair.1] {
                precondition(event.flags.isEmpty, "Literal Unicode inherited Caps Lock")
                var count = 0
                event.keyboardGetUnicodeString(maxStringLength: 0, actualStringLength: &count, unicodeString: nil)
                var actual = [UniChar](repeating: 0, count: count)
                actual.withUnsafeMutableBufferPointer {
                    event.keyboardGetUnicodeString(maxStringLength: $0.count, actualStringLength: &count,
                        unicodeString: $0.baseAddress)
                }
                precondition(actual == units)
                checks += 1
            }
        }
        for caps in [false, true] {
            let plan = SystemSpecialKeys.Plan(action: "fixture", route: "quartz_hid", code: 0,
                flags: [.maskCommand, .maskShift], registered: true, preferenceID: nil)
            let pair = try SystemSpecialKeys.events(plan, observedCapsLock: caps)
            for event in [pair.0, pair.1] {
                precondition(event.flags.subtracting(.maskAlphaShift) == [.maskCommand, .maskShift])
                precondition(event.flags.contains(.maskAlphaShift) == caps)
                checks += 1
            }
        }
        for route in ["modifier_lock_state", "system_defined_hid", "quartz_hid"] {
            var reads = 0
            let conflict = SystemSpecialKeys.heldKeyConflict(route: route) { reads += 1; return true }
            precondition(conflict == (route == "quartz_hid"))
            precondition(reads == (route == "quartz_hid" ? 1 : 0))
            checks += 1
        }
        try SystemKeyboard.inputAllowed(postAccess: true, flags: .maskAlphaShift, keyHeld: false)
        checks += 1
        do {
            try SystemKeyboard.inputAllowed(postAccess: true, flags: .maskAlphaShift, keyHeld: true)
            fatalError("An actual held Quartz key was accepted")
        } catch let failure as SystemBridgeFailure {
            precondition(!failure.effectUnknown)
            checks += 1
        }
        print("{\"checks\":\(checks),\"event_posts\":0,\"os_writes\":0,\"native_ui_calls\":0,\"permission_requests\":0}")
    }
}

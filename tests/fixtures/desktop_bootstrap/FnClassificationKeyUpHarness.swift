import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

@main
struct FnClassificationKeyUpHarness {
    @MainActor static func main() throws {
        var checks = 0
        let codes = [123, 124, 125, 126, 122, 120, 99, 118, 96, 97, 98, 100,
                     101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90]
        let modifierFlags: [CGEventFlags] = [.maskCommand, .maskControl, .maskAlternate, .maskShift]
        for code in codes {
            for mask in 0..<16 {
                let other = modifierFlags.enumerated().reduce(CGEventFlags()) {
                    mask & (1 << $1.offset) == 0 ? $0 : $0.union($1.element)
                }
                let requested = other.union(.maskSecondaryFn)
                let plan = SystemSpecialKeys.Plan(action: "fixture", route: "quartz_hid", code: code,
                    flags: requested, registered: true, preferenceID: nil)
                for caps in [false, true] {
                    for explicitFn in [false, true] {
                        let pair = try SystemSpecialKeys.events(plan, observedCapsLock: caps, explicitFn: explicitFn)
                        precondition(pair.0.flags.subtracting(.maskAlphaShift) == requested)
                        precondition(pair.1.flags.subtracting(.maskAlphaShift) == (explicitFn ? requested : other))
                        precondition(pair.0.flags.contains(.maskAlphaShift) == caps
                                     && pair.1.flags.contains(.maskAlphaShift) == caps)
                        precondition(pair.0.getIntegerValueField(.keyboardEventKeycode) == code
                                     && pair.1.getIntegerValueField(.keyboardEventKeycode) == code)
                        precondition(pair.0.type == .keyDown && pair.1.type == .keyUp)
                        checks += 1
                    }
                }
            }
        }
        let plain = SystemSpecialKeys.Plan(action: "fixture", route: "quartz_hid", code: 48,
            flags: [.maskCommand, .maskSecondaryFn], registered: false, preferenceID: nil)
        let pair = try SystemSpecialKeys.events(plain, observedCapsLock: true, explicitFn: false)
        precondition(pair.1.flags == [.maskCommand, .maskSecondaryFn, .maskAlphaShift])
        checks += 1
        let f11 = try SystemSpecialKeys.actionPlan("show_desktop", modifiers: [], preferences: [
            "36": ["enabled": true, "value": ["type": "standard", "parameters": [65535, 103, 8388608]]]
        ])
        let f11Pair = try SystemSpecialKeys.events(f11, observedCapsLock: true, explicitFn: false)
        precondition(f11Pair.0.flags == [.maskSecondaryFn, .maskAlphaShift]
                     && f11Pair.1.flags == .maskAlphaShift)
        precondition(SystemSpecialKeys.modifierReleasePlan(f11, explicitFn: false, capsLock: true).isEmpty)
        checks += 1
        let nx = try SystemSpecialKeys.actionPlan("volume_up", modifiers: ["fn", "option"], preferences: [:])
        let mediaPair = try SystemSpecialKeys.events(nx, explicitFn: false)
        precondition(mediaPair.0.flags.contains(.maskSecondaryFn) && mediaPair.1.flags.contains(.maskSecondaryFn))
        checks += 1
        print(String(decoding: try JSONSerialization.data(withJSONObject: ["checks": checks,
            "real_event_posts": 0, "permission_requests": 0, "classification_key_up_clears_fn": true,
            "explicit_fn_preserved": true, "additional_event_posts": 0]), as: UTF8.self))
    }
}

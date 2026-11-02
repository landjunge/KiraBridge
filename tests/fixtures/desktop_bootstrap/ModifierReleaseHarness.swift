import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

@main
struct ModifierReleaseHarness {
    @MainActor static func main() throws {
        var checks = 0
        let flags: [CGEventFlags] = [.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn]
        for mask in 0..<32 {
            let requested = flags.enumerated().reduce(CGEventFlags()) { mask & (1 << $1.offset) == 0 ? $0 : $0.union($1.element) }
            let plan = SystemSpecialKeys.Plan(action: "fixture", route: "quartz_hid", code: 48,
                flags: requested, registered: true, preferenceID: nil)
            for explicitFn in [false, true] {
                for caps in [false, true] {
                    let releasePlan = SystemSpecialKeys.modifierReleasePlan(plan, explicitFn: explicitFn, capsLock: caps)
                    let expected = requested.intersection([.maskCommand, .maskControl, .maskAlternate, .maskShift]).rawValue.nonzeroBitCount
                        + (explicitFn && requested.contains(.maskSecondaryFn) ? 1 : 0)
                    precondition(releasePlan.count == expected && Set(releasePlan.map { $0.code }).count == expected)
                    precondition(releasePlan.allSatisfy { $0.flags.contains(.maskAlphaShift) == caps })
                    if let final = releasePlan.last { precondition(final.flags == (caps ? .maskAlphaShift : [])) }
                    var events: [CGEvent] = [], guards = 0
                    let posted = try SystemSpecialKeys.releaseModifiers(plan, explicitFn: explicitFn,
                        capsLock: { caps }, validate: { guards += 1 }, post: { events.append($0) })
                    precondition(posted == expected && guards == expected && events.count == expected)
                    precondition(events.allSatisfy { $0.type == .flagsChanged && $0.flags.contains(.maskAlphaShift) == caps })
                    precondition(events.map { $0.getIntegerValueField(.keyboardEventKeycode) } == releasePlan.map { Int64($0.code) })
                    checks += 1
                }
            }
        }
        let nx = try SystemSpecialKeys.actionPlan("volume_up", modifiers: ["option", "shift"], preferences: [:])
        precondition(SystemSpecialKeys.modifierReleasePlan(nx, explicitFn: false, capsLock: true).isEmpty)
        let caps = try SystemSpecialKeys.actionPlan("caps_lock", modifiers: [], preferences: [:])
        precondition(SystemSpecialKeys.modifierReleasePlan(caps, explicitFn: false, capsLock: true).isEmpty)
        checks += 2
        precondition(SystemSpecialKeys.physicalModifiersIdle(read: { _ in false }))
        precondition(!SystemSpecialKeys.physicalModifiersIdle(read: { $0 == 54 }))
        precondition(!SystemSpecialKeys.physicalModifiersIdle(read: { $0 == 63 }))
        precondition(SystemSpecialKeys.physicalModifiersIdle(read: { $0 == 57 }))
        checks += 4
        var order: [String] = []
        let repeated = try SystemSpecialKeys.pairs(3, validate: {}, post: { order.append($0 ? "down" : "up") },
            release: { order.append("release"); return 1 })
        precondition(order == ["down", "up", "release", "down", "up", "release", "down", "up", "release"])
        precondition(repeated["post_calls_returned"] as? Int == 9
                     && repeated["key_pair_post_calls_returned"] as? Int == 6
                     && repeated["modifier_release_post_calls_returned"] as? Int == 3)
        checks += 1
        order = []
        do {
            _ = try SystemSpecialKeys.pairs(1, validate: {}, post: {
                order.append($0 ? "down" : "up")
                if $0 { throw SystemSpecialKeys.failure("partial down") }
            }, release: { order.append("release"); return 1 })
            fatalError("Partial event post was reported completed")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && order == ["down", "up", "release"]); checks += 1
        }
        order = []
        do {
            _ = try SystemSpecialKeys.pairs(1, validate: {}, post: { order.append($0 ? "down" : "up") },
                release: { order.append("release"); throw SystemSpecialKeys.failure("partial modifier release") })
            fatalError("Partial release was reported completed")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && order == ["down", "up", "release"]); checks += 1
        }
        let nxResult = try SystemSpecialKeys.pairs(2, validate: {}, post: { _ in })
        precondition(nxResult["post_calls_returned"] as? Int == 4
                     && nxResult["modifier_release_post_calls_returned"] as? Int == 0)
        checks += 1
        print(String(decoding: try JSONSerialization.data(withJSONObject: [
            "checks": checks, "real_event_posts": 0, "permission_requests": 0,
            "fixture_keyboard_posts": 6, "fixture_modifier_releases": 3]), as: UTF8.self))
    }
}

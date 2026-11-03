import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

@main
struct ModifierOwnershipHarness {
    @MainActor static func main() throws {
        var checks = 0
        let map: [(CGKeyCode, CGEventFlags)] = SystemSpecialKeys.leftModifierKeys
        for ownedMask in 0..<32 {
            let ownedFlags = map.enumerated().reduce(CGEventFlags()) { ownedMask & (1 << $1.offset) != 0 ? $0.union($1.element.1) : $0 }
            for observedMask in 0..<32 {
                let held = Set(map.enumerated().filter { observedMask & (1 << $0.offset) != 0 }.map { $0.element.0 })
                precondition(SystemSpecialKeys.modifierStateCompatible(ownedFlags: ownedFlags,
                    read: { held.contains($0) }) == (observedMask & ~ownedMask == 0))
                checks += 1
            }
            for right: CGKeyCode in [54, 60, 61, 62] {
                precondition(!SystemSpecialKeys.modifierStateCompatible(ownedFlags: ownedFlags,
                    read: { $0 == right })); checks += 1
            }
        }
        precondition(!SystemSpecialKeys.physicalModifiersIdle(read: { $0 == 55 || $0 == 56 }))
        precondition(SystemSpecialKeys.modifierStateCompatible(ownedFlags: [.maskCommand, .maskShift],
            read: { $0 == 55 || $0 == 56 }))
        precondition(SystemSpecialKeys.modifierStateCompatible(ownedFlags: [.maskControl, .maskSecondaryFn],
            read: { $0 == 59 || $0 == 63 }))
        precondition(SystemSpecialKeys.physicalModifiersIdle(read: { $0 == 57 }))
        checks += 4
        let plan = try SystemSpecialKeys.actionPlan("app_previous", modifiers: [], preferences: [:])
        var owned = CGEventFlags(), observed = Set<CGKeyCode>(), order: [String] = []
        func guardState() throws {
            guard SystemSpecialKeys.modifierStateCompatible(ownedFlags: owned, read: { observed.contains($0) }) else {
                throw SystemSpecialKeys.failure("Unowned state fixture")
            }
        }
        var settlePolls = 0
        let receipt = try SystemSpecialKeys.pairs(1, validate: {
            precondition(SystemSpecialKeys.physicalModifiersIdle(read: { observed.contains($0) }))
        }, post: { down in
            try guardState(); order.append(down ? "down" : "up")
            if down { owned = plan.flags; observed = [55, 56] }
        }, release: {
            let returned = try SystemSpecialKeys.releaseModifiers(plan, explicitFn: false, capsLock: { true },
                validate: guardState, post: { event in
                    let code = CGKeyCode(event.getIntegerValueField(.keyboardEventKeycode))
                    order.append("release\(code)")
                    // CG post return can precede HID state updates. Both
                    // synthetic keys remain reported through release56.
                    precondition(observed == [55, 56] && owned == plan.flags)
                    precondition(event.flags.contains(.maskAlphaShift))
                })
            var time = 0.0, reads = 0
            settlePolls = try SystemSpecialKeys.settleModifierState(ownedFlags: owned,
                now: { time }, pause: { time += $0 }, validate: guardState, read: {
                    reads += 1
                    if reads == 3 { observed = [] }
                    return (observed, observed.isEmpty ? [] : plan.flags)
                })
            precondition(settlePolls == 3 && reads == 3 && time == 0.002)
            owned = []; return returned
        })
        precondition(order == ["down", "up", "release55", "release56"] && observed.isEmpty)
        precondition(receipt["post_calls_returned"] as? Int == 4
                     && receipt["key_pair_post_calls_returned"] as? Int == 2
                     && receipt["modifier_release_post_calls_returned"] as? Int == 2)
        checks += 1
        owned = []; observed = []; order = []
        do {
            _ = try SystemSpecialKeys.pairs(1, validate: {}, post: { down in
                try guardState(); order.append(down ? "down" : "up")
                if down { owned = plan.flags; observed = [55, 56] }
                else { observed.insert(60) } // A new unowned right Shift belongs to the user.
            }, release: {
                try SystemSpecialKeys.releaseModifiers(plan, explicitFn: false, capsLock: { false },
                    validate: guardState, post: { _ in fatalError("Unowned modifier must not be released") })
            })
            fatalError("Interference was accepted")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && order == ["down", "up"] && observed.contains(60)); checks += 1
        }
        precondition(!SystemSpecialKeys.modifierStateCompatible(ownedFlags: .maskShift,
            read: { $0 == 55 || $0 == 56 })) // A previous complete batch owns no new Command.
        checks += 1
        var time = 0.0, flagReads = 0
        let flagOnly = try SystemSpecialKeys.settleModifierState(ownedFlags: [.maskControl, .maskSecondaryFn],
            now: { time }, pause: { time += $0 }, validate: {}, read: {
                flagReads += 1
                return ([], flagReads < 3 ? [.maskControl, .maskSecondaryFn] : [])
            })
        precondition(flagOnly == 3 && flagReads == 3)
        checks += 1
        order = []; time = 0
        var releaseBatches = 0
        do {
            _ = try SystemSpecialKeys.pairs(1, validate: {},
                post: { order.append($0 ? "down" : "up") }, release: {
                    releaseBatches += 1
                    order += ["release55", "release56"]
                    _ = try SystemSpecialKeys.settleModifierState(ownedFlags: plan.flags,
                        now: { time }, pause: { _ in time += 0.05 }, validate: {},
                        read: { ([55, 56], plan.flags) })
                    return 2
                })
            fatalError("Unsettled modifier state accepted")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && releaseBatches == 1
                         && order == ["down", "up", "release55", "release56"] && time <= 0.25)
            checks += 1
        }
        time = 0
        do {
            _ = try SystemSpecialKeys.settleModifierState(ownedFlags: plan.flags,
                now: { time }, pause: { time += $0 }, validate: {}, read: { ([55, 56, 60], plan.flags) })
            fatalError("Unowned right modifier accepted during settle")
        } catch let error as SystemBridgeFailure { precondition(error.effectUnknown && time == 0); checks += 1 }
        let noModifiers = try SystemSpecialKeys.settleModifierState(ownedFlags: [],
            now: { fatalError("No modifier needs settling") }, pause: { _ in fatalError() },
            validate: { fatalError() }, read: { fatalError() })
        precondition(noModifiers == 0)
        checks += 1
        print(String(decoding: try JSONSerialization.data(withJSONObject: ["checks": checks,
            "real_event_posts": 0, "permission_requests": 0,
            "delayed_hid_clear_polls": settlePolls, "timeout_release_batches": releaseBatches,
            "cmd_shift_tab_fixture_total_posts": 4]), as: UTF8.self))
    }
}

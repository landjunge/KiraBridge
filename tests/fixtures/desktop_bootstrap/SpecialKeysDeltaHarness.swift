import Carbon
import Foundation
import CoreGraphics

@main
struct SpecialKeysDeltaHarness {
    @MainActor static func main() throws {
        var checks = 0
        func carbon(_ code: Any, modifiers: Any = controlKey, enabled: Bool = true) -> [String: Any] {
            [kHISymbolicHotKeyCode as String: code,
             kHISymbolicHotKeyModifiers as String: modifiers,
             kHISymbolicHotKeyEnabled as String: enabled]
        }
        let rows = [carbon(123), carbon(125), carbon(125), carbon(124, enabled: false),
                    carbon(true), carbon(128), carbon(120, modifiers: 1)]
        let prefs: [String: Any] = ["_carbon_symbolic_hotkeys": rows]
        let plans = SystemSpecialKeys.publicPlans(prefs)
        precondition(plans.count == 2 && plans.allSatisfy { $0.registered && $0.preferenceID == nil })
        checks += 1
        let left = plans.first { $0.code == 123 }!
        precondition(left.action == "registered_shortcut_123_262144" && left.flags == .maskControl)
        checks += 1
        precondition(SystemSpecialKeys.registeredMatch(code: 123, flags: .maskControl,
                                                      preferences: prefs)?.action == left.action)
        checks += 1
        let exact = try SystemSpecialKeys.actionPlan(left.action, modifiers: [], preferences: prefs)
        precondition(exact == left)
        checks += 1
        do {
            _ = try SystemSpecialKeys.actionPlan(left.action, modifiers: [], preferences: [:])
            fatalError("Unregistered public shortcut was accepted")
        } catch is SystemBridgeFailure { checks += 1 }
        var named = prefs
        named["79"] = ["enabled": true,
                       "value": ["type": "standard", "parameters": [65535, 123, 8650752]]]
        precondition(SystemSpecialKeys.publicPlans(named).count == 1)
        precondition(SystemSpecialKeys.registeredMatch(code: 123, flags: .maskControl,
                                                      preferences: named)?.action == "space_left")
        checks += 2
        let preservedFn = SystemSpecialKeys.rawKeyPlan(code: 123, flags: [.maskControl, .maskSecondaryFn],
            explicitFn: true, preferences: named)
        precondition(preservedFn.action == "explicit_key" && !preservedFn.registered
                     && preservedFn.flags == [.maskControl, .maskSecondaryFn])
        checks += 1
        let ordinaryLeft = SystemSpecialKeys.rawKeyPlan(code: 123, flags: .maskControl,
            explicitFn: false, preferences: named)
        precondition(ordinaryLeft.action == "space_left" && ordinaryLeft.registered)
        checks += 1
        let mixed = ["_carbon_symbolic_hotkeys": [carbon(48, modifiers: cmdKey),
                                                 carbon(48, modifiers: cmdKey | shiftKey)]]
        precondition(SystemSpecialKeys.publicPlans(mixed).isEmpty)
        checks += 1
        var observation = SystemSpecialKeys.SpaceChanges()
        observation.observe(at: 9)
        precondition(observation.count == 0 && observation.startedAt == nil)
        checks += 1
        observation.begin(at: 100)
        observation.observe(at: 100.1)
        observation.observe(at: 99)
        observation.observe(at: Double.nan)
        precondition(observation.count == 1 && observation.lastObservedAt == 100.1)
        checks += 1
        observation.begin(at: 500)
        observation.observe(at: 102)
        precondition(observation.count == 2 && observation.startedAt == 100
                     && observation.lastObservedAt == 102)
        checks += 1
        precondition(observation.metadata["notification_count"] as? Int == 2)
        checks += 1
        let capsPlan = try SystemSpecialKeys.actionPlan("caps_lock", modifiers: [], preferences: [:])
        precondition(capsPlan.route == "modifier_lock_state" && capsPlan.registered && capsPlan.code == 57)
        checks += 1
        var fixtureLock = false, setCalls = [Bool]()
        let capsReceipt = try SystemSpecialKeys.modifierLock(1, validate: {}, read: { fixtureLock }, set: {
            fixtureLock = $0; setCalls.append($0)
        })
        precondition(fixtureLock && setCalls == [true] && capsReceipt["effect_verified"] as? Bool == true
                     && capsReceipt["post_calls_returned"] as? Int == 0
                     && capsReceipt["scope"] as? String == "native_state_readback")
        checks += 1
        setCalls = []
        let double = try SystemSpecialKeys.modifierLock(2, validate: {}, read: { fixtureLock }, set: {
            fixtureLock = $0; setCalls.append($0)
        })
        precondition(fixtureLock && setCalls == [false, true]
                     && double["state_before"] as? Bool == true && double["state_after"] as? Bool == true)
        checks += 1
        var validations = 0
        setCalls = []
        do {
            _ = try SystemSpecialKeys.modifierLock(1, validate: {
                throw SystemSpecialKeys.failure("no focus")
            }, read: { fixtureLock }, set: { setCalls.append($0) })
            fatalError("Missing guard accepted")
        } catch let error as SystemBridgeFailure {
            precondition(!error.effectUnknown && setCalls.isEmpty); checks += 1
        }
        do {
            _ = try SystemSpecialKeys.modifierLock(1, validate: {}, read: { fixtureLock }, set: {
                setCalls.append($0)
                throw SystemSpecialKeys.failure("setter denied")
            })
            fatalError("Failed setter accepted")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && setCalls == [false]); checks += 1
        }
        setCalls = []
        do {
            _ = try SystemSpecialKeys.modifierLock(1, validate: {}, read: { fixtureLock }, set: {
                setCalls.append($0)  // Does not change fixtureLock: readback must reject.
            })
            fatalError("Wrong readback accepted")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && setCalls == [false]); checks += 1
        }
        setCalls = []
        do {
            _ = try SystemSpecialKeys.modifierLock(2, validate: {
                validations += 1
                if validations == 2 { throw SystemSpecialKeys.failure("focus changed") }
            }, read: { fixtureLock }, set: { fixtureLock = $0; setCalls.append($0) })
            fatalError("Partial lock transaction accepted")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && setCalls == [false]); checks += 1
        }
        let output: [String: Any] = ["checks": checks, "real_event_posts": 0,
                                    "permission_requests": 0]
        print(String(decoding: try JSONSerialization.data(withJSONObject: output), as: UTF8.self))
    }
}

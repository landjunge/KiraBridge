import AppKit
import ApplicationServices
import Foundation
import CoreGraphics

@main
struct SpecialKeysModifiersHarness {
    @MainActor static func main() throws {
        var checks = 0
        let matrix: [[String]] = [[], ["option"], ["option", "shift"], ["control"],
            ["command"], ["fn"], ["command", "control", "option", "shift", "fn"]]
        for action in SystemSpecialKeys.special.keys.sorted() {
            for modifiers in matrix {
                let plan = try SystemSpecialKeys.actionPlan(action, modifiers: modifiers, preferences: [:])
                let events = try SystemSpecialKeys.events(plan)
                let down = NSEvent(cgEvent: events.0)!, up = NSEvent(cgEvent: events.1)!
                precondition(Set(SystemSpecialKeys.modifierNames(plan.flags)) == Set(modifiers))
                precondition(events.0.flags.intersection(SystemSpecialKeys.allowedFlags) == plan.flags)
                precondition(events.1.flags.intersection(SystemSpecialKeys.allowedFlags) == plan.flags)
                precondition((down.data1 >> 16) == plan.code && (up.data1 >> 16) == plan.code)
                precondition(((down.data1 >> 8) & 255) == 10 && ((up.data1 >> 8) & 255) == 11)
                checks += 1
            }
        }
        func refuse(_ action: String, _ modifiers: [String]) {
            do {
                _ = try SystemSpecialKeys.actionPlan(action, modifiers: modifiers, preferences: [:])
                fatalError("Unexpected action modifiers accepted")
            } catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); checks += 1 }
            catch { fatalError("Unexpected error") }
        }
        refuse("volume_up", ["option", "option"])
        refuse("volume_up", ["unknown"])
        refuse("volume_up", ["command", "control", "option", "shift", "fn", "shift"])
        for action in ["space_left", "caps_lock", "app_next", "registered_shortcut_123_262144"] {
            refuse(action, ["option"])
        }
        let observed: [String: Any] = ["caps_lock": ["available": true, "state": false]]
        let inventory = SystemSpecialKeys.inventory(preferenceValues: [:], observationValues: observed)
        let rows = inventory["actions"] as! [[String: Any]]
        for row in rows {
            let action = row["action"] as! String
            precondition(row["accepts_modifiers"] as? Bool == (SystemSpecialKeys.special[action] != nil))
        }
        checks += 1
        let receipt: [String: Any] = ["checks": checks, "nx_action_count": SystemSpecialKeys.special.count,
            "combinations_per_action": matrix.count, "real_event_posts": 0, "hardware_writes": 0]
        print(String(decoding: try JSONSerialization.data(withJSONObject: receipt), as: UTF8.self))
    }
}

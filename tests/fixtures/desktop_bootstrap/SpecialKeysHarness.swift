import AppKit
import ApplicationServices
import CoreGraphics

@main
struct SpecialKeysHarness {
    @MainActor static func main() throws {
        var checks = 0, simulatedPosts = 0
        func refuse(unknown: Bool = false, _ operation: () throws -> Void) {
            do { try operation(); fatalError("Expected system input refusal") }
            catch let error as SystemBridgeFailure {
                precondition(error.effectUnknown == unknown); checks += 1
            } catch { fatalError("Unexpected error: \(error)") }
        }
        func binding(_ code: Any = 123, flags: Any = 8650752, enabled: Bool = true) -> [String: Any] {
            ["enabled": enabled, "value": ["type": "standard", "parameters": [65535, code, flags]]]
        }
        let prefs: [String: Any] = ["79": binding(), "81": binding(124),
                                    "32": binding(126), "33": binding(125)]
        let left = try SystemSpecialKeys.actionPlan("space_left", modifiers: [], preferences: prefs)
        precondition(left.code == 123 && left.preferenceID == "79"
                     && left.registered && left.flags.contains(.maskControl))
        checks += 1
        let custom = try SystemSpecialKeys.actionPlan("space_left", modifiers: [],
            preferences: ["79": binding(115, flags: 1572864)])
        precondition(custom.code == 115 && custom.flags == [.maskCommand, .maskAlternate])
        checks += 1
        for invalid: [String: Any] in [[:], ["79": binding(enabled: false)],
            ["79": binding(true)], ["79": binding(128)], ["79": binding(flags: 1)],
            ["79": ["enabled": 1, "value": ["type": "standard", "parameters": [65535, 123, 8650752]]]],
            ["79": ["enabled": true, "value": ["type": "button", "parameters": [65535, 123, 8650752]]]]
        ] { refuse { _ = try SystemSpecialKeys.symbolicPlan("space_left", preferences: invalid) } }
        refuse { _ = try SystemSpecialKeys.actionPlan("power", modifiers: [], preferences: prefs) }
        refuse { _ = try SystemSpecialKeys.actionPlan("space_left", modifiers: ["command"], preferences: prefs) }
        refuse { _ = try SystemSpecialKeys.plan(["action": "volume_up"], preferences: prefs) }
        refuse { _ = try SystemSpecialKeys.plan(["scope": "system", "action": "mute", "key": [:]], preferences: prefs) }
        precondition(SystemSpecialKeys.registeredMatch(code: 123, flags: .maskControl, preferences: prefs)?.action == "space_left")
        precondition(SystemSpecialKeys.registeredMatch(code: 123, flags: [.maskControl, .maskShift], preferences: prefs) == nil)
        precondition(SystemSpecialKeys.registeredMatch(code: 12, flags: .maskCommand, preferences: prefs) == nil)
        precondition(SystemSpecialKeys.registeredMatch(code: 48, flags: .maskCommand, preferences: prefs)?.action == "app_next")
        checks += 4
        let ambiguous: [String: Any] = ["79": binding(), "81": binding()]
        precondition(SystemSpecialKeys.registeredMatch(code: 123, flags: .maskControl, preferences: ambiguous) == nil)
        checks += 1
        for action in SystemSpecialKeys.special.keys.sorted() {
            let plan = try SystemSpecialKeys.actionPlan(action, modifiers: [], preferences: [:])
            let pair = try SystemSpecialKeys.events(plan)
            let down = NSEvent(cgEvent: pair.0)!, up = NSEvent(cgEvent: pair.1)!
            precondition(down.type == .systemDefined && down.subtype.rawValue == 8)
            precondition((down.data1 >> 16) == plan.code && ((down.data1 >> 8) & 255) == 10)
            precondition((up.data1 >> 16) == plan.code && ((up.data1 >> 8) & 255) == 11)
            checks += 1
        }
        let chord = try SystemSpecialKeys.events(left)
        precondition(chord.0.type == .keyDown && chord.1.type == .keyUp)
        precondition(chord.0.getIntegerValueField(.keyboardEventKeycode) == 123
                     && chord.0.flags.contains(.maskControl))
        checks += 1
        var validations = 0
        let receipt = try SystemSpecialKeys.pairs(3, validate: { validations += 1 }, post: { _ in simulatedPosts += 1 })
        precondition(validations == 3 && simulatedPosts == 6
                     && receipt["posted_pairs"] as? Int == 3
                     && receipt["system_processing_confirmed"] as? Bool == false)
        checks += 1
        refuse { _ = try SystemSpecialKeys.pairs(0, validate: {}, post: { _ in fatalError() }) }
        refuse { _ = try SystemSpecialKeys.pairs(21, validate: {}, post: { _ in fatalError() }) }
        refuse { _ = try SystemSpecialKeys.pairs(1, validate: { throw SystemSpecialKeys.failure("fixture") }, post: { _ in fatalError() }) }
        var partialPosts = [Bool]()
        refuse(unknown: true) {
            _ = try SystemSpecialKeys.pairs(1, validate: {}, post: { down in
                partialPosts.append(down)
                if down { throw SystemSpecialKeys.failure("fixture") }
            })
        }
        precondition(partialPosts == [true, false]); checks += 1
        var calls = 0, posted = [Bool]()
        refuse(unknown: true) {
            _ = try SystemSpecialKeys.pairs(2, validate: {
                calls += 1
                if calls == 2 { throw SystemSpecialKeys.failure("changed focus") }
            }, post: { posted.append($0) })
        }
        precondition(posted == [true, false]); checks += 1
        let inventory = SystemSpecialKeys.inventory(preferenceValues: prefs, observationValues: ["fixture": true])
        let rows = inventory["actions"] as! [[String: Any]]
        let row = rows.first { $0["action"] as? String == "space_left" }!
        precondition((row["key"] as? [String: Int])?["key_code"] == 123
                     && (row["modifiers"] as? [String])?.contains("control") == true)
        let disabled = rows.first { $0["action"] as? String == "show_desktop" }!
        precondition(disabled["available"] as? Bool == false
                     && (inventory["observations"] as? [String: Bool])?["fixture"] == true)
        checks += 1
        let output: [String: Any] = ["checks": checks, "simulated_posts": simulatedPosts,
            "system_event_types": SystemSpecialKeys.special.count, "real_event_posts": 0,
            "real_hardware_writes": 0, "permission_requests": 0]
        print(String(decoding: try JSONSerialization.data(withJSONObject: output, options: .sortedKeys), as: UTF8.self))
    }
}

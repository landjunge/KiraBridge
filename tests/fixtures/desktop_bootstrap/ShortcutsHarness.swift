import Foundation
import ApplicationServices

@main
struct ShortcutsHarness {
    @MainActor static func main() throws {
        var decoderCases = 0, scanCases = 0, cacheCases = 0
        for mask in 0...15 {
            let observed = SystemShortcuts.shortcut(["cmd_char": "a", "virtual_key": 0, "glyph": 0, "modifier_mask": mask])
            let candidate = observed["candidate"] as! [String: Any]
            let modifiers = candidate["modifiers"] as! [String]
            precondition(modifiers.contains("command") == (mask & 8 == 0))
            for (bit, name) in [(1, "shift"), (2, "option"), (4, "control")] {
                precondition(modifiers.contains(name) == (mask & bit != 0))
            }
            precondition(observed["status"] as? String == "observed_unconfirmed" && observed["verified"] as? Bool == false)
            decoderCases += 1
        }
        let none = SystemShortcuts.shortcut(["cmd_char": "", "virtual_key": 0, "glyph": 0, "modifier_mask": 0])
        precondition(none["candidate"] is NSNull && none["status"] as? String == "none_observed"); decoderCases += 1
        let unknown = SystemShortcuts.shortcut(["cmd_char": "a", "modifier_mask": 16])
        precondition(unknown["candidate"] is NSNull && unknown["modifier_mask"] as? Int == 16); decoderCases += 1
        let missing = SystemShortcuts.shortcut(["cmd_char": "a"])
        precondition(missing["candidate"] is NSNull && missing["status"] as? String == "unavailable"); decoderCases += 1
        let modifierKey = SystemShortcuts.shortcut(["cmd_char": "", "virtual_key": 54, "modifier_mask": 0])
        precondition(modifierKey["candidate"] is NSNull && modifierKey["virtual_key"] as? Int == 54); decoderCases += 1
        let glyph = SystemShortcuts.shortcut(["cmd_char": "", "virtual_key": 0, "glyph": 13, "modifier_mask": 0])
        precondition(glyph["candidate"] is NSNull && glyph["glyph"] as? Int == 13); decoderCases += 1
        let physical = SystemShortcuts.shortcut(["virtual_key": 53, "modifier_mask": 8])
        precondition((physical["candidate"] as? [String: Any])?["modifiers"] as? [String] == []); decoderCases += 1

        var reads = 0
        let tree = SystemShortcuts.scan(root: 0, now: { 0 }, equal: ==, read: { node, _, alive in
            precondition(alive()); reads += 1
            let fields: [String: Any] = node == 0 ? ["role": "AXMenuBar", "name": ""] :
                ["role": "AXMenuItem", "name": node == 1 ? "Edit" : "Select All", "identifier": "item-\(node)",
                 "enabled": node == 2, "cmd_char": node == 2 ? "a" : "", "virtual_key": 0, "glyph": 0, "modifier_mask": 0]
            return SystemShortcuts.NodeRead(fields: fields, children: node < 2 ? [node + 1] : [], reasons: [])
        })
        precondition(reads == 3 && tree.reasons.isEmpty && tree.entries.count == 2)
        precondition(tree.entries[1]["path"] as? [String] == ["Edit", "Select All"])
        precondition(tree.entries[0]["enabled"] as? Bool == false); scanCases += 1
        let partial = SystemShortcuts.scan(root: 0, now: { 0 }, equal: ==, read: { _, _, _ in
            SystemShortcuts.NodeRead<Int>(fields: [:], children: [], reasons: ["children_unavailable"])
        })
        precondition(partial.reasons == ["children_unavailable"]); scanCases += 1
        var budgets: [Int] = []
        let fanout = SystemShortcuts.scan(root: 0, now: { 0 }, equal: ==, read: { node, budget, _ in
            budgets.append(budget)
            return SystemShortcuts.NodeRead(fields: ["role": "AXMenuItem", "name": "N\(node)"],
                children: node == 0 ? Array(1...5000) : [50000 + node * 2, 50001 + node * 2], reasons: [])
        })
        precondition(fanout.visited == 2000 && budgets[0] == 1999 && budgets.dropFirst().allSatisfy { $0 == 0 })
        precondition(fanout.reasons.contains("node_limit")); scanCases += 1
        let depth = SystemShortcuts.scan(root: 0, now: { 0 }, equal: ==, read: { node, _, _ in
            SystemShortcuts.NodeRead(fields: [:], children: [node + 1], reasons: [])
        })
        precondition(depth.visited == 13 && depth.reasons.contains("depth_limit")); scanCases += 1
        let cycle = SystemShortcuts.scan(root: 0, now: { 0 }, equal: ==, read: { _, _, _ in
            SystemShortcuts.NodeRead(fields: [:], children: [0], reasons: [])
        })
        precondition(cycle.visited == 1 && cycle.reasons.contains("repeated_element")); scanCases += 1
        var clock = 0.0
        let timed = SystemShortcuts.scan(root: 0, now: { clock }, equal: ==, read: { _, _, alive in
            clock = 4; precondition(!alive())
            return SystemShortcuts.NodeRead<Int>(fields: [:], children: [], reasons: [])
        })
        precondition(timed.visited == 1 && timed.reasons.contains("time_limit")); scanCases += 1

        SystemShortcuts.snapshots = []
        let app: [String: Any] = ["pid": 123, "started_at": 100.5]
        let layout: [String: Any] = ["layout_id": "fixture.US", "layout_sha256": "data1"]
        let first = try SystemShortcuts.store(application: app, layout: layout, observation: tree,
            principal: "owner", generation: "worker", now: 1, observedAt: 1000)
        let repeated = try SystemShortcuts.store(application: app, layout: layout, observation: tree,
            principal: "owner", generation: "worker", now: 1, observedAt: 1001)
        precondition(first.revision == repeated.revision && SystemShortcuts.snapshots.count == 1); cacheCases += 1
        let page = try SystemShortcuts.page(revision: first.revision, application: app, layout: layout,
            principal: "owner", generation: "worker", offset: 0, limit: 1, now: 2, cached: false)
        precondition(page["coverage"] as? String == "complete" && page["next_offset"] as? Int == 1)
        precondition(page["all_app_shortcuts_enumerated"] as? Bool == false && page["language"] as? String == "unknown"); cacheCases += 1
        var inactiveApp = app; inactiveApp["active"] = false; inactiveApp["hidden"] = true
        let next = try SystemShortcuts.page(revision: first.revision, application: inactiveApp, layout: layout,
            principal: "owner", generation: "worker", offset: 1, limit: 250, now: 2, cached: true)
        precondition(next["cached"] as? Bool == true && next["eof"] as? Bool == true && reads == 3); cacheCases += 1
        for change in ["owner", "worker", "layout", "birth", "executable", "missing", "expiry"] {
            var changedApp = app, changedLayout = layout
            if change == "birth" { changedApp["started_at"] = 101.0 }
            if change == "layout" { changedLayout["layout_sha256"] = "data2" }
            if change == "executable" { changedApp["executable"] = "/different/executable" }
            do {
                _ = try SystemShortcuts.page(revision: change == "missing" ? "absent" : first.revision,
                    application: changedApp, layout: changedLayout, principal: change == "owner" ? "foreign" : "owner",
                    generation: change == "worker" ? "worker2" : "worker", offset: 0, limit: 1,
                    now: change == "expiry" ? 16 : 2, cached: true)
                fatalError("Unbound snapshot accepted")
            } catch let error as SystemBridgeFailure {
                precondition(error.code == "keyboard_shortcuts_refresh_required" && !error.effectUnknown); cacheCases += 1
            }
        }
        var oldest = ""
        for index in 0..<5 {
            var anotherApp = app; anotherApp["pid"] = index + 100
            let saved = try SystemShortcuts.store(application: anotherApp, layout: layout, observation: partial,
                principal: "owner", generation: "worker", now: 20, observedAt: 1002)
            if index == 0 { oldest = saved.revision }
        }
        precondition(SystemShortcuts.snapshots.count == 4 && !SystemShortcuts.snapshots.contains { $0.revision == oldest }); cacheCases += 1
        let unavailable = try SystemShortcuts.store(application: app, layout: layout,
            observation: SystemShortcuts.Observation(entries: [], reasons: ["menu_bar_unavailable"], visited: 0),
            principal: "owner", generation: "worker", now: 20, observedAt: 1003)
        let absent = try SystemShortcuts.page(revision: unavailable.revision, application: app, layout: layout,
            principal: "owner", generation: "worker", offset: 0, limit: 1, now: 20, cached: false)
        precondition(absent["coverage"] as? String == "unavailable"); cacheCases += 1
        print(String(data: try JSONSerialization.data(withJSONObject: ["decoder_cases": decoderCases, "scan_cases": scanCases,
            "cache_cases": cacheCases, "native_ui_calls": 0, "event_posts": 0, "permission_requests": 0]), encoding: .utf8)!)
    }
}

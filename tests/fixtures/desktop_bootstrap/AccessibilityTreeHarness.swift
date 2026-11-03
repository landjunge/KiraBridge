import Foundation
import ApplicationServices

/// Synthetic production traversal/summary calls only. Never creates a real AX
/// element, inspects another application, asks for grants or posts UI effects.
@main
struct AccessibilityTreeHarness {
    @MainActor static func main() {
        let scenario = CommandLine.arguments[1]
        if scenario.hasPrefix("decode_") {
            var result: [String: Any] = ["native_ui_calls": 0, "permission_requests": 0, "input_posts": 0]
            do {
                switch scenario {
                case "decode_children_empty":
                    result["count"] = try SystemControl.treeChildren([] as CFArray).count
                case "decode_children_nil":
                    result["count"] = try SystemControl.treeChildren(nil).count
                case "decode_children_scalar":
                    result["count"] = try SystemControl.treeChildren("not children" as CFString).count
                case "decode_children_mixed":
                    result["count"] = try SystemControl.treeChildren(["not an AX element", 7] as CFArray).count
                case "decode_children_large":
                    result["count"] = try SystemControl.treeChildren(Array(repeating: 7, count: 5001) as CFArray).count
                case "decode_actions_empty":
                    result["count"] = try SystemControl.treeActionNames([] as CFArray).count
                case "decode_actions_valid":
                    result["count"] = try SystemControl.treeActionNames([kAXPressAction] as CFArray).count
                case "decode_actions_nil":
                    result["count"] = try SystemControl.treeActionNames(nil).count
                case "decode_actions_mixed":
                    result["count"] = try SystemControl.treeActionNames([kAXPressAction, 7] as CFArray).count
                case "decode_actions_large":
                    result["count"] = try SystemControl.treeActionNames(Array(repeating: kAXPressAction, count: 129) as CFArray).count
                case "decode_actions_long":
                    result["count"] = try SystemControl.treeActionNames([String(repeating: "x", count: 257)] as CFArray).count
                default: result["error"] = "fixture_scenario"
                }
            } catch let failure as SystemBridgeFailure { result["error"] = failure.code }
            catch { result["error"] = "unexpected" }
            let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
            print(String(data: data, encoding: .utf8)!)
            return
        }
        var graph: [Int: [Int]] = [:]
        for node in 0..<40 { graph[node] = [node * 3 + 1, node * 3 + 2, node * 3 + 3] }
        if scenario == "cycle" { graph = [0: [1, 1], 1: [0, 2], 2: [1]] }
        if scenario == "childlimit" { graph[0] = Array(repeating: 1, count: 5001) }
        if scenario == "heldlimit" {
            graph = [0: [1, 2, 3, 4]]
            for node in 1...4 { graph[node] = Array(repeating: 5, count: 5000) }
        }
        var clock = 0.0, reads = 0, valueReads = 0, revisionsMatch = true
        var depth = scenario == "depth" ? 1 : 32
        if scenario == "invaliddepth" { depth = 33 }
        let nodes = scenario == "nodes" ? 2 : 256
        let byteLimit = ["bytes", "rootbytes"].contains(scenario) ? 16384 : 262144
        let budget = ["time", "root_time"].contains(scenario) ? 50 : 1500
        func summary(_ node: Int) throws -> [String: Any] {
            try SystemControl.observedSummary(prepare: {}, read: { name in
                if name == kAXRoleAttribute { return "AXTextField" as CFString }
                if name == kAXSubroleAttribute {
                    return (scenario == "secure" && node == 1 ? "AXSecureTextField" : "") as CFString
                }
                if name == kAXTitleAttribute {
                    if scenario == "bytes" { return String(repeating: "🙂", count: 2048) as CFString }
                    return (node == 120 ? "Add people" : "fixture-\(node)") as CFString
                }
                if name == kAXValueAttribute { valueReads += 1; return "synthetic value" as CFString }
                return nil
            }, actionNames: { [kAXPressAction] })
        }
        var result: [String: Any]
        do {
            let snapshot = try SystemControl.observedTree(root: 0, maxDepth: depth, maxNodes: nodes,
                maxBytes: byteLimit, budgetMS: budget, now: { clock }) { node, _ in
                reads += 1
                if scenario == "owner" && node == 1 {
                    throw SystemControl.failure("macos_target_changed", "synthetic foreign owner")
                }
                if scenario == "changed" && node == 1 {
                    throw SystemControl.failure("macos_tree_changed", "synthetic changed node")
                }
                if scenario == "unavailable" && node == 1 {
                    throw SystemControl.failure("macos_accessibility_unavailable", "synthetic unavailable node")
                }
                if scenario == "time" { clock += 0.020 }
                if scenario == "root_time" { throw SystemControl.TreeReadLimit.deadline }
                var metadata = try summary(node)
                let individual = try summary(node)
                revisionsMatch = revisionsMatch && metadata["revision"] as? String == individual["revision"] as? String
                if scenario == "rootbytes" { metadata["title"] = String(repeating: "x", count: 50000) }
                return SystemControl.TreeObservation(node: node,
                    token: String(format: "%032x", node), metadata: metadata, children: graph[node] ?? [])
            }
            let data = try JSONSerialization.data(withJSONObject: snapshot.tree, options: [.sortedKeys])
            result = ["tree": snapshot.tree, "encoded_tree_bytes": data.count,
                      "legacy_internal_node_calls": graph.count]
        } catch let failure as SystemBridgeFailure { result = ["error": failure.code] }
        catch { result = ["error": String(describing: error)] }
        result["reads"] = reads
        result["value_reads"] = valueReads
        result["individual_revisions_match"] = revisionsMatch
        result["native_ui_calls"] = 0
        result["permission_requests"] = 0
        result["input_posts"] = 0
        let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
}

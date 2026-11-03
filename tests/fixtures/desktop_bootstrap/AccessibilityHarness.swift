import Foundation
import ApplicationServices

@main
struct AccessibilityHarness {
    @MainActor static func main() {
        let scenario = CommandLine.arguments[1]
        var result: [String: Any] = [:]
        if scenario == "catalog" || scenario == "focus" || scenario == "hidden" {
            var rows: [[String: Any]] = [["pid": 10, "active": true, "hidden": false],
                                        ["pid": 20, "active": false, "hidden": false]]
            let first = try! SystemControl.applicationPage(rows, args: ["limit": 1])
            if scenario == "focus" { rows[0]["active"] = false }
            if scenario == "hidden" { rows[0]["hidden"] = true }
            do {
                let second = try SystemControl.applicationPage(rows,
                    args: ["offset": 1, "limit": 1, "expected_revision": first["revision"]!])
                result = ["success": true, "page_count": (second["applications"] as! [[String: Any]]).count]
            } catch let failure as SystemBridgeFailure { result = ["error": failure.code] }
            catch { result = ["error": "unexpected"] }
        } else {
            var reads: [String: Int] = [:], prepared = false, premature = false
            do {
                let summary = try SystemControl.observedSummary(prepare: {
                    if scenario == "timeout_failure" {
                        throw SystemControl.failure("mock_timeout_failed", "private fixture")
                    }
                    prepared = true
                }, read: { name in
                    premature = premature || !prepared
                    reads[name, default: 0] += 1
                    if name == kAXRoleAttribute {
                        return (scenario == "missing_role" ? "" : "AXTextField") as CFString
                    }
                    if name == kAXSubroleAttribute {
                        return (scenario == "secure" ? "AXSecureTextField" : "") as CFString
                    }
                    if name == kAXTitleAttribute || name == kAXDescriptionAttribute {
                        let text = scenario == "flapping" && reads[name]! > 1
                            ? String(repeating: "x", count: 5000) : "short"
                        return text as CFString
                    }
                    if name == kAXValueAttribute { return "private mock text" as CFString }
                    return nil
                }, actionNames: { [] })
                result = ["summary": summary]
            } catch let failure as SystemBridgeFailure { result = ["error": failure.code] }
            catch { result = ["error": "unexpected"] }
            result["reads"] = reads
            result["premature"] = premature
            result["prepared"] = prepared
        }
        let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
}

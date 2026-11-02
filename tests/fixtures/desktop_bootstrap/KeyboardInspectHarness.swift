import Foundation
import ApplicationServices

@main
struct KeyboardInspectHarness {
    @MainActor static func main() throws {
        var checks = 0
        func field(_ scenario: String = "ordinary", selection: CFRange = CFRange(location: 1, length: 2),
                   value: String = "A😀e\u{301}") throws -> SystemKeyboard.Field {
            var prepared = false, valueRead = false
            do {
                let result = try SystemKeyboard.observeField(prepare: {
                    if scenario == "timeout" { throw SystemControl.failure("mock_timeout", "fixture") }
                    prepared = true
                }, read: { name in
                    precondition(prepared, "Attribute read before timeout")
                    switch name {
                    case kAXRoleAttribute:
                        return (scenario == "unknown" ? "AXButton" : "AXTextField") as CFString
                    case kAXSubroleAttribute:
                        if scenario == "missing_subrole" { return nil }
                        return (scenario == "secure" ? "AXSecureTextField" : "") as CFString
                    case kAXEnabledAttribute, kAXFocusedAttribute: return NSNumber(value: scenario != "unfocused")
                    case kAXNumberOfCharactersAttribute:
                        return NSNumber(value: scenario == "oversize" ? SystemKeyboard.maxValueBytes : value.utf16.count)
                    case kAXSelectedTextRangeAttribute:
                        var range = selection
                        return AXValueCreate(.cfRange, &range)
                    case kAXValueAttribute:
                        valueRead = true
                        return value as CFString
                    default: return nil
                    }
                })
                precondition(valueRead)
                return result
            } catch {
                if ["secure", "unknown", "missing_subrole", "timeout", "oversize", "unfocused"].contains(scenario) {
                    precondition(!valueRead, "Unsupported field value was read")
                }
                throw error
            }
        }
        let observed = try field()
        precondition(observed.value == "A😀e\u{301}" && observed.selection.location == 1 && observed.selection.length == 2)
        precondition(observed.metadata["value_utf16_units"] as? Int == 5)
        precondition(observed.metadata["value_utf8_bytes"] as? Int == 8)
        precondition(!observed.metadata.keys.contains("value"))
        checks += 1
        for scenario in ["secure", "unknown", "missing_subrole", "timeout", "oversize", "unfocused", "surrogate_split", "invalid_selection"] {
            do {
                _ = try field(scenario, selection: scenario == "surrogate_split" ? CFRange(location: 2, length: 0) : scenario == "invalid_selection" ? CFRange(location: 6, length: 0) : CFRange(location: 1, length: 2))
                fatalError("Expected refusal: \(scenario)")
            } catch let error as SystemBridgeFailure {
                precondition(error.code == (scenario == "timeout" ? "mock_timeout" : "keyboard_unsupported"))
                checks += 1
            }
        }
        let app: [String: Any] = ["pid": 123, "started_at": 100.5, "active": true]
        let layout: [String: Any] = ["input_source_id": "fixture.de", "layout_id": "fixture.de", "keyboard_type": 40]
        let first = try SystemKeyboard.revision(application: app, window: "window", element: "field", field: observed, layout: layout)
        for change in ["value", "selection", "layout", "focus", "window", "element"] {
            var otherApp = app, otherLayout = layout
            if change == "focus" { otherApp["active"] = false }
            if change == "layout" { otherLayout["layout_id"] = "fixture.us" }
            let otherField = try field(selection: change == "selection" ? CFRange(location: 0, length: 0) : observed.selection,
                                       value: change == "value" ? "B😀e\u{301}" : observed.value)
            let next = try SystemKeyboard.revision(application: otherApp, window: change == "window" ? "other" : "window",
                                                   element: change == "element" ? "other" : "field", field: otherField, layout: otherLayout)
            precondition(first != next, "Snapshot revision ignored \(change)")
            checks += 1
        }
        let result: [String: Any] = ["checks": checks, "field": observed.metadata,
                                   "native_ui_calls": 0, "event_posts": 0, "permission_requests": 0]
        print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
    }
}

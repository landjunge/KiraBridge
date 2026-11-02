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
        var keyChecks = 0
        precondition(SystemKeyboard.namedKeys.count == 27 && Set(SystemKeyboard.namedKeys.values).count == 27)
        precondition(SystemKeyboard.namedKeys["enter"] == 36 && SystemKeyboard.namedKeys["keypad_enter"] == 76)
        precondition(SystemKeyboard.namedKeys["backspace"] == 51 && SystemKeyboard.namedKeys["delete"] == 117)
        _ = try SystemKeyboard.namedKey(["named": "enter", "character": NSNull(), "key_code": NSNull()])
        keyChecks += 1
        let unsupportedKeys: [[String: Any]] = [["character": "a"], ["key_code": 0], ["named": "unknown"],
            ["named": "enter", "character": "a"], ["named": "enter", "key_code": 0]]
        for spec in unsupportedKeys {
            do { _ = try SystemKeyboard.namedKey(spec); fatalError("Unsupported key accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); keyChecks += 1 }
        }
        let binding: [String: Any] = ["pid": 123, "expected_started_at": 100.5, "target_token": "field",
            "helper_pid": 456, "worker_generation": "worker", "expected_revision": first]
        try SystemKeyboard.matchingBinding(binding, binding)
        for key in binding.keys {
            var stale = binding; stale[key] = "stale"
            do { try SystemKeyboard.matchingBinding(stale, binding); fatalError("Stale binding accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); keyChecks += 1 }
        }
        for scenario in ["permission", "modifier", "held_key"] {
            var posts = 0
            do {
                _ = try SystemKeyboard.postPair(validate: {
                    try SystemKeyboard.inputAllowed(postAccess: scenario != "permission",
                        flags: scenario == "modifier" ? .maskShift : [], keyHeld: scenario == "held_key")
                }, sameGeneration: { true }, post: { _ in posts += 1 })
                fatalError("Input conflict accepted")
            } catch let error as SystemBridgeFailure {
                precondition(!error.effectUnknown && posts == 0); keyChecks += 1
            }
        }
        var order: [String] = []
        let posted = try SystemKeyboard.postPair(validate: {
            order.append("validate")
            try SystemKeyboard.inputAllowed(postAccess: true, flags: [], keyHeld: false)
        }, sameGeneration: { order.append("generation"); return true }, post: { order.append($0 ? "down" : "up") })
        precondition(order == ["validate", "generation", "down", "generation", "up"])
        precondition(posted["post_calls_returned"] as? Int == 2 && posted["app_processing_confirmed"] as? Bool == false)
        keyChecks += 1
        for scenario in ["target_before", "generation_before", "generation_after", "down_error", "up_error", "cleanup_error"] {
            var posts: [String] = []
            do {
                _ = try SystemKeyboard.postPair(validate: {
                    if scenario == "target_before" { throw SystemControl.failure("changed", "fixture") }
                }, sameGeneration: {
                    scenario != "generation_before" && !(scenario == "generation_after" && !posts.isEmpty)
                }, post: { down in
                    posts.append(down ? "down" : "up")
                    if (scenario == "down_error" && down) || (scenario == "up_error" && posts.count == 2)
                        || scenario == "cleanup_error" { throw SystemControl.failure("post_lost", "fixture") }
                })
                fatalError("Expected key pair failure")
            } catch let error as SystemBridgeFailure {
                let before = ["target_before", "generation_before"].contains(scenario)
                precondition(error.effectUnknown == !before)
                if before { precondition(posts.isEmpty) }
                else if scenario == "generation_after" { precondition(posts == ["down"]) }
                else if scenario == "up_error" { precondition(posts == ["down", "up", "up"]) }
                else { precondition(posts == ["down", "up"]) }
                keyChecks += 1
            }
        }
        let result: [String: Any] = ["checks": checks, "field": observed.metadata,
                                   "key_checks": keyChecks, "named_key_codes": SystemKeyboard.namedKeys,
                                   "native_ui_calls": 0, "event_posts": 0, "permission_requests": 0]
        print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
    }
}

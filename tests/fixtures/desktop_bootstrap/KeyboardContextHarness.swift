import Foundation
import ApplicationServices

@main
struct KeyboardContextHarness {
    @MainActor static func main() throws {
        var checks = 0, valueReads = 0, attemptedPairs = 0
        func context(_ changes: [String: Any] = [:], text: Bool = false) throws -> SystemKeyboard.Context {
            var attributes: [String: Any] = [kAXRoleAttribute: text ? "AXTextArea" : "AXButton",
                kAXFocusedAttribute: true, kAXEnabledAttribute: true]
            if text {
                var selection = CFRange(location: 1, length: 2)
                attributes[kAXSubroleAttribute] = ""
                attributes[kAXNumberOfCharactersAttribute] = 5
                attributes[kAXSelectedTextRangeAttribute] = AXValueCreate(.cfRange, &selection)!
                attributes[kAXValueAttribute] = "A😀e\u{301}"
            }
            attributes.merge(changes) { _, new in new }
            var prepared = false
            return try SystemKeyboard.observeContext(prepare: { prepared = true }, read: { name in
                precondition(prepared)
                if name == kAXValueAttribute { valueReads += 1 }
                let value = attributes[name]
                return value is NSNull ? nil : value as CFTypeRef?
            })
        }
        func refuse(_ action: () throws -> Void) {
            do { try action(); fatalError("Unsafe context was accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); checks += 1 }
            catch { fatalError("Unexpected error: \(error)") }
        }
        let ordinary = try context()
        precondition(ordinary.field == nil && ordinary.metadata["text_supported"] as? Bool == false)
        precondition(ordinary.metadata["subrole"] is NSNull && ordinary.metadata["secure"] is NSNull)
        precondition(!ordinary.metadata.keys.contains("value_sha256") && valueReads == 0)
        checks += 1
        for role in ["AXOutline", "AXWebArea", "AXGroup", "AXStaticText", "AXCustomControl"] {
            let observed = try context([kAXRoleAttribute: role])
            precondition(observed.metadata["role"] as? String == role && observed.field == nil)
            let result = try SystemKeyboard.postPair(validate: {
                _ = try context([kAXRoleAttribute: role])
            }, sameGeneration: { true }, post: { _ in attemptedPairs += 1 })
            precondition(result["post_calls_returned"] as? Int == 2
                         && result["app_processing_confirmed"] as? Bool == false)
            checks += 1
        }
        precondition(valueReads == 0 && attemptedPairs == 10)
        let missingFocused = try context([kAXFocusedAttribute: NSNull()])
        precondition(missingFocused.metadata["focused"] is NSNull && missingFocused.field == nil)
        _ = try SystemKeyboard.postPair(validate: { _ = try context([kAXFocusedAttribute: NSNull()]) },
            sameGeneration: { true }, post: { _ in attemptedPairs += 1 })
        checks += 1
        let missingEnabled = try context([kAXEnabledAttribute: NSNull()])
        precondition(missingEnabled.metadata["enabled"] is NSNull)
        let specificSubrole = try context([kAXSubroleAttribute: "AXCloseButton"])
        precondition(specificSubrole.metadata["subrole"] as? String == "AXCloseButton")
        checks += 2
        for changes: [String: Any] in [
            [kAXRoleAttribute: "AXSecureTextField"], [kAXSubroleAttribute: "AXSecureTextField"],
            ["AXProtectedContent": true], [kAXFocusedAttribute: false],
            [kAXFocusedAttribute: "focused"], [kAXEnabledAttribute: false],
            [kAXRoleAttribute: NSNull()], [kAXRoleAttribute: ""], [kAXRoleAttribute: "AXbad role"],
            [kAXRoleAttribute: "AX" + String(repeating: "x", count: 127)],
            [kAXSubroleAttribute: 4], [kAXEnabledAttribute: "enabled"]
        ] { refuse { _ = try context(changes) } }
        precondition(valueReads == 0)
        refuse {
            _ = try SystemKeyboard.observeContext(prepare: {
                throw SystemControl.failure("fixture_timeout", "fixture")
            }, read: { _ in fatalError("AX read after timeout") })
        }
        let text = try context(text: true)
        let field = try SystemKeyboard.requireField(text.field)
        precondition(text.metadata["text_supported"] as? Bool == true
                     && text.metadata["secure"] as? Bool == false
                     && field.value == "A😀e\u{301}" && field.selection.length == 2)
        for (key, value) in field.metadata {
            let old = try SystemControl.hash(["v": value])
            let new = try SystemControl.hash(["v": text.metadata[key]!])
            precondition(old == new)
        }
        precondition(valueReads == 1)
        checks += 1
        for changes: [String: Any] in [
            [kAXRoleAttribute: "AXTextField", kAXSubroleAttribute: NSNull()],
            [kAXSubroleAttribute: "AXUnclassifiedText"],
            [kAXNumberOfCharactersAttribute: NSNull()], [kAXSelectedTextRangeAttribute: NSNull()],
            [kAXNumberOfCharactersAttribute: SystemKeyboard.maxValueBytes],
            [kAXFocusedAttribute: NSNull()]
        ] {
            let unsupported = try context(changes, text: true)
            precondition(unsupported.field == nil && unsupported.metadata["text_supported"] as? Bool == false)
            refuse { _ = try SystemKeyboard.requireField(unsupported.field) }
        }
        precondition(valueReads == 1, "Unclassified/unbounded text was read")
        for changes: [String: Any] in [[kAXSubroleAttribute: "AXSecureTextField"], ["AXProtectedContent": true]] {
            refuse { _ = try context(changes, text: true) }
        }
        precondition(valueReads == 1)
        var roleReads = 0
        refuse {
            _ = try SystemKeyboard.observeContext(prepare: {}, read: { name in
                switch name {
                case kAXRoleAttribute: roleReads += 1; return "AXTextArea" as CFString
                case kAXSubroleAttribute: return (roleReads > 1 ? "AXSecureTextField" : "") as CFString
                case kAXFocusedAttribute, kAXEnabledAttribute: return kCFBooleanTrue
                default: return nil
                }
            })
        }
        let app: [String: Any] = ["pid": 123, "started_at": 10.5, "active": true]
        let layout: [String: Any] = ["layout_id": "fixture", "keyboard_type": 40]
        let baseline = try SystemKeyboard.revision(application: app, window: "window", element: "focus",
                                                   metadata: ordinary.metadata, layout: layout)
        for change in ["role", "subrole", "enabled", "layout", "window", "element", "app"] {
            var other = ordinary.metadata, otherApp = app, otherLayout = layout
            if change == "role" { other["role"] = "AXOutline" }
            if change == "subrole" { other["subrole"] = "AXCloseButton" }
            if change == "enabled" { other["enabled"] = NSNull() }
            if change == "layout" { otherLayout["layout_id"] = "other" }
            if change == "app" { otherApp["started_at"] = 11.5 }
            let revision = try SystemKeyboard.revision(application: otherApp,
                window: change == "window" ? "other" : "window", element: change == "element" ? "other" : "focus",
                metadata: other, layout: otherLayout)
            precondition(revision != baseline, "Generic revision ignored \(change)")
            checks += 1
        }
        refuse {
            _ = try SystemKeyboard.postPair(validate: { _ = try SystemKeyboard.requireField(ordinary.field) },
                sameGeneration: { true }, post: { _ in fatalError("Text attempt without exact field") })
        }
        // Delta: Apple's optional subrole is accepted only for an otherwise exact text area.
        let nilArea = try context([kAXSubroleAttribute: NSNull()], text: true)
        let nilAreaField = try SystemKeyboard.requireField(nilArea.field)
        precondition(nilArea.metadata["subrole"] is NSNull && nilArea.metadata["text_supported"] as? Bool == true)
        precondition(nilAreaField.value.utf8.elementsEqual(field.value.utf8) && valueReads == 2)
        checks += 1
        try SystemKeyboard.textFieldAllowed(nilAreaField, text: "\tline\n")
        checks += 1
        for status: AXError in [.success, .attributeUnsupported, .noValue] {
            let absent = try SystemKeyboard.optionalSubrole(status: status, value: nil)
            precondition(absent == nil)
            checks += 1
        }
        let explicit = try SystemKeyboard.optionalSubrole(status: .success, value: "" as CFString)
        precondition(explicit as? String == "")
        checks += 1
        for status: AXError in [.cannotComplete, .invalidUIElement, .apiDisabled, .notImplemented, .failure] {
            refuse {
                _ = try SystemKeyboard.observeContext(prepare: {
                    _ = try SystemKeyboard.optionalSubrole(status: status, value: nil)
                }, read: { _ in fatalError("AX read after failed subrole observation") })
            }
        }
        refuse { _ = try SystemKeyboard.optionalSubrole(status: .success, value: kCFBooleanTrue) }
        let incompleteNilArea = try context([kAXSubroleAttribute: NSNull(), kAXNumberOfCharactersAttribute: NSNull()], text: true)
        refuse { _ = try SystemKeyboard.requireField(incompleteNilArea.field) }
        precondition(valueReads == 2)
        let nilRevision = try SystemKeyboard.revision(application: app, window: "window", element: "focus",
                                                      metadata: nilArea.metadata, layout: layout)
        let emptyRevision = try SystemKeyboard.revision(application: app, window: "window", element: "focus",
                                                        metadata: text.metadata, layout: layout)
        precondition(nilRevision != emptyRevision, "Nil subrole was normalized into an invented empty string")
        checks += 1
        var notesChecks = 0
        func notesField(_ scenario: String = "allowed") throws -> SystemKeyboard.Field {
            var valueRead = false
            do {
                let result = try SystemKeyboard.observeField(prepare: {}, read: { name in
                    switch name {
                    case kAXRoleAttribute: return (scenario == "unknown_role" ? "AXButton" : "AXTextArea") as CFString
                    case kAXSubroleAttribute: return scenario == "secure" ? "AXSecureTextField" as CFString : nil
                    case kAXEnabledAttribute: return scenario == "disabled" ? NSNumber(value: false) : nil
                    case kAXFocusedAttribute: return NSNumber(value: scenario != "unfocused")
                    case kAXNumberOfCharactersAttribute: return NSNumber(value: scenario == "nonempty_no_value" ? 1 : 0)
                    case kAXSelectedTextRangeAttribute:
                        var range = CFRange(location: scenario == "nonempty_no_value" ? 1 : 0, length: 0)
                        return AXValueCreate(.cfRange, &range)
                    case kAXValueAttribute:
                        valueRead = true
                        if ["empty_no_value", "nonempty_no_value", "empty_other_error", "empty_without_proof", "wrong_value_type"].contains(scenario) {
                            return scenario == "wrong_value_type" ? NSNumber(value: 0) : nil
                        }
                        return "" as CFString
                    default: return nil
                    }
                }, notesEvidence: {
                    if scenario == "evidence_failed" { throw SystemControl.failure("mock_notes_error", "fixture") }
                    var names = [kAXRoleAttribute, kAXFocusedAttribute, kAXIdentifierAttribute,
                                 kAXValueAttribute, kAXSelectedTextAttribute, kAXSelectedTextRangeAttribute,
                                 kAXNumberOfCharactersAttribute]
                    if scenario == "listed_subrole" { names.append(kAXSubroleAttribute) }
                    if scenario == "listed_enabled" { names.append(kAXEnabledAttribute) }
                    if scenario == "duplicate_names" { names.append(kAXRoleAttribute) }
                    if scenario == "too_many_names" { names = (0...256).map { "AXField\($0)" } }
                    if scenario == "invalid_name" { names.append("") }
                    return SystemKeyboard.NotesBodyEvidence(
                        bundleID: scenario == "fake_bundle" ? "com.example.Notes" : "com.apple.Notes",
                        bundlePath: scenario == "fake_path" ? "/Applications/Notes.app" : "/System/Applications/Notes.app",
                        executablePath: scenario == "fake_executable" ? "/tmp/Notes" : "/System/Applications/Notes.app/Contents/MacOS/Notes",
                        identifier: scenario == "wrong_identifier" ? "Other text view" : "Note Body Text View",
                        attributeNames: scenario == "names_failed" ? nil : names,
                        subroleUnsupported: scenario != "subrole_error",
                        enabledUnsupported: scenario != "enabled_error",
                        selectedTextWritable: !["locked", "writability_error"].contains(scenario))
                }, notesEmptyValue: scenario == "empty_without_proof" ? nil : {
                    precondition(valueRead, "Empty-value proof must follow the guarded value read")
                    return scenario != "empty_other_error"
                })
                precondition(valueRead)
                return result
            } catch {
                if !["nonempty_no_value", "empty_other_error", "empty_without_proof", "wrong_value_type"].contains(scenario) {
                    precondition(!valueRead, "Unverified Notes field value was read")
                }
                throw error
            }
        }
        let notesBody = try notesField()
        precondition(notesBody.metadata["subrole"] is NSNull && notesBody.metadata["enabled"] is NSNull)
        precondition(notesBody.metadata["classification_source"] as? String == "system_notes_writable_body")
        precondition(notesBody.metadata["selected_text_settable"] as? Bool == true)
        notesChecks += 1
        try SystemKeyboard.textFieldAllowed(notesBody, text: "\n\n\t")
        notesChecks += 1
        let emptyNotesBody = try notesField("empty_no_value")
        precondition(emptyNotesBody.value.isEmpty && emptyNotesBody.selection.location == 0)
        precondition(emptyNotesBody.metadata["value_source"] as? String == "system_notes_empty_no_value")
        precondition(emptyNotesBody.metadata["value_utf8_bytes"] as? Int == 0)
        notesChecks += 1
        for scenario in ["fake_bundle", "fake_path", "fake_executable", "wrong_identifier",
                         "listed_subrole", "listed_enabled", "names_failed", "too_many_names",
                         "duplicate_names", "invalid_name", "subrole_error", "enabled_error",
                         "locked", "writability_error", "secure", "disabled", "unknown_role",
                         "unfocused", "evidence_failed", "nonempty_no_value", "empty_other_error",
                         "empty_without_proof", "wrong_value_type"] {
            do { _ = try notesField(scenario); fatalError("Unsafe Notes fallback accepted: \(scenario)") }
            catch let error as SystemBridgeFailure {
                precondition(!error.effectUnknown)
                notesChecks += 1
            }
        }
        // The compatibility must be wired through the generic key/context path,
        // not only the isolated text observer. Missing attributes stay missing.
        for valid in [true, false] {
            var reads = 0
            let result = try SystemKeyboard.observeContext(prepare: {}, read: { name in
                switch name {
                case kAXRoleAttribute: return "AXTextArea" as CFString
                case kAXFocusedAttribute: return kCFBooleanTrue
                case kAXNumberOfCharactersAttribute: return NSNumber(value: 0)
                case kAXSelectedTextRangeAttribute:
                    var range = CFRange(location: 0, length: 0)
                    return AXValueCreate(.cfRange, &range)
                case kAXValueAttribute: reads += 1; return nil
                default: return nil
                }
            }, notesEvidence: {
                SystemKeyboard.NotesBodyEvidence(
                    bundleID: valid ? "com.apple.Notes" : "com.example.Notes",
                    bundlePath: "/System/Applications/Notes.app",
                    executablePath: "/System/Applications/Notes.app/Contents/MacOS/Notes",
                    identifier: "Note Body Text View",
                    attributeNames: [kAXRoleAttribute, kAXFocusedAttribute, kAXValueAttribute],
                    subroleUnsupported: true, enabledUnsupported: true, selectedTextWritable: true)
            }, notesEmptyValue: { true })
            precondition(result.metadata["text_supported"] as? Bool == valid)
            precondition(result.metadata["enabled"] is NSNull && result.metadata["subrole"] is NSNull)
            precondition(reads == (valid ? 1 : 0))
            if valid {
                let field = try SystemKeyboard.requireField(result.field)
                precondition(field.value.isEmpty)
            }
            else { precondition(result.field == nil) }
            notesChecks += 1
        }
        var repeatChecks = 0
        let defaultRepeat = try SystemKeyboard.repeatCount([:])
        let maxRepeat = try SystemKeyboard.repeatCount(["repeat": 20])
        precondition(defaultRepeat == 1 && maxRepeat == 20)
        repeatChecks += 1
        for invalid: Any in [true, 0, 21, 1.5, 1.0, NSNull(), "2"] {
            do {
                _ = try SystemKeyboard.repeatCount(["repeat": invalid])
                fatalError("Invalid keyboard repeat accepted")
            } catch let error as SystemBridgeFailure {
                precondition(error.code == "invalid_arguments" && !error.effectUnknown)
                repeatChecks += 1
            }
        }
        var pairOrder: [Int] = [], repeatPosts = 0
        let repeated = try SystemKeyboard.repeatedPairs(20) { index in
            pairOrder.append(index)
            return try SystemKeyboard.postPair(validate: {}, sameGeneration: { true }, post: { _ in repeatPosts += 1 })
        }
        precondition(pairOrder == Array(0..<20) && repeatPosts == 40
                     && repeated["post_calls_returned"] as? Int == 40
                     && repeated["completed_repeat"] as? Int == 20
                     && repeated["app_processing_confirmed"] as? Bool == false)
        repeatChecks += 1
        for failAt in [0, 1] {
            var pairs = 0, posts = 0
            do {
                _ = try SystemKeyboard.repeatedPairs(3) { index in
                    pairs += 1
                    return try SystemKeyboard.postPair(validate: {
                        if index == failAt { throw SystemControl.failure("macos_element_changed", "fixture") }
                    }, sameGeneration: { true }, post: { _ in posts += 1 })
                }
                fatalError("Changed repetition target accepted")
            } catch let error as SystemBridgeFailure {
                precondition(error.effectUnknown == (failAt > 0))
                precondition(pairs == failAt + 1 && posts == failAt * 2)
                repeatChecks += 1
            }
        }
        var uncertainPosts = 0
        do {
            _ = try SystemKeyboard.repeatedPairs(3) { index in
                try SystemKeyboard.postPair(validate: {}, sameGeneration: { true }, post: { down in
                    uncertainPosts += 1
                    if index == 1 && down { throw SystemControl.failure("lost", "fixture") }
                })
            }
            fatalError("Uncertain repetition was replayed")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && uncertainPosts == 4)
            repeatChecks += 1
        }
        let output: [String: Any] = ["checks": checks, "value_reads": valueReads,
            "repeat_checks": repeatChecks,
            "simulated_key_posts": attemptedPairs, "notes_checks": notesChecks, "native_ui_calls": 0, "event_posts": 0, "permission_requests": 0]
        print(String(data: try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]), encoding: .utf8)!)
    }
}

import Foundation
import ApplicationServices

/// Exercises the real production scalar formatter and batch planner with local
/// CF values. No AX element or application is created or inspected.
@main
struct AccessibilityBatchHarness {
    @MainActor static func main() {
        let scenario = CommandLine.arguments[1]
        var result: [String: Any] = [:]
        var scalarReads = 0, scalarActions = 0, scalarValueReads = 0
        var batchCalls = 0, batchActions = 0, fallbackCalls = 0, prepares = 0
        var requested: [[String]] = [], currentTitle = "synthetic title", fallbackSecure = false
        var optionalRecovered = false
        let optionalFailure = ["optional_both_failure", "optional_failure_fallback",
            "secure_optional_failure", "optional_failure_recovery"].contains(scenario)
        let isSecure = scenario.hasPrefix("secure")
        func errorValue(_ error: AXError) -> CFTypeRef {
            var value = error
            return AXValueCreate(.axError, &value)!
        }
        func fixtureValue(_ name: String) -> CFTypeRef {
            if name == kAXRoleAttribute {
                if scenario == "role_failure" { return errorValue(.failure) }
                if scenario == "missing_role" { return kCFNull }
                if scenario == "bad_role_type" { return NSNumber(value: 7) }
                if scenario == "wrapped_success" { return errorValue(.success) }
                return (scenario == "secure_role" ? "AXSecureTextField" : "AXTextField") as CFString
            }
            if name == kAXSubroleAttribute {
                if scenario == "classification_failure" { return errorValue(.failure) }
                if scenario == "bad_subrole_type" { return NSNumber(value: 8) }
                if scenario == "classification_error" { return errorValue(.cannotComplete) }
                return (isSecure || fallbackSecure ? "AXSecureTextField" : "") as CFString
            }
            if name == kAXTitleAttribute {
                if scenario == "title_failure" { return errorValue(.failure) }
                if scenario == "metadata_error" { return errorValue(.cannotComplete) }
                if scenario == "slot_not_implemented" { return errorValue(.notImplemented) }
                if scenario == "missing_optional" { return kCFNull }
                return currentTitle as CFString
            }
            if name == kAXDescriptionAttribute {
                if scenario == "description_cannot_complete" { return errorValue(.cannotComplete) }
                if scenario == "description_not_implemented" { return errorValue(.notImplemented) }
                if optionalFailure || scenario == "optional_description_failure" {
                    return optionalRecovered ? "" as CFString : errorValue(.failure)
                }
                return scenario == "missing_optional" ? errorValue(.noValue) : "synthetic description" as CFString
            }
            if name == kAXIdentifierAttribute {
                if scenario == "identifier_invalid_element" { return errorValue(.invalidUIElement) }
                if optionalFailure || scenario == "optional_identifier_failure" {
                    return optionalRecovered ? "" as CFString : errorValue(.failure)
                }
                return "synthetic-id" as CFString
            }
            if name == kAXValueAttribute {
                if scenario == "value_failure" { return errorValue(.failure) }
                return scenario == "numeric_value" ? NSNumber(value: 42) : "synthetic value" as CFString
            }
            if name == kAXEnabledAttribute {
                return scenario == "missing_optional" ? errorValue(.attributeUnsupported) : kCFBooleanTrue
            }
            if [kAXFocusedAttribute, kAXSelectedAttribute, kAXExpandedAttribute, kAXMinimizedAttribute].contains(name) {
                return kCFBooleanFalse
            }
            if name == kAXPositionAttribute {
                var point = CGPoint(x: 12, y: 34)
                return AXValueCreate(.cgPoint, &point)!
            }
            if name == kAXSizeAttribute {
                var size = CGSize(width: 100, height: 50)
                return AXValueCreate(.cgSize, &size)!
            }
            return kCFNull
        }
        func scalarSummary() throws -> [String: Any] {
            var failure: Error?
            var unavailable: Set<String> = []
            do {
                let summary = try SystemControl.observedSummary(prepare: {}, read: { name in
                    guard failure == nil else { return nil }
                    scalarReads += 1
                    if name == kAXValueAttribute { scalarValueReads += 1 }
                    let value = fixtureValue(name)
                    if CFGetTypeID(value) == CFNullGetTypeID() { return nil }
                    if CFGetTypeID(value) == AXValueGetTypeID() {
                        let wrapped = unsafeBitCast(value, to: AXValue.self)
                        if AXValueGetType(wrapped) == .axError {
                            var error = AXError.failure
                            _ = AXValueGetValue(wrapped, .axError, &error)
                            do {
                                return try SystemControl.treeAttributeValue(name, status: error, value: nil,
                                    unavailableMetadata: { unavailable.insert($0) })
                            } catch { failure = error; return nil }
                        }
                    }
                    if [kAXRoleAttribute, kAXSubroleAttribute].contains(name), !(value is String) {
                        failure = SystemControl.failure("macos_accessibility_unavailable", "synthetic classification error")
                        return nil
                    }
                    return value
                }, actionNames: {
                    scalarActions += 1
                    return scenario == "actions_not_implemented" ? nil : [kAXPressAction]
                }, unavailableMetadata: { unavailable.sorted() })
                if let error = failure { throw error }
                return summary
            } catch { throw failure ?? error }
        }
        var baseline: [String: Any]?
        do { baseline = try scalarSummary() }
        catch let failure as SystemBridgeFailure { result["baseline_error"] = failure.code }
        catch { result["baseline_error"] = "unexpected" }
        let baselineReads = scalarReads, baselineActions = scalarActions
        scalarReads = 0; scalarActions = 0; scalarValueReads = 0
        func batched() throws -> [String: Any] {
            try SystemControl.observedBatchedTreeSummary(prepare: {
                prepares += 1
                if scenario == "prepare_failure" {
                    throw SystemControl.failure("mock_prepare_failed", "synthetic prepare failure")
                }
            }, copy: { names in
                batchCalls += 1; requested.append(names)
                if scenario == "copy_deadline" { throw SystemControl.TreeReadLimit.deadline }
                if scenario == "whole_not_implemented_first" && batchCalls == 1
                    || scenario == "whole_not_implemented_second" && batchCalls == 2 {
                    return (.notImplemented, nil)
                }
                if scenario == "secure_fallback" && batchCalls == 2 { return (.notImplemented, nil) }
                if scenario == "optional_failure_fallback" && batchCalls == 2 { return (.notImplemented, nil) }
                if scenario == "fallback_new_secure" && batchCalls == 2 { return (.notImplemented, nil) }
                if scenario == "whole_failure" { return (.failure, nil) }
                if scenario == "whole_metadata_failure" && batchCalls == 2 { return (.failure, nil) }
                if scenario == "whole_error" { return (.cannotComplete, nil) }
                if scenario == "whole_unsupported" { return (.attributeUnsupported, nil) }
                if scenario == "success_nil" { return (.success, nil) }
                if scenario == "wrong_container" {
                    return (.success, unsafeBitCast("not an array" as CFString, to: CFArray.self))
                }
                var values = names.map { fixtureValue($0) }
                if scenario == "wrong_count" { values.removeLast() }
                return (.success, values as CFArray)
            }, actionNames: {
                batchActions += 1
                if scenario == "actions_error" {
                    throw SystemControl.failure("macos_accessibility_unavailable", "synthetic action error")
                }
                if scenario == "actions_not_implemented" { return nil }
                return [kAXPressAction]
            }, individual: {
                fallbackCalls += 1
                if scenario == "fallback_new_secure" { fallbackSecure = true }
                return try scalarSummary()
            })
        }
        do {
            let candidate = try batched()
            result["summary"] = candidate
            result["matches_individual_summary"] = baseline.map { NSDictionary(dictionary: $0).isEqual(to: candidate) } ?? false
            if scenario == "fresh_calls" {
                currentTitle = "new synthetic title"
                let second = try batched()
                result["second_summary"] = second
                result["fresh_revision_changed"] = candidate["revision"] as? String != second["revision"] as? String
            }
            if scenario == "optional_failure_recovery" {
                optionalRecovered = true
                let second = try batched()
                result["second_summary"] = second
                result["recovery_revision_changed"] = candidate["revision"] as? String != second["revision"] as? String
                result["recovery_matches_scalar"] = NSDictionary(dictionary: try scalarSummary()).isEqual(to: second)
            }
        } catch let failure as SystemBridgeFailure { result["error"] = failure.code }
        catch SystemControl.TreeReadLimit.deadline { result["error"] = "deadline" }
        catch { result["error"] = "unexpected" }
        result["baseline_attribute_calls"] = baselineReads
        result["baseline_action_calls"] = baselineActions
        result["batch_copy_calls"] = batchCalls
        result["batch_action_calls"] = batchActions
        result["fallback_calls"] = fallbackCalls
        result["fallback_attribute_calls"] = scalarReads
        result["fallback_action_calls"] = scalarActions
        result["fallback_value_reads"] = scalarValueReads
        result["batch_requested_attributes"] = requested
        result["prepare_calls"] = prepares
        result["native_ui_calls"] = 0
        result["permission_requests"] = 0
        result["input_posts"] = 0
        let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
}

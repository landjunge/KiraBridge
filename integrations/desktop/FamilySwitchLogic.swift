// Pure family-switch ABI logic (Foundation only), shared by main.swift and the
// targeted test. Kept out of the Cocoa/WebKit host so the ABI mapping and the
// JSON-string escaping are testable in isolation.
import Foundation

let familySwitchCatalogIDs: Set<String> = [
    "kirabridge", "threaddesk", "4allpass", "tollgate", "agent-authority",
]

func familySwitchAdmits(sameView: Bool, mainFrame: Bool, scheme: String, host: String,
                        port: Int, body: Any) -> Bool {
    guard sameView, mainFrame, scheme == "http", host == "127.0.0.1", port == 8766,
          let value = body as? [String: Any], Set(value.keys) == Set(["id", "appId"]),
          let id = value["id"] as? String, !id.isEmpty, id.utf8.count <= 128,
          let app = value["appId"] as? String else { return false }
    return familySwitchCatalogIDs.contains(app)
}

/// Strict ABI shape for the family-switch result. `JSONDecoder` rejects a
/// numeric "success" (only a real JSON `true`/`false` decodes) and an invalid
/// bounds/window type, so a malformed reply never masquerades as a clean switch.
struct FamilySwitchResult: Decodable {
    let success: Bool
    let activeProduct: String?
    let visibleFamilyWindows: Int?
    let executionOutcomeUnknown: Bool?
    let actualOuterBounds: OuterBounds?
    let error: FamilySwitchError?
    let hasError: Bool
    struct OuterBounds: Decodable {
        let x: Double
        let y: Double
        let width: Double
        let height: Double
    }
    struct FamilySwitchError: Decodable {
        let code: String
        let message: String
    }
    enum CodingKeys: String, CodingKey {
        case success
        case activeProduct = "active_product"
        case visibleFamilyWindows = "visible_family_windows"
        case executionOutcomeUnknown = "execution_outcome_unknown"
        case actualOuterBounds = "actual_outer_bounds"
        case error
    }
    init(from decoder: Decoder) throws {
        let value = try decoder.container(keyedBy: CodingKeys.self)
        success = try value.decode(Bool.self, forKey: .success)
        activeProduct = try value.decodeIfPresent(String.self, forKey: .activeProduct)
        visibleFamilyWindows = try value.decodeIfPresent(Int.self, forKey: .visibleFamilyWindows)
        executionOutcomeUnknown = value.contains(.executionOutcomeUnknown)
            ? try value.decode(Bool.self, forKey: .executionOutcomeUnknown) : nil
        actualOuterBounds = try value.decodeIfPresent(OuterBounds.self, forKey: .actualOuterBounds)
        hasError = value.contains(.error)
        error = try value.decodeIfPresent(FamilySwitchError.self, forKey: .error)
    }
}

/// Map a family-switch CLI result to one of focused/failed/uncertain. A clean
/// success requires exit 0, a real JSON `true`, the exact target, no error or
/// unknown field, finite positive width/height and exactly one visible family
/// window; anything else is a confirmed failure or an unverifiable effect.
func familySwitchOutcome(status: Int32, data: Data, appId: String) -> String {
    guard familySwitchCatalogIDs.contains(appId),
          let result = try? JSONDecoder().decode(FamilySwitchResult.self, from: data) else {
        return "uncertain"
    }
    if status != 0 {
        guard result.success == false, let error = result.error,
              !error.code.isEmpty, !error.message.isEmpty,
              result.executionOutcomeUnknown == false else {
            return "uncertain"
        }
        return "failed"
    }
    guard result.success == true else {
        return "uncertain"
    }
    guard result.activeProduct == appId,
          !result.hasError,
          result.executionOutcomeUnknown != true,
          let bounds = result.actualOuterBounds,
          bounds.x.isFinite, bounds.y.isFinite, bounds.width.isFinite, bounds.height.isFinite,
          bounds.width > 0, bounds.height > 0,
          result.visibleFamilyWindows == 1 else {
        return "uncertain"
    }
    return "focused"
}

/// Encode a Swift string as a JSON string literal. Array-wrapping avoids a
/// top-level scalar, which would make `JSONSerialization` raise an ObjC
/// exception that Swift's `try?` cannot catch.
func familySwitchJsonString(_ value: String) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: [value]),
          let encoded = String(data: data, encoding: .utf8) else {
        return "\"\""
    }
    return String(encoded.dropFirst().dropLast())
}

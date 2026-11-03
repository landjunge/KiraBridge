import Foundation
import ApplicationServices

@main
struct ProfileContextHarness {
    @MainActor static func main() throws {
        var checks = 0
        let app: [String: Any] = ["pid": 123, "started_at": 100.5, "bundle_id": "example.Fixture",
            "app_path": "/private/Fixture.app", "executable": "/private/Fixture.app/bin", "active": true]
        let layout: [String: Any] = ["layout_id": "fixture.US", "keyboard_type": 40]
        let field: [String: Any] = ["role": "AXTextArea"]
        let constraints: [String: Any] = ["bundle_id": "example.Fixture", "layout_id": "fixture.US",
                                         "keyboard_type": 40, "field_roles": ["AXTextArea"]]
        let context: [String: Any] = ["id": "fixture_profile", "revision": String(repeating: "a", count: 64),
                                     "action": "editor.select_all", "app": constraints]
        let expected: [String: Any] = context.filter { $0.key != "app" }
        let binding = try SystemKeyboard.profileContext(context, application: app, layout: layout, field: field)
        let expectedHash = try SystemControl.hash(expected), bindingHash = try SystemControl.hash(binding)
        precondition(bindingHash == expectedHash); checks += 1
        var allowed = context, allowedApp = constraints
        allowedApp["field_roles"] = ["AXTextField", "AXTextArea"]; allowed["app"] = allowedApp
        _ = try SystemKeyboard.profileContext(allowed, application: app, layout: layout, field: field); checks += 1
        var nullable = context
        nullable["app"] = ["bundle_id": "example.Fixture", "version": NSNull(), "layout_id": NSNull()]
        _ = try SystemKeyboard.profileContext(nullable, application: app, layout: [:], field: [:]); checks += 1
        let nativeLayout = SystemKeyboard.Layout(metadata: layout, translate: { _, _ in nil })
        let physical = try SystemKeyboard.resolve(["key_code": 6], modifiers: ["command"], layout: nativeLayout)
        var posts: [Bool] = []
        let sent = try SystemKeyboard.postPair(validate: {
            _ = try SystemKeyboard.profileContext(context, application: app, layout: layout, field: field)
        }, sameGeneration: { true }, post: { posts.append($0) })
        precondition(physical.code == 6 && physical.flags == .maskCommand && posts == [true, false])
        precondition(sent["app_processing_confirmed"] as? Bool == false); checks += 1
        do {
            _ = try SystemKeyboard.key(["target": [:], "key": ["named": "enter"], "profile_context": context])
            fatalError("Legacy operation ignored profile context")
        } catch let error as SystemBridgeFailure { precondition(error.code == "keyboard_profile_context_invalid"); checks += 1 }
        func refuses(_ candidate: Any?, code: String, application: [String: Any]? = nil,
                     observedLayout: [String: Any]? = nil, observedField: [String: Any]? = nil) throws {
            var events = 0
            do {
                _ = try SystemKeyboard.postPair(validate: {
                    _ = try SystemKeyboard.profileContext(candidate, application: application ?? app,
                        layout: observedLayout ?? layout, field: observedField ?? field)
                }, sameGeneration: { true }, post: { _ in events += 1 })
                fatalError("Unbound profile context accepted")
            } catch let error as SystemBridgeFailure {
                precondition(error.code == code && !error.effectUnknown && events == 0); checks += 1
            }
        }
        var malformed: [Any?] = [nil]
        var extra = context; extra["trusted"] = true; malformed.append(extra)
        var badID = context; badID["id"] = "UPPER"; malformed.append(badID)
        var badRevision = context; badRevision["revision"] = "a"; malformed.append(badRevision)
        var badAction = context; badAction["action"] = "../run"; malformed.append(badAction)
        for (key, value) in [("unknown", true as Any), ("bundle_id", "not-a-bundle"), ("keyboard_type", true),
                             ("keyboard_type", -1), ("field_roles", ["AXTextArea", "AXTextArea"]),
                             ("field_roles", [] as [String]), ("version", "1/2")] {
            var candidate = context, wrongApp = constraints
            wrongApp[key] = value; candidate["app"] = wrongApp; malformed.append(candidate)
        }
        for candidate in malformed { try refuses(candidate, code: "keyboard_profile_context_invalid") }
        for (key, value) in [("version", "1.0"), ("build", "42"), ("signing_team_id", "ABCDEFGHIJ"), ("language", "de")] {
            var candidate = context, required = constraints
            required[key] = value; candidate["app"] = required
            try refuses(candidate, code: "keyboard_profile_context_unavailable")
        }
        var missingBundle = app; missingBundle.removeValue(forKey: "bundle_id")
        try refuses(context, code: "keyboard_profile_context_unavailable", application: missingBundle)
        try refuses(context, code: "keyboard_profile_context_unavailable", observedLayout: ["keyboard_type": 40])
        try refuses(context, code: "keyboard_profile_context_unavailable", observedLayout: ["layout_id": "fixture.US"])
        try refuses(context, code: "keyboard_profile_context_unavailable", observedField: [:])
        var otherApp = app; otherApp["bundle_id"] = "example.Other"
        try refuses(context, code: "keyboard_profile_context_mismatch", application: otherApp)
        try refuses(context, code: "keyboard_profile_context_mismatch", observedLayout: ["layout_id": "fixture.DE", "keyboard_type": 40])
        try refuses(context, code: "keyboard_profile_context_mismatch", observedLayout: ["layout_id": "fixture.US", "keyboard_type": 41])
        try refuses(context, code: "keyboard_profile_context_mismatch", observedField: ["role": "AXTextField"])
        let identity = try SystemShortcuts.stableAppIdentity(app)
        var focusChanged = app; focusChanged["active"] = false; focusChanged["hidden"] = true
        let focusIdentity = try SystemShortcuts.stableAppIdentity(focusChanged)
        precondition(identity == focusIdentity); checks += 1
        var execChanged = app; execChanged["executable"] = "/other/bin"
        let execIdentity = try SystemShortcuts.stableAppIdentity(execChanged)
        precondition(identity != execIdentity); checks += 1
        print(String(data: try JSONSerialization.data(withJSONObject: ["checks": checks, "binding": binding,
            "native_ui_calls": 0, "event_posts": 0, "profile_file_reads": 0]), encoding: .utf8)!)
    }
}

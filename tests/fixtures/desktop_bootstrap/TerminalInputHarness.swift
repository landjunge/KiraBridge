import Foundation
import ApplicationServices
import CryptoKit

@main
struct TerminalInputHarness {
    @MainActor static func main() async throws {
        SystemBridgeRuntime.principal = "terminal_fixture"
        var checks = 0, simulatedPosts = 0
        func refuse(_ action: () throws -> Void) {
            do { try action(); fatalError("Unsafe private terminal input accepted") }
            catch is SystemBridgeFailure { checks += 1 }
            catch { fatalError("Unexpected failure: \(error)") }
        }
        let owner: [String: Any] = ["task_id": "original_terminal_task", "principal": "terminal_fixture",
            "operation": "terminal.visible", "request_sha256": String(repeating: "a", count: 64)]
        _ = try SystemKeyboard.terminalOwner(owner); checks += 1
        var agentOwner = owner; agentOwner["operation"] = "agent.execute"
        _ = try SystemKeyboard.terminalOwner(agentOwner); checks += 1
        let descriptor: [String: Any] = ["cg_window_id": 12916, "tty": "/dev/ttys000", "shell_pid": 99,
            "shell_identity_sha256": String(repeating: "b", count: 64), "cwd_sha256": String(repeating: "c", count: 64)]
        _ = try SystemKeyboard.terminalDescriptor(descriptor); checks += 1
        for change: [String: Any] in [["tty": "/dev/ttys000\n"], ["tty": "/dev/../ttys000"],
                                     ["shell_pid": -1], ["cg_window_id": true], ["cwd_sha256": "wrong"]] {
            var changed = descriptor; changed.merge(change) { _, new in new }
            refuse { _ = try SystemKeyboard.terminalDescriptor(changed) }
        }
        for (key, value) in [("task_id", "bad task"), ("principal", "foreign"),
                             ("operation", "keyboard.text"), ("request_sha256", "bad")] {
            var changed = owner; changed[key] = value
            refuse { _ = try SystemKeyboard.terminalOwner(changed) }
        }
        var extra = owner; extra["allow_terminal"] = true
        refuse { _ = try SystemKeyboard.terminalOwner(extra) }
        for text in ["/bin/echo safe", "e\u{301}😀", "'quoted command'", "x\\y"] {
            try SystemKeyboard.terminalLiteral(text); checks += 1
        }
        for text in ["\t", "\r", "\n", "\r\n", "\0", "\u{1b}", "\u{7f}", "\u{85}",
                     "\u{2028}", "\u{2029}", "\u{feff}", "\u{202e}", "\u{200b}"] {
            refuse { try SystemKeyboard.terminalLiteral("before" + text + "after") }
        }
        for name in [kAXSubroleAttribute, kAXEnabledAttribute, "AXProtectedContent"] {
            let unsupported = try SystemKeyboard.terminalAttributeResult(name, status: .attributeUnsupported, value: nil)
            precondition(unsupported == nil)
            checks += 1
            refuse { _ = try SystemKeyboard.terminalAttributeResult(name, status: .cannotComplete, value: nil) }
            refuse { _ = try SystemKeyboard.terminalAttributeResult(name, status: .success, value: nil) }
        }
        refuse { _ = try SystemKeyboard.terminalAttributeResult(kAXValueAttribute, status: .attributeUnsupported, value: nil) }
        func field(_ value: String, location: Int? = nil, length: Int = 0,
                   changes: [String: Any] = [:]) throws -> SystemKeyboard.Field {
            var range = CFRange(location: location ?? value.utf16.count, length: length)
            var attributes: [String: Any] = [kAXRoleAttribute: "AXTextArea", kAXFocusedAttribute: true,
                kAXNumberOfCharactersAttribute: value.utf16.count,
                kAXValueAttribute: value, kAXSelectedTextRangeAttribute: AXValueCreate(.cfRange, &range)!]
            attributes.merge(changes) { _, new in new }
            return try SystemKeyboard.terminalField { attributes[$0] as CFTypeRef? }
        }
        let value = "$ /bin/echo e\u{301}😀"
        let correct = try field(value)
        precondition(correct.metadata["enabled"] is NSNull && correct.metadata["scope"] as? String == "terminal_shell")
        checks += 1
        refuse { _ = try field(value, length: 1) }
        refuse { _ = try field(value, location: value.utf16.count - 1) }
        refuse { _ = try field(value, location: -1) }
        for badCount: Any in [true, false, -1, 0, 1.5, value.utf16.count - 1, NSNull()] {
            refuse { _ = try field(value, changes: [kAXNumberOfCharactersAttribute: badCount]) }
        }
        for change in [[kAXRoleAttribute: "AXSecureTextField"], [kAXSubroleAttribute: "AXSecureTextField"],
                       [kAXEnabledAttribute: false], [kAXFocusedAttribute: false], ["AXProtectedContent": true]] {
            refuse { _ = try field(value, changes: change) }
        }
        let geometry = CGRect(x: 10, y: 20, width: 600, height: 400)
        let window: [String: Any] = ["window_id": 12916, "owner_pid": 100, "layer": 0, "on_screen": true,
            "bounds": ["X": 10.0, "Y": 20.0, "Width": 600.0, "Height": 400.0]]
        try SystemKeyboard.terminalCGWindow([window], pid: 100, id: 12916, geometry: geometry); checks += 1
        refuse { try SystemKeyboard.terminalCGWindow([window], pid: 101, id: 12916, geometry: geometry) }
        refuse { try SystemKeyboard.terminalCGWindow([window], pid: 100, id: 11084, geometry: geometry) }
        var other = window; other["window_id"] = 11084
        refuse { try SystemKeyboard.terminalCGWindow([window, other], pid: 100, id: 12916, geometry: geometry) }
        try SystemKeyboard.terminalTabMembership(roles: ["AXRadioButton", "AXButton"], selected: [true]); checks += 1
        refuse { try SystemKeyboard.terminalTabMembership(roles: ["AXRadioButton", "AXRadioButton"], selected: [true, false]) }
        refuse { try SystemKeyboard.terminalTabMembership(roles: ["AXRadioButton"], selected: [false]) }
        refuse { try SystemKeyboard.terminalTabMembership(roles: ["AXGroup"], selected: []) }
        func shell(_ uid: uid_t, name: String = "zsh", pid: pid_t = 99) -> SystemServices.Record {
            SystemServices.Record(pid: pid, parent: 55, uid: uid, realUID: uid, savedUID: uid,
                name: name, path: nil, start: "123.000001", tty: true, terminalDevice: 100)
        }
        try SystemKeyboard.terminalShellRowsAllowed([shell(501)], pid: 99, uid: 501); checks += 1
        func login(real: uid_t = 501, saved: uid_t = 0, pid: pid_t = 55) -> SystemServices.Record {
            SystemServices.Record(pid: pid, parent: 44, uid: 0, realUID: real, savedUID: saved,
                name: "login", path: nil, start: "123.000000", tty: true, terminalDevice: 100)
        }
        try SystemKeyboard.terminalShellRowsAllowed([shell(501), login()], pid: 99, uid: 501); checks += 1
        try SystemKeyboard.terminalShellRowsAllowed([shell(501), login(real: 0)], pid: 99, uid: 501); checks += 1
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(501), login(pid: 54)], pid: 99, uid: 501) }
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(501), login(real: 502)], pid: 99, uid: 501) }
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(501), login(saved: 501)], pid: 99, uid: 501) }
        let incomplete = SystemServices.Snapshot(records: [shell(501)], unavailable: [123])
        refuse { _ = try SystemKeyboard.terminalCensusRecords(incomplete) }
        do {
            _ = try await SystemKeyboard.writeText([[65]], prepare: { _ in }, validate: { _ in
                _ = try SystemKeyboard.terminalCensusRecords(incomplete)
            }, sameGeneration: { true }, post: { _ in fatalError("Incomplete census permitted text") }, verify: { true })
            fatalError("Incomplete census accepted")
        } catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); checks += 1 }
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(UInt32(bitPattern: -2))], pid: 99, uid: 501) }
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(501, name: "codex")], pid: 99, uid: 501) }
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(501)], pid: 98, uid: 501) }
        refuse { try SystemKeyboard.terminalShellRowsAllowed([shell(501), shell(502, pid: 100)], pid: 99, uid: 501) }
        let target: [String: Any] = ["pid": 100, "expected_started_at": 12.0,
            "target_token": String(repeating: "b", count: 32), "helper_pid": 1000,
            "worker_generation": SystemBridgeRuntime.generation, "expected_revision": String(repeating: "c", count: 64)]
        let stagedID = String(repeating: "e", count: 64)
        SystemKeyboard.transfer = SystemKeyboard.TextTransfer(id: stagedID, principal: "terminal_fixture", task: "original_terminal_task",
            digest: String(repeating: "a", count: 64), target: target, submit: false, bytes: 1, units: 1, chunks: 1,
            now: ProcessInfo.processInfo.systemUptime, terminal: true)
        refuse { _ = try SystemKeyboard.chunkTransfer(["transfer_id": stagedID, "index": 0, "data_b64": "QQA="]) }
        refuse { _ = try SystemKeyboard.abortTransfer(["transfer_id": stagedID]) }
        _ = try SystemKeyboard.abortTransfer(["transfer_id": stagedID], terminal: true); checks += 1
        SystemKeyboard.transfer = SystemKeyboard.TextTransfer(id: stagedID, principal: "terminal_fixture", task: "original_terminal_task",
            digest: String(repeating: "a", count: 64), target: target, submit: false, bytes: 1, units: 1, chunks: 1,
            now: ProcessInfo.processInfo.systemUptime)
        refuse { _ = try SystemKeyboard.ownedTransfer(["transfer_id": stagedID], now: ProcessInfo.processInfo.systemUptime, terminal: true) }
        _ = try SystemKeyboard.abortTransfer(["transfer_id": stagedID]); checks += 1
        let expected = SystemKeyboard.TextState(value: correct.value, units: Array(correct.value.utf16), selection: correct.selection)
        func commit() -> SystemKeyboard.TerminalCommit {
            SystemKeyboard.TerminalCommit(owner: owner, target: target, transferID: String(repeating: "d", count: 64), expected: expected)
        }
        let args: [String: Any] = ["owner": owner, "target": target, "transfer_id": String(repeating: "d", count: 64),
            "expected_value_sha256": SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined(),
            "selection_utf16": ["location": correct.selection.location, "length": 0]]
        refuse { _ = try SystemKeyboard.performTerminalReturn(commit(), args: args, observe: {
            _ = try SystemKeyboard.terminalCensusRecords(incomplete); return correct
        }, validate: {}, sameGeneration: { true }, post: { _ in fatalError("Incomplete census permitted Return") }) }
        let once = commit()
        var posts: [Bool] = []
        let result = try SystemKeyboard.performTerminalReturn(once, args: args, observe: { correct }, validate: {},
            sameGeneration: { true }, post: { posts.append($0); simulatedPosts += 1 })
        precondition(once.consumed && posts == [true, false] && result["post_calls_returned"] as? Int == 2)
        checks += 1
        refuse { _ = try SystemKeyboard.performTerminalReturn(once, args: args, observe: { fatalError("Consumed cap observed again") },
            validate: {}, sameGeneration: { true }, post: { _ in fatalError("Repeated Return") }) }
        for altered in [try field(value + "x"), try field(value, location: 0), try field("$ /bin/echo é😀")] {
            let cap = commit()
            refuse { _ = try SystemKeyboard.performTerminalReturn(cap, args: args, observe: { altered }, validate: {},
                sameGeneration: { true }, post: { _ in fatalError("Changed command/caret received Return") }) }
            precondition(cap.consumed)
        }
        // A long wrapper can softwrap/scroll in the real terminal. This fixture
        // proves refusal of rendered extra newlines, not the actual AX semantics.
        let longWrapper = "$ /bin/zsh -f /Users/fixture/.local/state/" + String(repeating: "long-wrapper-", count: 24) + "/command.zsh"
        let wrappedValue = String(longWrapper.prefix(80)) + "\n" + String(longWrapper.dropFirst(80))
        let longField = try field(longWrapper), wrappedField = try field(wrappedValue)
        let longState = SystemKeyboard.TextState(value: longWrapper, units: Array(longWrapper.utf16), selection: longField.selection)
        let longCap = SystemKeyboard.TerminalCommit(owner: owner, target: target, transferID: String(repeating: "d", count: 64), expected: longState)
        var longArgs = args
        longArgs["expected_value_sha256"] = SHA256.hash(data: Data(longWrapper.utf8)).map { String(format: "%02x", $0) }.joined()
        longArgs["selection_utf16"] = ["location": longField.selection.location, "length": 0]
        refuse { _ = try SystemKeyboard.performTerminalReturn(longCap, args: longArgs, observe: { wrappedField }, validate: {},
            sameGeneration: { true }, post: { _ in fatalError("Softwrapped changed buffer received Return") }) }
        var softwrapPosts = 0, softwrapUnknown = false
        do {
            _ = try await SystemKeyboard.writeText(try SystemKeyboard.textChunks(longWrapper), prepare: { _ in },
                validate: { _ in }, sameGeneration: { true }, post: { _ in softwrapPosts += 1 },
                verify: { longState.matches(wrappedField) })
            fatalError("Rendered softwrap declared literal insertion verified")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && softwrapPosts > 2)
            softwrapUnknown = true; checks += 1
        }
        for key in ["owner", "target", "transfer_id", "expected_value_sha256", "selection_utf16"] {
            var foreign = args
            if key == "owner" { var changed = owner; changed["request_sha256"] = String(repeating: "f", count: 64); foreign[key] = changed }
            else if key == "target" { var changed = target; changed["pid"] = 101; foreign[key] = changed }
            else if key == "selection_utf16" { foreign[key] = ["location": 0, "length": 0] }
            else { foreign[key] = String(repeating: "f", count: 64) }
            let cap = commit()
            refuse { _ = try SystemKeyboard.performTerminalReturn(cap, args: foreign, observe: { fatalError("Foreign cap observed") },
                validate: {}, sameGeneration: { true }, post: { _ in fatalError("Foreign cap received Return") }) }
            precondition(!cap.consumed)
        }
        let lost = commit(); var cleanup: [Bool] = []
        do {
            _ = try SystemKeyboard.performTerminalReturn(lost, args: args, observe: { correct }, validate: {},
                sameGeneration: { true }, post: { down in
                    cleanup.append(down); simulatedPosts += 1
                    if down { throw SystemControl.failure("fixture_lost_reply", "fixture") }
                })
            fatalError("Lost keydown reply declared successful")
        } catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && lost.consumed && cleanup == [true, false]); checks += 1
        }
        print(String(data: try JSONSerialization.data(withJSONObject: ["checks": checks, "simulated_posts": simulatedPosts,
            "softwrap_after_typing_unknown": softwrapUnknown,
            "native_ui_calls": 0, "event_posts": 0, "permission_requests": 0]), encoding: .utf8)!)
    }
}

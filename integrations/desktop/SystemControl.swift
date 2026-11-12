import AppKit
import ApplicationServices
import CoreGraphics
import CryptoKit
import SystemConfiguration
import UserNotifications

/// Public application/system/AX operations. Element references live only in this
/// worker, are principal-owned, expire, and never survive a worker generation.
@MainActor
enum SystemControl {
    struct ElementRecord {
        let element: AXUIElement
        let pid: pid_t
        let started: Double
        let principal: String
        var expires: Date
        var children: [AXUIElement]? = nil
        var treeGeneration: String? = nil
    }
    static var elements: [String: ElementRecord] = [:]
    static let terminalBundles: Set<String> = [
        "com.apple.Terminal", "com.googlecode.iterm2", "com.mitchellh.ghostty",
        "com.github.wez.wezterm", "net.kovidgoyal.kitty", "org.alacritty"
    ]

    static func failure(_ code: String, _ message: String, unknown: Bool = false) -> SystemBridgeFailure {
        SystemBridgeFailure(code: code, message: message, effectUnknown: unknown)
    }
    static func hash(_ value: Any) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    static func integer(_ args: [String: Any], _ key: String, _ fallback: Int) -> Int {
        (args[key] as? NSNumber)?.intValue ?? fallback
    }
    static func appIdentity(_ app: NSRunningApplication) throws -> [String: Any] {
        guard !app.isTerminated, let started = app.launchDate else {
            throw failure("macos_target_changed", "Application start identity is unavailable")
        }
        return ["pid": Int(app.processIdentifier), "started_at": started.timeIntervalSince1970,
                "bundle_id": app.bundleIdentifier ?? "", "name": app.localizedName ?? "",
                "app_path": app.bundleURL?.path ?? "", "executable": app.executableURL?.path ?? "",
                "active": app.isActive, "hidden": app.isHidden,
                "user_application": app.activationPolicy == .regular]
    }
    static func target(_ args: [String: Any], mutating: Bool = false) throws -> NSRunningApplication {
        guard let number = args["pid"] as? NSNumber, number.int64Value > 0, number.int64Value <= Int64(Int32.max),
              number.doubleValue == Double(number.int64Value),
              let started = args["expected_started_at"] as? NSNumber,
              let app = NSRunningApplication(processIdentifier: pid_t(number.intValue)),
              !app.isTerminated, let actualStart = app.launchDate,
              actualStart.timeIntervalSince1970 == started.doubleValue else {
            throw failure("macos_target_changed", "Application PID/start identity no longer matches")
        }
        guard app.processIdentifier != ProcessInfo.processInfo.processIdentifier else {
            throw failure("macos_protected_target", "The native worker cannot target itself")
        }
        if mutating && terminalBundles.contains(app.bundleIdentifier ?? "") {
            throw failure("macos_terminal_route_required", "Terminal input and lifecycle use the existing guarded session operations")
        }
        if mutating {
            try protectLiveTerminalDescendants(app.processIdentifier,
                targetBundlePath: app.bundleURL?.path ?? "",
                targetExecutablePath: app.executableURL?.path ?? "")
        }
        return app
    }
    /// One canonical absolute form for bundle containment checks. A firmlink or
    /// `..` segment cannot disguise a process outside the exact target bundle.
    static func canonicalExecutablePath(_ path: String) -> String? {
        guard path.hasPrefix("/") else { return nil }
        let resolved = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL.path
        let data = "/System/Volumes/Data/"
        return resolved.hasPrefix(data) ? "/" + String(resolved.dropFirst(data.count)) : resolved
    }
    /// The target app's own helpers are its UI infrastructure, not a hosted
    /// agent terminal. They must live inside the exact target bundle, have no
    /// controlling terminal, and be the main executable or follow the app's
    /// helper naming. Unknown paths never qualify.
    static func isAppOwnedHelper(record: SystemServices.Record, targetBundlePath: String,
                                 targetExecutablePath: String) -> Bool {
        guard !record.tty, let bundle = canonicalExecutablePath(targetBundlePath),
              bundle.hasSuffix(".app"),
              let executable = record.path.flatMap(canonicalExecutablePath),
              executable.hasPrefix(bundle + "/") else { return false }
        if let main = canonicalExecutablePath(targetExecutablePath),
           main.hasPrefix(bundle + "/"), executable == main { return true }
        let pattern = " helper( \\([a-z]+\\))?$"
        return [record.name.lowercased().trimmingCharacters(in: .whitespaces),
                URL(fileURLWithPath: executable).lastPathComponent.lowercased()]
            .contains { $0.range(of: pattern, options: .regularExpression) != nil }
    }
    /// A descendant that still requires the guarded terminal route. The broad
    /// agent classification remains intact; only the exact target's own helpers
    /// are exempted, and only with a complete no-TTY identity.
    static func requiresGuardedRoute(_ record: SystemServices.Record, targetPID: pid_t,
                                     targetBundlePath: String,
                                     targetExecutablePath: String) -> Bool {
        guard record.pid != targetPID,
              SystemServices.knownProtected(record) || record.tty else { return false }
        return !isAppOwnedHelper(record: record, targetBundlePath: targetBundlePath,
            targetExecutablePath: targetExecutablePath)
    }
    static func protectLiveTerminalDescendants(_ targetPID: pid_t, targetBundlePath: String,
                                               targetExecutablePath: String) throws {
        // Public process metadata only. Editors hosting shells/agents must use
        // their guarded terminal route rather than a generic AX write/quit.
        let observation = try SystemServices.guardedSnapshot(targetPID: targetPID,
            workerPID: getpid(), corePID: getppid())
        guard observation.unavailable.isEmpty,
              observation.records.contains(where: { $0.pid == targetPID }) else {
            throw failure("macos_process_observation", "Target descendant inventory is incomplete")
        }
        var descendants: Set<pid_t> = [targetPID]
        var complete = false
        for _ in 0..<128 {
            let old = descendants
            for row in observation.records where descendants.contains(row.parent) { descendants.insert(row.pid) }
            if descendants == old { complete = true; break }
        }
        guard complete else {
            throw failure("macos_process_limit", "Target descendant graph exceeds observation depth")
        }
        var blocking = observation.records.filter {
            $0.pid != targetPID && descendants.contains($0.pid)
                && (SystemServices.knownProtected($0) || $0.tty)
        }
        guard blocking.count <= 128 else {
            throw failure("macos_process_limit", "Target descendant agent candidates exceed observation budget")
        }
        // Electron helper processes are not AppKit applications, so the guarded
        // snapshot leaves their public path unavailable. Bind each remaining
        // candidate's executable identity once; a missing or changed path blocks.
        for index in blocking.indices where blocking[index].path == nil && !blocking[index].tty {
            let observed = try SystemServices.read(blocking[index].pid,
                applications: [blocking[index].pid])
            guard observed.pid == blocking[index].pid,
                  observed.kernel == blocking[index].kernel else {
                throw failure("macos_process_changed", "Descendant changed during its executable observation")
            }
            blocking[index] = observed
        }
        if blocking.contains(where: {
            requiresGuardedRoute($0, targetPID: targetPID, targetBundlePath: targetBundlePath,
                targetExecutablePath: targetExecutablePath)
        }) {
            throw failure("macos_agent_route_required", "Application hosts an active terminal/agent process; its guarded session route is required")
        }
    }

    static func axGranted() throws {
        guard AXIsProcessTrusted() else {
            throw failure("macos_permission_denied", "This native worker has no current Accessibility grant; no request was made")
        }
    }
    // Cocoa text views can report .failure for these optional descriptive
    // fields. This is not a license to ignore transport or classification errors.
    static func unavailableOptionalMetadata(_ name: String, status: AXError) -> Bool {
        status == .failure && [kAXDescriptionAttribute, kAXIdentifierAttribute].contains(name)
    }
    static func attribute(_ element: AXUIElement, _ name: String,
                          unavailableMetadata: (String) -> Void = { _ in }) -> CFTypeRef? {
        var result: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, name as CFString, &result)
        if unavailableOptionalMetadata(name, status: status) { unavailableMetadata(name) }
        guard status == .success else { return nil }
        return result
    }
    static func string(_ element: AXUIElement, _ name: String) -> String {
        attribute(element, name) as? String ?? ""
    }
    static func secure(_ element: AXUIElement) -> Bool {
        string(element, kAXRoleAttribute).contains("Secure") || string(element, kAXSubroleAttribute).contains("Secure")
    }
    static func summary(_ element: AXUIElement) throws -> [String: Any] {
        var unavailable: Set<String> = []
        return try observedSummary(prepare: {
                guard AXUIElementSetMessagingTimeout(element, 1.0) == .success else {
                    throw failure("macos_accessibility_unavailable", "Accessibility timeout could not be configured")
                }
            },
            read: { attribute(element, $0, unavailableMetadata: { unavailable.insert($0) }) }, actionNames: {
                var actions: CFArray?
                guard AXUIElementCopyActionNames(element, &actions) == .success else { return nil }
                return actions as? [String] ?? []
            }, unavailableMetadata: { unavailable.sorted() })
    }
    static func observedSummary(prepare: () throws -> Void,
                                read: (String) -> CFTypeRef?,
                                actionNames: () -> [String]?,
                                unavailableMetadata: () -> [String] = { [] }) throws -> [String: Any] {
        func text(_ name: String) -> String { read(name) as? String ?? "" }
        try prepare()
        let role = text(kAXRoleAttribute)
        guard !role.isEmpty else {
            throw failure("macos_accessibility_unavailable", "Accessibility element attributes are not currently observable")
        }
        let subrole = text(kAXSubroleAttribute)
        let isSecure = role.contains("Secure") || subrole.contains("Secure")
        let title = text(kAXTitleAttribute), description = text(kAXDescriptionAttribute)
        var result: [String: Any] = ["role": role,
            "subrole": subrole,
            "identifier": text(kAXIdentifierAttribute),
            "title": String(title.prefix(4096)),
            "description": String(description.prefix(4096)),
            "title_truncated": title.count > 4096,
            "description_truncated": description.count > 4096,
            "secure_value_redacted": isSecure]
        if !isSecure, let value = read(kAXValueAttribute) {
            if let text = value as? String {
                result["value_sha256"] = SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
                result["value_characters"] = text.count
            } else if let number = value as? NSNumber { result["value"] = number }
        }
        for (key, attr) in [("enabled", kAXEnabledAttribute), ("focused", kAXFocusedAttribute),
                            ("selected", kAXSelectedAttribute), ("expanded", kAXExpandedAttribute),
                            ("minimized", kAXMinimizedAttribute)] {
            if let value = read(attr) as? NSNumber { result[key] = value }
        }
        for (key, attr, type) in [("position", kAXPositionAttribute, AXValueType.cgPoint),
                                  ("size", kAXSizeAttribute, AXValueType.cgSize)] {
            if let raw = read(attr), CFGetTypeID(raw) == AXValueGetTypeID() {
                let value = unsafeBitCast(raw, to: AXValue.self)
                if type == .cgPoint {
                    var point = CGPoint.zero
                    if AXValueGetValue(value, type, &point) { result[key] = [point.x, point.y] }
                } else {
                    var size = CGSize.zero
                    if AXValueGetValue(value, type, &size) { result[key] = [size.width, size.height] }
                }
            }
        }
        if let actions = actionNames() { result["actions"] = actions }
        let unavailable = unavailableMetadata()
        if !unavailable.isEmpty { result["unavailable_metadata"] = unavailable }
        result["revision"] = try hash(result)
        return result
    }
    // The revision covers the full observed catalog, including focus/hidden flags.
    // Keeping those flags stable across pages is intentional; focus changes restart traversal.
    static func applicationPage(_ all: [[String: Any]], args: [String: Any]) throws -> [String: Any] {
        let revision = try hash(all)
        if let expected = args["expected_revision"] as? String, expected != revision {
            throw failure("macos_catalog_changed", "Running application catalog changed")
        }
        let offset = integer(args, "offset", 0), limit = integer(args, "limit", 100)
        guard offset >= 0, offset <= all.count, limit >= 1, limit <= 1000 else {
            throw failure("invalid_cursor", "Invalid application catalog page")
        }
        let page = Array(all.dropFirst(offset).prefix(limit))
        var result: [String: Any] = ["applications": page, "revision": revision,
            "offset": offset, "total": all.count, "eof": offset + page.count >= all.count,
            "truncated": offset + page.count < all.count, "effect": "none"]
        if offset + page.count < all.count { result["next_offset"] = offset + page.count }
        return result
    }
    static func remember(_ element: AXUIElement, app: NSRunningApplication,
                         messagingTimeout: Float = 1.0) throws -> String {
        AXUIElementSetMessagingTimeout(element, messagingTimeout)
        var actual: pid_t = 0
        guard AXUIElementGetPid(element, &actual) == .success, actual == app.processIdentifier else {
            throw failure("macos_target_changed", "Accessibility element belongs to a different application")
        }
        elements = elements.filter { $0.value.expires > Date() }
        if let found = elements.first(where: {
            $0.value.pid == app.processIdentifier && $0.value.started == app.launchDate?.timeIntervalSince1970 && $0.value.principal == SystemBridgeRuntime.principal && CFEqual($0.value.element, element)
        }) {
            elements[found.key]?.expires = Date().addingTimeInterval(300)
            return found.key
        }
        guard elements.count < 4096, let date = app.launchDate else {
            throw failure("macos_resource_limit", "Accessibility reference budget exhausted")
        }
        let token = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        elements[token] = ElementRecord(element: element, pid: app.processIdentifier,
            started: date.timeIntervalSince1970, principal: SystemBridgeRuntime.principal,
            expires: Date().addingTimeInterval(300))
        return token
    }
    static func element(_ args: [String: Any], app: NSRunningApplication) throws -> AXUIElement {
        guard let token = args["element_token"] as? String,
              integer(args, "helper_pid", -1) == Int(ProcessInfo.processInfo.processIdentifier),
              args["worker_generation"] as? String == String(describing: SystemBridgeRuntime.generation),
              let record = elements[token], record.expires > Date(),
              record.principal == SystemBridgeRuntime.principal,
              record.pid == app.processIdentifier, record.started == app.launchDate?.timeIntervalSince1970 else {
            throw failure("macos_element_expired", "Element reference is expired, foreign or belongs to another native worker")
        }
        var actual: pid_t = 0
        guard AXUIElementGetPid(record.element, &actual) == .success, actual == app.processIdentifier else {
            throw failure("macos_target_changed", "Accessibility element no longer belongs to this application")
        }
        return record.element
    }
    static func checkElementOwner(_ element: AXUIElement, pid: pid_t) throws {
        var actual: pid_t = 0
        guard AXUIElementGetPid(element, &actual) == .success, actual == pid else {
            throw failure("macos_target_changed", "Accessibility child belongs to a different application")
        }
    }
    static func sameElements(_ left: [AXUIElement], _ right: [AXUIElement]) -> Bool {
        left.count == right.count && zip(left, right).allSatisfy { CFEqual($0.0, $0.1) }
    }
    // A tree read amortizes native/cloud dispatches, not authorization. References
    // still belong to this principal, PID/start identity and worker generation.
    struct TreeReference: Hashable {
        let element: AXUIElement
        static func == (left: Self, right: Self) -> Bool { CFEqual(left.element, right.element) }
        func hash(into hasher: inout Hasher) { hasher.combine(CFHash(element)) }
    }
    struct TreeObservation<Node: Hashable> {
        let node: Node
        let token: String
        let metadata: [String: Any]
        let children: [Node]
    }
    enum TreeReadLimit: Error { case deadline }
    nonisolated static func treeNow() -> Double { ProcessInfo.processInfo.systemUptime }
    static func checkTreeDeadline(_ deadline: Double) throws {
        if treeNow() >= deadline { throw TreeReadLimit.deadline }
    }
    static func prepareTreeElement(_ element: AXUIElement, deadline: Double) throws {
        try checkTreeDeadline(deadline)
        // One already-started AX IPC can extend the cooperative deadline by at
        // most this timeout. Every following attribute checks the deadline first.
        let timeout = Float(max(0.001, min(0.1, deadline - treeNow())))
        guard AXUIElementSetMessagingTimeout(element, timeout) == .success else {
            throw failure("macos_accessibility_unavailable", "Accessibility timeout could not be configured")
        }
    }
    static func treeAttribute(_ element: AXUIElement, _ name: String, deadline: Double,
                              unavailableMetadata: (String) -> Void = { _ in }) throws -> CFTypeRef? {
        try checkTreeDeadline(deadline)
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, name as CFString, &value)
        try checkTreeDeadline(deadline)
        return try treeAttributeValue(name, status: status, value: value,
            unavailableMetadata: unavailableMetadata)
    }
    // The same decoder is used by scalar and positional batch reads and the
    // synthetic harness. Only a named optional metadata failure is tolerated.
    static func treeAttributeValue(_ name: String, status: AXError, value: CFTypeRef?,
                                   unavailableMetadata: (String) -> Void = { _ in }) throws -> CFTypeRef? {
        if status == .success {
            guard let observed = value else {
                throw failure("macos_accessibility_unavailable", "Accessibility reported success without an observable attribute value")
            }
            return observed
        }
        if status == .attributeUnsupported || status == .noValue { return nil }
        if unavailableOptionalMetadata(name, status: status) {
            unavailableMetadata(name)
            return nil
        }
        throw failure("macos_accessibility_unavailable", "Accessibility attribute could not be observed during subtree read")
    }
    static func treeChildren(_ raw: CFTypeRef?) throws -> [AXUIElement] {
        guard let value = raw else { return [] }
        guard CFGetTypeID(value) == CFArrayGetTypeID() else {
            throw failure("macos_accessibility_unavailable", "Accessibility children are not an observable array")
        }
        guard CFArrayGetCount(unsafeBitCast(value, to: CFArray.self)) <= 5000 else {
            throw failure("macos_resource_limit", "Accessibility subtree child reference budget exceeded")
        }
        guard let items = value as? [AnyObject] else {
            throw failure("macos_accessibility_unavailable", "Accessibility children cannot be decoded")
        }
        return try items.map { item in
            guard CFGetTypeID(item) == AXUIElementGetTypeID() else {
                throw failure("macos_accessibility_unavailable", "Accessibility child is not an element reference")
            }
            return unsafeBitCast(item, to: AXUIElement.self)
        }
    }
    static func treeActionNames(_ raw: CFArray?) throws -> [String] {
        guard let value = raw else {
            throw failure("macos_accessibility_unavailable", "Accessibility action names are not an observable array")
        }
        guard CFArrayGetCount(value) <= 128 else {
            throw failure("macos_resource_limit", "Accessibility action name budget exceeded")
        }
        guard let names = value as? [String] else {
            throw failure("macos_accessibility_unavailable", "Accessibility action names cannot be decoded")
        }
        guard names.allSatisfy({ $0.utf8.count <= 256 }) else {
            throw failure("macos_resource_limit", "Accessibility action name length budget exceeded")
        }
        return names
    }
    // Retained as the compatibility path when the application does not implement
    // the whole multiple-attribute API. Values are freshly observed again; no
    // partial fields from an unsupported batch are reused.
    static func individualTreeSummary(_ element: AXUIElement, deadline: Double) throws -> [String: Any] {
        var readError: Error?
        var unavailable: Set<String> = []
        do {
            let result = try observedSummary(prepare: { try prepareTreeElement(element, deadline: deadline) },
                read: { name in
                    guard readError == nil else { return nil }
                    do {
                        let value = try treeAttribute(element, name, deadline: deadline,
                            unavailableMetadata: { unavailable.insert($0) })
                        if [kAXRoleAttribute, kAXSubroleAttribute].contains(name),
                           let observed = value, !(observed is String) {
                            throw failure("macos_accessibility_unavailable", "Accessibility secure classification is not observable")
                        }
                        return value
                    }
                    catch { readError = error; return nil }
                }, actionNames: {
                    guard readError == nil else { return nil }
                    do {
                        try checkTreeDeadline(deadline)
                        var actions: CFArray?
                        let status = AXUIElementCopyActionNames(element, &actions)
                        try checkTreeDeadline(deadline)
                        if status == .notImplemented { return nil }
                        guard status == .success else {
                            throw failure("macos_accessibility_unavailable", "Accessibility actions could not be observed during subtree read")
                        }
                        return try treeActionNames(actions)
                    } catch { readError = error; return nil }
                }, unavailableMetadata: { unavailable.sorted() })
            if let error = readError { throw error }
            return result
        } catch {
            // In particular, a failed role/subrole read cannot lead to emitting
            // a value/hash from a field whose secure classification is unknown.
            throw readError ?? error
        }
    }
    enum TreeBatchFailure: Error { case notImplemented }
    static let treeClassificationAttributes = [kAXRoleAttribute, kAXSubroleAttribute]
    static let treeMetadataAttributes = [kAXTitleAttribute, kAXDescriptionAttribute, kAXIdentifierAttribute,
        kAXEnabledAttribute, kAXFocusedAttribute, kAXSelectedAttribute, kAXExpandedAttribute,
        kAXMinimizedAttribute, kAXPositionAttribute, kAXSizeAttribute]

    /// CopyMultiple(options:0) reports missing attributes as CFNull or an
    /// AXValue(.axError) in their original position. Supported absence is omitted;
    /// narrowly allowed descriptive failures are recorded in the summary/revision.
    /// Transport/unknown errors never become compatibility fallbacks.
    static func treeBatchAttributes(_ names: [String], status: AXError, raw: CFArray?,
                                   unavailableMetadata: (String) -> Void = { _ in }) throws -> [String: CFTypeRef] {
        guard !names.isEmpty, names.count <= 32, Set(names).count == names.count else {
            throw failure("invalid_arguments", "Invalid Accessibility attribute batch")
        }
        if status == .notImplemented { throw TreeBatchFailure.notImplemented }
        guard status == .success, let values = raw,
              CFGetTypeID(values) == CFArrayGetTypeID(),
              CFArrayGetCount(values) == names.count,
              let items = values as? [AnyObject] else {
            throw failure("macos_accessibility_unavailable", "Accessibility attribute batch is not a complete positional array")
        }
        var result: [String: CFTypeRef] = [:]
        for (name, item) in zip(names, items) {
            if CFGetTypeID(item) == CFNullGetTypeID() { continue }
            if CFGetTypeID(item) == AXValueGetTypeID() {
                let value = unsafeBitCast(item, to: AXValue.self)
                if AXValueGetType(value) == .axError {
                    var error = AXError.failure
                    guard AXValueGetValue(value, .axError, &error), error != .success else {
                        throw failure("macos_accessibility_unavailable", "Accessibility batch contains an invalid error value")
                    }
                    _ = try treeAttributeValue(name, status: error, value: nil,
                        unavailableMetadata: unavailableMetadata)
                    continue
                }
            }
            result[name] = item
        }
        return result
    }
    /// Pure public-API call planner, injected by the synthetic harness. This
    /// reduces API invocations, without asserting the framework's IPC internals.
    static func observedBatchedTreeSummary(prepare: () throws -> Void,
        copy: ([String]) throws -> (AXError, CFArray?),
        actionNames: () throws -> [String]?,
        individual: () throws -> [String: Any]) throws -> [String: Any] {
        do {
            var unavailable: Set<String> = []
            try prepare()
            let classification = try copy(treeClassificationAttributes)
            var values = try treeBatchAttributes(treeClassificationAttributes,
                status: classification.0, raw: classification.1)
            guard let role = values[kAXRoleAttribute] as? String, !role.isEmpty,
                  values[kAXSubroleAttribute] == nil || values[kAXSubroleAttribute] is String else {
                throw failure("macos_accessibility_unavailable", "Accessibility secure classification is not observable")
            }
            let subrole = values[kAXSubroleAttribute] as? String ?? ""
            let secure = role.contains("Secure") || subrole.contains("Secure")
            // A secure value is never requested, rather than fetched and then
            // redacted. Role/subrole are always observed before this list exists.
            let names = Array(treeMetadataAttributes.prefix(3))
                + (secure ? [] : [kAXValueAttribute]) + Array(treeMetadataAttributes.dropFirst(3))
            let metadata = try copy(names)
            values.merge(try treeBatchAttributes(names, status: metadata.0, raw: metadata.1,
                unavailableMetadata: { unavailable.insert($0) })) { _, new in new }
            let actions = try actionNames()
            return try observedSummary(prepare: {}, read: { values[$0] }, actionNames: { actions },
                unavailableMetadata: { unavailable.sorted() })
        } catch TreeBatchFailure.notImplemented {
            return try individual()
        }
    }
    static func treeSummary(_ element: AXUIElement, deadline: Double) throws -> [String: Any] {
        let result = try observedBatchedTreeSummary(
            prepare: { try prepareTreeElement(element, deadline: deadline) },
            copy: { names in
                try checkTreeDeadline(deadline)
                var values: CFArray?
                let status = AXUIElementCopyMultipleAttributeValues(element, names as CFArray, [], &values)
                try checkTreeDeadline(deadline)
                return (status, values)
            }, actionNames: {
                try checkTreeDeadline(deadline)
                var actions: CFArray?
                let status = AXUIElementCopyActionNames(element, &actions)
                try checkTreeDeadline(deadline)
                if status == .notImplemented { return nil }
                guard status == .success else {
                    throw failure("macos_accessibility_unavailable", "Accessibility actions could not be observed during subtree read")
                }
                return try treeActionNames(actions)
            }, individual: { try individualTreeSummary(element, deadline: deadline) })
        try checkTreeDeadline(deadline)
        return result
    }
    /// Pure bounded BFS, also exercised by the no-desktop synthetic harness.
    /// Each observation is locally stable; the whole remote AX graph is not an
    /// atomic snapshot. Mutations recheck the normal individual node revision.
    static func observedTree<Node: Hashable>(root: Node, maxDepth: Int, maxNodes: Int,
        maxBytes: Int, budgetMS: Int, now: () -> Double = treeNow,
        observe: (Node, Double) throws -> TreeObservation<Node>) throws
        -> (tree: [String: Any], root: TreeObservation<Node>) {
        guard (1...32).contains(maxDepth), (1...512).contains(maxNodes),
              (16384...524288).contains(maxBytes), (50...5000).contains(budgetMS) else {
            throw failure("invalid_arguments", "Invalid bounded Accessibility subtree limits")
        }
        let started = now(), deadline = started + Double(budgetMS) / 1000
        var queue: [(node: Node, parent: String?, depth: Int)] = [(root, nil, 0)]
        var discovered: Set<Node> = [root], observations: [TreeObservation<Node>] = []
        var paths: [(parent: String?, depth: Int)] = [], reasons: Set<String> = []
        var cursor = 0, childReferences = 0, estimatedBytes = 2048
        while cursor < queue.count {
            if now() >= deadline { reasons.insert("time_budget"); break }
            let item = queue[cursor]
            let observation: TreeObservation<Node>
            do { observation = try observe(item.node, deadline) }
            catch TreeReadLimit.deadline { reasons.insert("time_budget"); break }
            if now() >= deadline { reasons.insert("time_budget"); break }
            guard observation.children.count <= 5000,
                  childReferences + observation.children.count <= 16384 else {
                throw failure("macos_resource_limit", "Accessibility subtree child reference budget exceeded")
            }
            childReferences += observation.children.count
            var row = observation.metadata
            row["element_token"] = observation.token
            row["parent_token"] = item.parent.map { $0 as Any } ?? NSNull()
            row["depth"] = item.depth
            // Fixed reserve includes the final per-node traversal fields. The
            // actual tree encoding is checked again before it can be returned.
            let rowBytes = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]).count + 160
            if estimatedBytes + rowBytes > maxBytes { reasons.insert("max_tree_bytes"); break }
            estimatedBytes += rowBytes
            observations.append(observation); paths.append((item.parent, item.depth))
            cursor += 1
            if item.depth < maxDepth {
                for child in observation.children where !discovered.contains(child) {
                    if discovered.count >= maxNodes { reasons.insert("max_nodes"); continue }
                    discovered.insert(child)
                    queue.append((child, observation.token, item.depth + 1))
                }
            }
        }
        guard let first = observations.first else {
            if reasons.contains("time_budget") {
                throw failure("macos_tree_timeout", "Accessibility root was not observed within the subtree time budget")
            }
            throw failure("macos_resource_limit", "Accessibility root exceeds the subtree byte budget")
        }
        let included = Set(observations.map { $0.node })
        var rows: [[String: Any]] = []
        for (index, observation) in observations.enumerated() {
            let returned = observation.children.filter { included.contains($0) }.count
            let missing = returned < observation.children.count
            if missing && paths[index].depth == maxDepth { reasons.insert("max_depth") }
            var row = observation.metadata
            row["element_token"] = observation.token
            row["parent_token"] = paths[index].parent.map { $0 as Any } ?? NSNull()
            row["depth"] = paths[index].depth
            row["children_total"] = observation.children.count
            row["children_returned"] = returned
            row["children_truncated"] = missing
            rows.append(row)
        }
        var tree: [String: Any] = ["nodes": rows, "node_count": rows.count,
            "complete": reasons.isEmpty, "truncated_reasons": reasons.sorted(),
            "max_depth": maxDepth, "max_nodes": maxNodes, "max_tree_bytes": maxBytes,
            "tree_budget_ms": budgetMS, "elapsed_ms": (now() - started) * 1000,
            "snapshot_atomic": false, "bytes": 0]
        // This exact check is independent of the conservative linear estimates.
        // Updating the byte count itself can change its digit width.
        for _ in 0..<4 {
            let size = try JSONSerialization.data(withJSONObject: tree, options: [.sortedKeys]).count
            guard size <= maxBytes else {
                throw failure("macos_resource_limit", "Accessibility subtree serialization exceeds its byte budget")
            }
            if tree["bytes"] as? Int == size { break }
            tree["bytes"] = size
        }
        return (tree, first)
    }
    static func inspectTree(_ args: [String: Any], app: NSRunningApplication,
                            root: AXUIElement) throws -> [String: Any] {
        guard integer(args, "offset", 0) == 0, integer(args, "value_offset", 0) == 0,
              args["expected_revision"] == nil else {
            throw failure("invalid_cursor", "A subtree snapshot cannot continue a paginated Accessibility read")
        }
        let snapshot = try observedTree(root: TreeReference(element: root),
            maxDepth: integer(args, "max_depth", 0), maxNodes: integer(args, "max_nodes", 256),
            maxBytes: integer(args, "max_tree_bytes", 262144), budgetMS: integer(args, "tree_budget_ms", 1500)) { reference, deadline in
            let selected = reference.element
            try checkTreeDeadline(deadline)
            try checkElementOwner(selected, pid: app.processIdentifier)
            let before = try treeSummary(selected, deadline: deadline)
            let children = try treeChildren(treeAttribute(selected, kAXChildrenAttribute, deadline: deadline))
            guard children.count <= 5000 else {
                throw failure("macos_resource_limit", "Accessibility subtree child reference budget exceeded")
            }
            for child in children {
                try checkTreeDeadline(deadline)
                try checkElementOwner(child, pid: app.processIdentifier)
            }
            let after = try treeSummary(selected, deadline: deadline)
            let finalChildren = try treeChildren(treeAttribute(selected, kAXChildrenAttribute, deadline: deadline))
            guard before["revision"] as? String == after["revision"] as? String,
                  sameElements(children, finalChildren) else {
                throw failure("macos_tree_changed", "Accessibility element or children changed during subtree read")
            }
            try checkTreeDeadline(deadline)
            let token = try remember(selected, app: app, messagingTimeout: 0.1)
            try checkTreeDeadline(deadline)
            return TreeObservation(node: reference, token: token, metadata: before,
                children: children.map { TreeReference(element: $0) })
        }
        _ = try target(args); try axGranted()
        return ["application": try appIdentity(app), "element": snapshot.root.metadata,
            "element_token": snapshot.root.token,
            "revision": snapshot.root.metadata["revision"]!,
            "revision_scope": "individual_root_element; not a paginated traversal revision",
            "helper_pid": Int(ProcessInfo.processInfo.processIdentifier),
            "worker_generation": String(describing: SystemBridgeRuntime.generation),
            "tree": snapshot.tree, "effect": "none", "permission_requested": false]
    }
    static func inspect(_ args: [String: Any]) throws -> [String: Any] {
        let app = try target(args)
        try axGranted()
        let root = args["element_token"] is String ? try element(args, app: app) : AXUIElementCreateApplication(app.processIdentifier)
        if integer(args, "max_depth", 0) > 0 { return try inspectTree(args, app: app, root: root) }
        let metadata = try summary(root)
        let token = try remember(root, app: app)
        let rawChildren = attribute(root, kAXChildrenAttribute) as? [AXUIElement] ?? []
        let old = elements[token]!
        let sameChildren = old.children.map { sameElements($0, rawChildren) } ?? false
        if (args["expected_revision"] != nil || integer(args, "offset", 0) > 0), old.children != nil, !sameChildren {
            throw failure("macos_tree_changed", "Accessibility children changed between pages")
        }
        let held = elements.filter { $0.key != token }.values.reduce(0) { $0 + ($1.children?.count ?? 0) }
        guard rawChildren.count <= 5000, held + rawChildren.count <= 16384 else {
            throw failure("macos_resource_limit", "Accessibility child reference budget exceeded")
        }
        for child in rawChildren { try checkElementOwner(child, pid: app.processIdentifier) }
        let generation = sameChildren ? old.treeGeneration! : UUID().uuidString
        let traversalRevision = try hash(["element": metadata["revision"]!, "children_generation": generation])
        if let expected = args["expected_revision"] as? String, expected != traversalRevision {
            throw failure("macos_tree_changed", "Accessibility traversal revision changed")
        }
        elements[token]?.children = rawChildren
        elements[token]?.treeGeneration = generation
        let offset = integer(args, "offset", 0), limit = integer(args, "limit", 50)
        guard offset >= 0, limit >= 1, limit <= 250, offset <= rawChildren.count else {
            throw failure("invalid_cursor", "Accessibility child cursor is outside the current element")
        }
        var children: [[String: Any]] = []
        for child in rawChildren.dropFirst(offset).prefix(limit) {
            try checkElementOwner(child, pid: app.processIdentifier)
            var item = try summary(child)
            item["element_token"] = try remember(child, app: app)
            children.append(item)
        }
        var result: [String: Any] = ["application": try appIdentity(app), "element": metadata,
            "element_token": token, "revision": traversalRevision, "helper_pid": Int(ProcessInfo.processInfo.processIdentifier),
            "worker_generation": String(describing: SystemBridgeRuntime.generation),
            "children": children, "offset": offset, "total_children": rawChildren.count,
            "eof": offset + children.count >= rawChildren.count, "truncated": offset + children.count < rawChildren.count,
            "effect": "none", "permission_requested": false]
        if offset + children.count < rawChildren.count { result["next_offset"] = offset + children.count }
        if metadata["secure_value_redacted"] as? Bool == false,
           !secure(root), let text = attribute(root, kAXValueAttribute) as? String {
            let start = integer(args, "value_offset", 0), maxChars = integer(args, "max_value_chars", 4096)
            guard start >= 0, start <= text.count, maxChars >= 1, maxChars <= 16384 else {
                throw failure("invalid_cursor", "Accessibility text cursor is outside the current value")
            }
            let lower = text.index(text.startIndex, offsetBy: start)
            let upper = text.index(lower, offsetBy: maxChars, limitedBy: text.endIndex) ?? text.endIndex
            result["value"] = String(text[lower..<upper]); result["value_offset"] = start
            result["value_eof"] = upper == text.endIndex
            if upper != text.endIndex { result["value_next_offset"] = start + text[lower..<upper].count }
        }
        _ = try target(args)
        try axGranted()
        let finalChildren = attribute(root, kAXChildrenAttribute) as? [AXUIElement] ?? []
        guard try summary(root)["revision"] as? String == metadata["revision"] as? String,
              sameElements(rawChildren, finalChildren) else {
            throw failure("macos_tree_changed", "Accessibility element or child ordering changed during read")
        }
        return result
    }
    static func mutate(_ operation: String, _ args: [String: Any]) throws -> [String: Any] {
        let app = try target(args, mutating: true)
        try axGranted()
        let selected = try element(args, app: app), before = try summary(selected)
        let beforeIdentity = try appIdentity(app)
        guard before["secure_value_redacted"] as? Bool == false,
              !secure(selected), args["expected_revision"] as? String == before["revision"] as? String else {
            throw failure("macos_element_changed", "Secure or changed element cannot be mutated")
        }
        let error: AXError
        if operation == "accessibility.action" {
            let actions = ["press": kAXPressAction, "confirm": kAXConfirmAction, "cancel": kAXCancelAction,
                           "raise": kAXRaiseAction, "increment": kAXIncrementAction, "decrement": kAXDecrementAction,
                           "show_menu": kAXShowMenuAction, "pick": kAXPickAction]
            guard let action = actions[args["action"] as? String ?? ""],
                  (before["actions"] as? [String] ?? []).contains(action) else {
                throw failure("macos_action_unsupported", "Selected element does not expose this public action")
            }
            _ = try target(args, mutating: true); try axGranted()
            error = AXUIElementPerformAction(selected, action as CFString)
        } else {
            let attributes = ["value": kAXValueAttribute, "focused": kAXFocusedAttribute,
                "selected": kAXSelectedAttribute, "expanded": kAXExpandedAttribute,
                "minimized": kAXMinimizedAttribute, "position": kAXPositionAttribute, "size": kAXSizeAttribute]
            guard let key = args["attribute"] as? String, let name = attributes[key], let input = args["value"] else {
                throw failure("invalid_arguments", "Unsupported accessibility attribute")
            }
            var settable = DarwinBoolean(false)
            guard AXUIElementIsAttributeSettable(selected, name as CFString, &settable) == .success, settable.boolValue else {
                throw failure("macos_attribute_read_only", "Selected element does not expose a writable attribute")
            }
            let value: CFTypeRef
            if key == "position", let coordinates = input as? [Double], coordinates.count == 2 {
                var point = CGPoint(x: coordinates[0], y: coordinates[1])
                guard let wrapped = AXValueCreate(.cgPoint, &point) else { throw failure("invalid_arguments", "Invalid position") }
                value = wrapped
            } else if key == "size", let dimensions = input as? [Double], dimensions.count == 2 {
                var size = CGSize(width: dimensions[0], height: dimensions[1])
                guard let wrapped = AXValueCreate(.cgSize, &size) else { throw failure("invalid_arguments", "Invalid size") }
                value = wrapped
            } else if let text = input as? String { value = text as CFString }
            else if let number = input as? NSNumber { value = number }
            else { throw failure("invalid_arguments", "Unsupported accessibility value") }
            _ = try target(args, mutating: true); try axGranted()
            error = AXUIElementSetAttributeValue(selected, name as CFString, value)
        }
        guard error == .success else {
            throw failure("macos_action_unknown", "Accessibility returned error \(error.rawValue) after the single effect attempt", unknown: true)
        }
        return ["application": beforeIdentity, "application_identity_observed_before_effect": true,
                "element_token": args["element_token"] ?? "",
                "effect": "accepted", "action_attempts": 1, "agent_confirmed": false,
                "automatic_retry": false, "before_revision": before["revision"] ?? "",
                "scope": "Public Accessibility API accepted one operation; application work and message delivery remain separately unconfirmed"]
    }
    static func handle(_ operation: String, arguments args: [String: Any]) async throws -> [String: Any]? {
        switch operation {
        case "system.permissions":
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            return ["actor_pid": Int(ProcessInfo.processInfo.processIdentifier),
                "accessibility_granted": AXIsProcessTrusted(),
                "post_events_granted": CGPreflightPostEventAccess(),
                "input_monitoring_granted": CGPreflightListenEventAccess(),
                "screen_capture_granted": CGPreflightScreenCaptureAccess(),
                "notification_authorization_status": settings.authorizationStatus.rawValue,
                "permission_requested": false, "effect": "none",
                "scope": "Current executing native worker only; every effect rechecks its own permissions"]
        case "system.permission_request":
            guard let resource = args["resource"] as? String else { throw failure("invalid_arguments", "Select one explicit OS permission resource") }
            let granted: Bool
            switch resource {
            case "accessibility":
                let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
                granted = AXIsProcessTrustedWithOptions(options)
            case "screen_capture": granted = CGRequestScreenCaptureAccess()
            case "notifications":
                var options: UNAuthorizationOptions = []
                if args["alert"] as? Bool == true { options.insert(.alert) }
                if args["sound"] as? Bool == true { options.insert(.sound) }
                if args["badge"] as? Bool == true { options.insert(.badge) }
                guard !options.isEmpty else { throw failure("invalid_arguments", "Select at least one notification authorization option") }
                do { granted = try await UNUserNotificationCenter.current().requestAuthorization(options: options) }
                catch { throw failure("macos_permission_request_unknown", "OS authorization request did not return a verifiable outcome", unknown: true) }
            default: throw failure("invalid_arguments", "Unsupported permission resource")
            }
            return ["resource": resource, "granted": granted, "permission_requested": true,
                "effect": "requested", "automatic_retry": false,
                "scope": "Explicit OS authorization request; the user and macOS determine the grant, and a process restart may be required"]
        case "accessibility.status":
            return ["granted": AXIsProcessTrusted(), "actor_pid": Int(ProcessInfo.processInfo.processIdentifier),
                "worker_generation": String(describing: SystemBridgeRuntime.generation),
                "permission_requested": false, "effect": "none",
                "scope": "Fresh permission of this executing native worker; every effect is checked again"]
        case "system.info":
            let process = ProcessInfo.processInfo
            var uid: uid_t = 0, gid: gid_t = 0
            let console = SCDynamicStoreCopyConsoleUser(nil, &uid, &gid) as String?
            return ["os_version": process.operatingSystemVersionString, "host_name": process.hostName,
                "processor_count": process.processorCount, "active_processor_count": process.activeProcessorCount,
                "physical_memory_bytes": process.physicalMemory, "uptime_seconds": process.systemUptime,
                "console_user": console ?? "", "console_uid": Int(uid), "uid": Int(getuid()),
                "scope": "Public system facts; no lock-state or TCC grant attestation", "effect": "none"]
        case "system.displays":
            return ["displays": try SystemBridge.displays(), "effect": "none", "scope": "Revision-bound display metadata; no captured pixels"]
        case "system.volumes":
            let keys: Set<URLResourceKey> = [.volumeNameKey, .volumeTotalCapacityKey, .volumeAvailableCapacityKey,
                .volumeIsReadOnlyKey, .volumeIsRemovableKey, .volumeIsLocalKey]
            let urls = FileManager.default.mountedVolumeURLs(includingResourceValuesForKeys: Array(keys), options: []) ?? []
            guard urls.count <= 256 else { throw failure("macos_resource_limit", "Mounted volume count exceeds the snapshot budget") }
            return ["volumes": try urls.map { url -> [String: Any] in
                let value = try url.resourceValues(forKeys: keys)
                return ["path": url.path, "name": value.volumeName ?? "", "total_bytes": value.volumeTotalCapacity ?? 0,
                    "available_bytes": value.volumeAvailableCapacity ?? 0, "read_only": value.volumeIsReadOnly ?? true,
                    "removable": value.volumeIsRemovable ?? false, "local": value.volumeIsLocal ?? false]
            }, "effect": "none"]
        case "apps.list":
            let all = try NSWorkspace.shared.runningApplications.filter { !$0.isTerminated && $0.launchDate != nil }
                .sorted { $0.processIdentifier < $1.processIdentifier }.map { try appIdentity($0) }
            return try applicationPage(all, args: args)
        case "apps.inspect":
            return ["application": try appIdentity(target(args)), "effect": "none"]
        case "apps.launch":
            guard let path = args["app_path"] as? String, path.hasPrefix("/"), path.hasSuffix(".app") else { throw failure("invalid_arguments", "Use an exact application bundle path") }
            let url = URL(fileURLWithPath: path).standardizedFileURL
            guard url.resolvingSymlinksInPath() == url, let bundle = Bundle(url: url), bundle.bundleURL == url,
                  !terminalBundles.contains(bundle.bundleIdentifier ?? "") else {
                throw failure("macos_terminal_route_required", "Use a non-symlink application bundle; terminals use session.open")
            }
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = true
            let app: NSRunningApplication = try await withCheckedThrowingContinuation { continuation in
                NSWorkspace.shared.openApplication(at: url, configuration: configuration) { app, error in
                    if let app = app { continuation.resume(returning: app) }
                    else { continuation.resume(throwing: failure("macos_launch_unknown", "Application launch did not produce an identity", unknown: true)) }
                }
            }
            do { return ["application": try appIdentity(app), "effect": "accepted", "automatic_retry": false] }
            catch { throw failure("macos_launch_unknown", "Launch occurred but its resulting application identity is unavailable", unknown: true) }
        case "apps.quit":
            let app = try target(args, mutating: true)
            guard app.terminate() else { throw failure("macos_quit_unknown", "Application did not accept termination", unknown: true) }
            return ["pid": Int(app.processIdentifier), "effect": "accepted", "termination_confirmed": app.isTerminated,
                "automatic_retry": false, "scope": "Graceful quit requested once; unsaved work may require the application's own decision"]
        case "accessibility.inspect": return try inspect(args)
        case "accessibility.action", "accessibility.set": return try mutate(operation, args)
        default: return try await SystemServices.handle(operation, arguments: args)
        }
    }
}

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
        if mutating { try protectLiveTerminalDescendants(app.processIdentifier) }
        return app
    }
    static func protectLiveTerminalDescendants(_ targetPID: pid_t) throws {
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
        if observation.records.contains(where: {
            $0.pid != targetPID && descendants.contains($0.pid)
                && (SystemServices.knownProtected($0) || $0.tty)
        }) {
            throw failure("macos_agent_route_required", "Application hosts an active terminal/agent process; its guarded session route is required")
        }
    }

    static func axGranted() throws {
        guard AXIsProcessTrusted() else {
            throw failure("macos_permission_denied", "This native worker has no current Accessibility grant; no request was made")
        }
    }
    static func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var result: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success else { return nil }
        return result
    }
    static func string(_ element: AXUIElement, _ name: String) -> String {
        attribute(element, name) as? String ?? ""
    }
    static func secure(_ element: AXUIElement) -> Bool {
        string(element, kAXRoleAttribute).contains("Secure") || string(element, kAXSubroleAttribute).contains("Secure")
    }
    static func summary(_ element: AXUIElement) throws -> [String: Any] {
        try observedSummary(prepare: {
                guard AXUIElementSetMessagingTimeout(element, 1.0) == .success else {
                    throw failure("macos_accessibility_unavailable", "Accessibility timeout could not be configured")
                }
            },
            read: { attribute(element, $0) }, actionNames: {
                var actions: CFArray?
                guard AXUIElementCopyActionNames(element, &actions) == .success else { return nil }
                return actions as? [String] ?? []
            })
    }
    static func observedSummary(prepare: () throws -> Void,
                                read: (String) -> CFTypeRef?,
                                actionNames: () -> [String]?) throws -> [String: Any] {
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
    static func remember(_ element: AXUIElement, app: NSRunningApplication) throws -> String {
        AXUIElementSetMessagingTimeout(element, 1.0)
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
    static func inspect(_ args: [String: Any]) throws -> [String: Any] {
        let app = try target(args)
        try axGranted()
        let root = args["element_token"] is String ? try element(args, app: app) : AXUIElementCreateApplication(app.processIdentifier)
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

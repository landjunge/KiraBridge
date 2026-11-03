import AppKit
import ApplicationServices

/// Observations of currently exported AX menus, never an execution or completeness claim about an app.
@MainActor
enum SystemShortcuts {
    struct NodeRead<Node> {
        let fields: [String: Any]
        let children: [Node]
        let reasons: [String]
    }
    struct Observation {
        let entries: [[String: Any]]
        let reasons: [String]
        let visited: Int
    }
    struct Snapshot {
        let principal: String, generation: String, revision: String
        let application: [String: Any], layout: [String: Any]
        let observation: Observation
        let created: Double, observedAt: Double
    }
    static var snapshots: [Snapshot] = []
    static func stableAppIdentity(_ application: [String: Any]) throws -> String {
        try SystemControl.hash(Dictionary(uniqueKeysWithValues:
            ["pid", "started_at", "bundle_id", "app_path", "executable"].map { ($0, application[$0] ?? NSNull()) }))
    }
    static func number(_ value: Any?) -> Int? {
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite,
              n.doubleValue >= Double(Int32.min), n.doubleValue <= Double(UInt32.max),
              n.doubleValue.rounded(.towardZero) == n.doubleValue else { return nil }
        return n.intValue
    }
    static func shortcut(_ fields: [String: Any]) -> [String: Any] {
        let char = fields["cmd_char"] as? String, key = number(fields["virtual_key"]), glyph = number(fields["glyph"])
        let raw = number(fields["modifier_mask"])
        var result: [String: Any] = ["cmd_char": char as Any? ?? NSNull(), "virtual_key": key as Any? ?? NSNull(),
            "glyph": glyph as Any? ?? NSNull(), "modifier_mask": raw as Any? ?? NSNull(),
            "candidate": NSNull(), "status": "none_observed", "verified": false]
        let positive = !(char ?? "").isEmpty || (key ?? 0) > 0 || (glyph ?? 0) > 0
        guard positive else { result["reason"] = "no_positive_shortcut_evidence"; return result }
        guard let raw = raw, raw >= 0, raw & ~15 == 0 else {
            result["status"] = "unavailable"; result["reason"] = "missing_or_unknown_modifier_bits"; return result
        }
        // AXMenuItemModifiers, not Carbon event modifiers or CGEventFlags. Command is implicit.
        var modifiers: [String] = raw & 8 == 0 ? ["command"] : []
        for (bit, name) in [(1, "shift"), (2, "option"), (4, "control")] where raw & bit != 0 { modifiers.append(name) }
        result["modifiers"] = modifiers
        var candidate: [String: Any]?
        if let char = char, char.unicodeScalars.count == 1, let scalar = char.unicodeScalars.first,
           !CharacterSet.controlCharacters.contains(scalar) { candidate = ["character": char] }
        else if (char ?? "").isEmpty, let key = key, key > 0 && key <= 127,
                SystemKeyboard.physicalKeys.contains(CGKeyCode(key)) { candidate = ["key_code": key] }
        result["status"] = "observed_unconfirmed"
        if let candidate = candidate {
            result["candidate"] = ["key": candidate, "modifiers": modifiers, "source": "ax_menu", "verification": "unconfirmed"]
        } else { result["reason"] = "glyph_or_key_representation_unresolved" }
        return result
    }
    static func scan<Node>(root: Node, now: @escaping () -> Double, deadline: Double? = nil,
                           equal: (Node, Node) -> Bool,
                           read: (Node, Int, () -> Bool) -> NodeRead<Node>) -> Observation {
        let deadline = deadline ?? now() + 3
        var stack: [(Node, [String], Int)] = [(root, [], 0)], seen: [Node] = []
        var entries: [[String: Any]] = [], reasons: Set<String> = []
        while let (node, parents, depth) = stack.popLast() {
            guard now() < deadline else { reasons.insert("time_limit"); break }
            guard seen.count < 2000 else { reasons.insert("node_limit"); break }
            if seen.contains(where: { equal($0, node) }) { reasons.insert("repeated_element"); continue }
            seen.append(node)
            let readBudget = max(0, 2000 - seen.count - stack.count)
            let observed = read(node, readBudget, { now() < deadline })
            let children = observed.children.prefix(readBudget)
            if observed.children.count > readBudget { reasons.insert("node_limit") }
            reasons.formUnion(observed.reasons)
            let name = observed.fields["name"] as? String
            let path = parents + ((name ?? "").isEmpty ? [] : [name!])
            if observed.fields["role"] as? String == "AXMenuItem" {
                entries.append(["name": name as Any? ?? NSNull(), "path": path,
                    "identifier": observed.fields["identifier"] ?? NSNull(),
                    "enabled": observed.fields["enabled"] ?? NSNull(), "shortcut": shortcut(observed.fields)])
            }
            if depth >= 12 {
                if !children.isEmpty { reasons.insert("depth_limit") }
            } else {
                for child in children.reversed() { stack.append((child, path, depth + 1)) }
            }
            if now() >= deadline { reasons.insert("time_limit"); break }
        }
        return Observation(entries: entries, reasons: reasons.sorted(), visited: seen.count)
    }
    static func readNode(_ node: AXUIElement, pid: pid_t, limit: Int, alive: () -> Bool) -> NodeRead<AXUIElement> {
        var fields: [String: Any] = [:], reasons: [String] = []
        guard alive(), AXUIElementSetMessagingTimeout(node, 0.2) == .success else {
            return NodeRead(fields: [:], children: [], reasons: ["message_timeout_unavailable"])
        }
        do { try SystemControl.checkElementOwner(node, pid: pid) }
        catch { return NodeRead(fields: [:], children: [], reasons: ["element_owner_unavailable"]) }
        func attribute(_ name: String) -> CFTypeRef? {
            guard alive() else { return nil }
            return SystemControl.attribute(node, name)
        }
        for (key, attr) in [("role", kAXRoleAttribute), ("name", kAXTitleAttribute),
                            ("identifier", kAXIdentifierAttribute), ("cmd_char", kAXMenuItemCmdCharAttribute)] {
            if let text = attribute(attr) as? String {
                fields[key] = String(decoding: text.utf8.prefix(256), as: UTF8.self)
                if text.utf8.count > 256 { reasons.append("attribute_truncated") }
            } else if key == "role" || key == "name" { reasons.append("menu_identity_attribute_unavailable") }
        }
        if let enabled = attribute(kAXEnabledAttribute) as? NSNumber, CFGetTypeID(enabled) == CFBooleanGetTypeID() {
            fields["enabled"] = enabled.boolValue
        } else { reasons.append("enabled_unavailable") }
        for (key, attr) in [("virtual_key", kAXMenuItemCmdVirtualKeyAttribute), ("glyph", kAXMenuItemCmdGlyphAttribute),
                            ("modifier_mask", kAXMenuItemCmdModifiersAttribute)] {
            if let value = number(attribute(attr)) { fields[key] = value }
        }
        guard alive() else { return NodeRead(fields: fields, children: [], reasons: reasons + ["time_limit"]) }
        var count: CFIndex = 0
        guard AXUIElementGetAttributeValueCount(node, kAXChildrenAttribute as CFString, &count) == .success, count >= 0 else {
            return NodeRead(fields: fields, children: [], reasons: reasons + ["children_unavailable"])
        }
        if count == 0 { return NodeRead(fields: fields, children: [], reasons: reasons) }
        let take = min(count, limit)
        if take < count { reasons.append("node_limit") }
        guard take > 0, alive() else { return NodeRead(fields: fields, children: [], reasons: reasons) }
        var children: CFArray?
        guard AXUIElementCopyAttributeValues(node, kAXChildrenAttribute as CFString, 0, take, &children) == .success,
              let result = children as? [AXUIElement], result.count <= take else {
            return NodeRead(fields: fields, children: [], reasons: reasons + ["children_unavailable"])
        }
        return NodeRead(fields: fields, children: result, reasons: reasons)
    }
    static func store(application: [String: Any], layout: [String: Any], observation: Observation,
                      principal: String, generation: String, now: Double, observedAt: Double) throws -> Snapshot {
        snapshots.removeAll { now - $0.created >= 15 }
        let revision = try SystemControl.hash(["application": application, "layout": layout,
            "principal": principal, "worker_generation": generation,
            "entries": observation.entries, "reasons": observation.reasons, "visited": observation.visited])
        let snapshot = Snapshot(principal: principal, generation: generation, revision: revision, application: application,
                                layout: layout, observation: observation, created: now, observedAt: observedAt)
        snapshots.removeAll { $0.revision == revision && $0.principal == principal }
        snapshots.append(snapshot)
        if snapshots.count > 4 { snapshots.removeFirst(snapshots.count - 4) }
        return snapshot
    }
    static func page(revision: String, application: [String: Any], layout: [String: Any], principal: String,
                     generation: String, offset: Int, limit: Int, now: Double, cached: Bool) throws -> [String: Any] {
        snapshots.removeAll { now - $0.created >= 15 }
        guard let snapshot = snapshots.first(where: { $0.revision == revision
            && $0.principal.utf8.elementsEqual(principal.utf8) && $0.generation == generation }),
              try stableAppIdentity(snapshot.application) == stableAppIdentity(application),
              try SystemControl.hash(snapshot.layout) == SystemControl.hash(layout) else {
            throw SystemControl.failure("keyboard_shortcuts_refresh_required", "Menu snapshot expired or its owner/app/layout/worker changed")
        }
        let observation = snapshot.observation
        guard offset <= observation.entries.count else { throw SystemControl.failure("invalid_cursor", "Menu page exceeds observed entries") }
        var result: [String: Any] = ["entries": Array(observation.entries.dropFirst(offset).prefix(limit)),
            "revision": snapshot.revision, "offset": offset, "total": observation.entries.count,
            "eof": offset + limit >= observation.entries.count, "cached": cached, "observed_at": snapshot.observedAt,
            "coverage": observation.visited == 0 ? "unavailable" : observation.reasons.isEmpty ? "complete" : "partial",
            "reasons": observation.reasons, "visited_nodes": observation.visited, "application": snapshot.application,
            "layout": snapshot.layout, "language": "unknown", "scope": "observed_ax_menu_snapshot_only",
            "all_app_shortcuts_enumerated": false, "effect": "none", "input_attempted": false, "permission_requested": false]
        if offset + limit < observation.entries.count { result["next_offset"] = offset + limit }
        return result
    }
    static func handle(_ operation: String, arguments args: [String: Any]) throws -> [String: Any]? {
        guard operation == "keyboard.shortcuts.discover" else { return nil }
        let app = try SystemControl.target(args)
        try SystemControl.axGranted()
        let application = try SystemControl.appIdentity(app), layout = try SystemKeyboard.inputSource()
        let limit = try SystemKeyboard.stageInteger(["value": args["limit"] ?? 100], "value", max: 250)
        let offset = try SystemKeyboard.stageInteger(["value": args["offset"] ?? 0], "value", max: 2000)
        try SystemKeyboard.require(limit > 0, "Menu page limit must be positive")
        var revision = args["expected_revision"] as? String
        if revision == nil {
            try SystemKeyboard.require(offset == 0, "A menu continuation requires its snapshot revision")
            let root = AXUIElementCreateApplication(app.processIdentifier)
            var menu: CFTypeRef?
            let start = ProcessInfo.processInfo.systemUptime
            let status = AXUIElementSetMessagingTimeout(root, 0.2) == .success
                ? AXUIElementCopyAttributeValue(root, kAXMenuBarAttribute as CFString, &menu) : .cannotComplete
            let observation: Observation
            if status == .success, let menu = menu, CFGetTypeID(menu) == AXUIElementGetTypeID() {
                observation = scan(root: unsafeBitCast(menu, to: AXUIElement.self), now: { ProcessInfo.processInfo.systemUptime }, deadline: start + 3,
                    equal: { CFEqual($0, $1) }, read: { readNode($0, pid: app.processIdentifier, limit: $1, alive: $2) })
            } else { observation = Observation(entries: [], reasons: ["menu_bar_unavailable"], visited: 0) }
            let latestApp = try SystemControl.target(args)
            try SystemControl.axGranted()
            guard try stableAppIdentity(application) == stableAppIdentity(SystemControl.appIdentity(latestApp)) else {
                throw SystemControl.failure("keyboard_shortcuts_refresh_required", "Application identity changed during menu observation")
            }
            let latestLayout = try SystemKeyboard.inputSource()
            guard try SystemControl.hash(layout) == SystemControl.hash(latestLayout) else {
                throw SystemControl.failure("keyboard_shortcuts_refresh_required", "Layout changed during menu observation")
            }
            revision = try store(application: application, layout: layout, observation: observation,
                principal: SystemBridgeRuntime.principal, generation: SystemBridgeRuntime.generation,
                now: start, observedAt: Date().timeIntervalSince1970).revision
        }
        return try page(revision: revision!, application: application, layout: layout,
            principal: SystemBridgeRuntime.principal, generation: SystemBridgeRuntime.generation,
            offset: offset, limit: limit, now: ProcessInfo.processInfo.systemUptime, cached: args["expected_revision"] != nil)
    }
}

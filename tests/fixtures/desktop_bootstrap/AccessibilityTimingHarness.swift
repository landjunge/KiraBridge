import AppKit
import ApplicationServices
import Darwin

/// One owned background fixture, or read-only timing of that exact fixture.
/// Never activates an application, posts input or requests OS permissions.
@main
struct AccessibilityTimingHarness {
    static let fixtureID = "de.netzwerkpunkt.kirabridge.owned-ax-timing"
    @MainActor static func foreground() -> Int {
        Int(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0)
    }
    @MainActor static func ownedApps() -> [NSRunningApplication] {
        let ownURL = Bundle.main.bundleURL.resolvingSymlinksInPath()
        return NSWorkspace.shared.runningApplications.filter {
            $0.processIdentifier != getpid() && !$0.isTerminated && $0.bundleIdentifier == fixtureID
                && $0.bundleURL?.resolvingSymlinksInPath() == ownURL
        }
    }
    static func emit(_ object: [String: Any]) {
        let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
    static func cpu() -> Double {
        var usage = rusage()
        getrusage(RUSAGE_SELF, &usage)
        return Double(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec)
            + Double(usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1_000_000
    }
    @MainActor static func main() {
        let args = CommandLine.arguments
        guard args.count > 1 else { emit(["error": "missing_mode"]); return }
        if args[1] == "--probe" {
            emit(["trusted": AXIsProcessTrusted(), "permission_requested": false,
                  "foreground_pid": foreground(), "owned_other_pids": ownedApps().map { Int($0.processIdentifier) }])
            return
        }
        if args[1] == "--owned-status" {
            emit(["applications": ownedApps().map { app -> [String: Any] in
                ["pid": Int(app.processIdentifier), "started_at": app.launchDate.map { $0.timeIntervalSince1970 as Any } ?? NSNull(),
                 "active": app.isActive]
            }, "foreground_pid": foreground()])
            return
        }
        if args[1] == "--launch", args.count == 3 {
            let ownURL = Bundle.main.bundleURL.resolvingSymlinksInPath()
            guard ownedApps().isEmpty,
                  URL(fileURLWithPath: args[2]).deletingLastPathComponent().resolvingSymlinksInPath() == ownURL.deletingLastPathComponent() else {
                emit(["launched": false, "error": "fixture_ownership_conflict"]); return
            }
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = false
            configuration.addsToRecentItems = false
            configuration.hidesOthers = false
            configuration.promptsUserIfNeeded = false
            configuration.createsNewApplicationInstance = true
            configuration.allowsRunningApplicationSubstitution = false
            configuration.arguments = ["--provider", args[2]]
            let completed = DispatchSemaphore(value: 0)
            let box = LaunchResult()
            NSWorkspace.shared.openApplication(at: ownURL, configuration: configuration) { app, error in
                box.lock.lock(); box.app = app; box.error = error; box.lock.unlock()
                completed.signal()
            }
            guard completed.wait(timeout: .now() + 12) == .success else {
                emit(["launched": false, "error": "fixture_launch_timeout"]); return
            }
            box.lock.lock(); let app = box.app; let error = box.error; box.lock.unlock()
            guard let app, let start = app.launchDate, app.bundleIdentifier == fixtureID,
                  app.bundleURL?.resolvingSymlinksInPath() == ownURL else {
                emit(["launched": false, "error": error?.localizedDescription ?? "fixture_launch_identity_unavailable"]); return
            }
            emit(["launched": true, "pid": Int(app.processIdentifier), "started_at": start.timeIntervalSince1970,
                  "active": app.isActive, "foreground_pid": foreground(), "activation_requested": false])
            return
        }
        if args[1] == "--provider", args.count == 3 {
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            let delegate = FixtureDelegate(ready: args[2])
            app.delegate = delegate
            withExtendedLifetime(delegate) { app.run() }
            return
        }
        if args[1] == "--stop", args.count == 4, let pid = Int32(args[2]), let start = Double(args[3]) {
            guard let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated else {
                emit(["signal_sent": false, "already_absent": true]); return
            }
            guard let actualStart = app.launchDate else { emit(["error": "fixture_identity_unknown"]); return }
            if actualStart.timeIntervalSince1970 != start { emit(["signal_sent": false, "already_absent": true]); return }
            guard pid != getpid(), app.bundleIdentifier == fixtureID,
                  app.bundleURL?.resolvingSymlinksInPath() == Bundle.main.bundleURL.resolvingSymlinksInPath() else {
                emit(["error": "fixture_ownership_conflict"]); return
            }
            let status = Darwin.kill(pid, SIGTERM)
            emit(["signal_sent": status == 0, "errno": status == 0 ? 0 : errno])
            return
        }
        if args[1] == "--absent", args.count == 4, let pid = Int32(args[2]),
           let start = Double(args[3]) {
            let app = NSRunningApplication(processIdentifier: pid)
            if let app, !app.isTerminated {
                guard let observedStart = app.launchDate else {
                    emit(["owned_provider_absent": false, "identity_unknown": true]); return
                }
                emit(["owned_provider_absent": observedStart.timeIntervalSince1970 != start,
                      "foreground_pid": foreground()])
            } else {
                emit(["owned_provider_absent": true, "foreground_pid": foreground()])
            }
            return
        }
        guard args[1] == "--measure", args.count == 5, let pid = Int32(args[2]),
              let start = Double(args[3]), let rounds = Int(args[4]), (10...50).contains(rounds) else {
            emit(["error": "invalid_mode"]); return
        }
        do {
            guard AXIsProcessTrusted() else {
                throw SystemControl.failure("macos_permission_denied", "No existing AX grant")
            }
            let app = try SystemControl.target(["pid": Int(pid), "expected_started_at": start])
            guard app.bundleIdentifier == fixtureID, !app.isActive else {
                throw SystemControl.failure("fixture_target_changed", "Owned fixture identity/focus changed")
            }
            let root = AXUIElementCreateApplication(pid)
            var queue = [root], seen = Set<SystemControl.TreeReference>(), targets: [AXUIElement] = []
            while !queue.isEmpty && seen.count < 256 && targets.count < 12 {
                let node = queue.removeFirst()
                guard seen.insert(SystemControl.TreeReference(element: node)).inserted else { continue }
                try SystemControl.checkElementOwner(node, pid: pid)
                AXUIElementSetMessagingTimeout(node, 0.2)
                var role: CFTypeRef?
                guard AXUIElementCopyAttributeValue(node, kAXRoleAttribute as CFString, &role) == .success else {
                    throw SystemControl.failure("fixture_unobservable", "Owned fixture role unavailable")
                }
                if role as? String == kAXButtonRole {
                    var identifier: CFTypeRef?
                    if AXUIElementCopyAttributeValue(node, kAXIdentifierAttribute as CFString, &identifier) == .success,
                       (identifier as? String)?.hasPrefix("owned-button-") == true {
                        targets.append(node)
                    }
                }
                var children: CFTypeRef?
                let status = AXUIElementCopyAttributeValue(node, kAXChildrenAttribute as CFString, &children)
                if status == .success { queue += try SystemControl.treeChildren(children) }
                else if status != .attributeUnsupported && status != .noValue {
                    throw SystemControl.failure("fixture_unobservable", "Owned fixture children unavailable")
                }
            }
            guard targets.count == 12 else {
                throw SystemControl.failure("fixture_incomplete", "Expected owned button targets")
            }
            var supportChecks: [[String: Any]] = []
            for target in targets {
                try SystemControl.prepareTreeElement(target, deadline: SystemControl.treeNow() + 3)
                var raw: CFArray?
                let first = AXUIElementCopyMultipleAttributeValues(target,
                    SystemControl.treeClassificationAttributes as CFArray, [], &raw)
                guard first == .success else {
                    throw SystemControl.failure("fixture_batch_not_supported", "Own provider classification batch unsupported")
                }
                let classification = try SystemControl.treeBatchAttributes(
                    SystemControl.treeClassificationAttributes, status: first, raw: raw)
                let role = classification[kAXRoleAttribute] as? String ?? ""
                let subrole = classification[kAXSubroleAttribute] as? String ?? ""
                guard !role.isEmpty else { throw SystemControl.failure("fixture_unobservable", "Own role absent") }
                let secure = role.contains("Secure") || subrole.contains("Secure")
                let names = Array(SystemControl.treeMetadataAttributes.prefix(3))
                    + (secure ? [] : [kAXValueAttribute]) + Array(SystemControl.treeMetadataAttributes.dropFirst(3))
                raw = nil
                let second = AXUIElementCopyMultipleAttributeValues(target, names as CFArray, [], &raw)
                guard second == .success else {
                    throw SystemControl.failure("fixture_batch_not_supported", "Own provider metadata batch unsupported")
                }
                _ = try SystemControl.treeBatchAttributes(names, status: second, raw: raw)
                supportChecks.append(["classification_status": first.rawValue, "metadata_status": second.rawValue])
            }
            var samples: [[String: Any]] = [], hashes = Set<String>()
            for round in 0..<rounds {
                guard !app.isTerminated, app.launchDate?.timeIntervalSince1970 == start, !app.isActive else {
                    throw SystemControl.failure("fixture_target_changed", "Owned fixture identity/focus changed")
                }
                var values: [String: [[String: Any]]] = [:], timings: [String: [String: Double]] = [:]
                let order = round % 2 == 0 ? ["individual", "batched"] : ["batched", "individual"]
                for mode in order {
                    let wall = ProcessInfo.processInfo.systemUptime, processCPU = cpu()
                    var observations: [[String: Any]] = []
                    for target in targets {
                        try SystemControl.checkElementOwner(target, pid: pid)
                        let deadline = SystemControl.treeNow() + 3
                        let observation: [String: Any]
                        if mode == "individual" {
                            observation = try SystemControl.individualTreeSummary(target, deadline: deadline)
                        } else {
                            observation = try SystemControl.treeSummary(target, deadline: deadline)
                        }
                        observations.append(observation)
                    }
                    timings[mode] = ["wall_ms": (ProcessInfo.processInfo.systemUptime - wall) * 1000,
                                     "cpu_ms": (cpu() - processCPU) * 1000]
                    values[mode] = observations
                }
                let first = try JSONSerialization.data(withJSONObject: values["individual"]!, options: [.sortedKeys])
                let second = try JSONSerialization.data(withJSONObject: values["batched"]!, options: [.sortedKeys])
                guard first == second else {
                    throw SystemControl.failure("fixture_result_changed", "Own baseline and candidate metadata differ")
                }
                hashes.insert(try SystemControl.hash(values["individual"]!))
                samples.append(["round": round, "order": order, "timings": timings,
                                "results_identical": true])
            }
            guard !app.isActive, foreground() != Int(pid), !app.isTerminated else {
                throw SystemControl.failure("fixture_target_changed", "Own fixture focus/lifecycle changed at completion")
            }
            emit(["passed": true, "scope": "real AX reads of the owned background fixture only",
                  "nodes_per_round": targets.count, "rounds": rounds, "samples": samples,
                  "batch_support_preflight": supportChecks,
                  "preflight_scope": "Both batches on every target before timing; timed fallback is not separately instrumented",
                  "result_hashes": hashes.sorted(), "permission_requested": false,
                  "input_posts": 0, "foreground_pid": foreground(), "fixture_active": app.isActive])
        } catch let error as SystemBridgeFailure { emit(["passed": false, "error": error.code]) }
        catch { emit(["passed": false, "error": String(describing: error)]) }
    }
}

final class LaunchResult: @unchecked Sendable {
    let lock = NSLock()
    var app: NSRunningApplication?
    var error: Error?
}

@MainActor
final class FixtureDelegate: NSObject, NSApplicationDelegate {
    let ready: String
    var window: NSWindow?
    init(ready: String) { self.ready = ready }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let window = NSWindow(contentRect: NSRect(x: 40, y: 40, width: 320, height: 460),
            styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "KiraBridge owned timing fixture"
        window.isReleasedWhenClosed = false
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.spacing = 2
        stack.translatesAutoresizingMaskIntoConstraints = false
        for index in 0..<12 {
            let button = NSButton(title: "Owned fixture button \(index)", target: nil, action: nil)
            button.setAccessibilityIdentifier("owned-button-\(index)")
            stack.addArrangedSubview(button)
        }
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: window.contentView!.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: window.contentView!.centerYAnchor)
        ])
        self.window = window
        // Does not activate this accessory application or make the window key.
        window.orderBack(nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            guard let start = NSRunningApplication.current.launchDate else {
                let data = try! JSONSerialization.data(withJSONObject: ["error": "fixture_launch_date_unavailable", "pid": Int(getpid())])
                try! data.write(to: URL(fileURLWithPath: self.ready), options: [.atomic])
                NSApp.terminate(nil); return
            }
            let data = try! JSONSerialization.data(withJSONObject: [
                "pid": Int(getpid()), "started_at": start.timeIntervalSince1970,
                "window_count": NSApp.windows.count,
                "active": NSRunningApplication.current.isActive,
                "foreground_pid": AccessibilityTimingHarness.foreground()
            ], options: [.sortedKeys])
            try! data.write(to: URL(fileURLWithPath: self.ready), options: [.atomic])
        }
    }
}

import Foundation
import Darwin

struct DesktopBootstrapFailure: LocalizedError {
    enum Kind: String { case timeout, outputLimit = "output_limit", processFailed = "process_failed", readFailed = "read_failed", cleanupUnknown = "cleanup_unknown" }
    let kind: Kind
    let cleanupConfirmed: Bool
    var errorDescription: String? {
        switch kind {
        case .timeout: return "Der lokale Starter hat zu lange gebraucht. Bitte versuche es erneut."
        case .outputLimit: return "Die Antwort des lokalen Starters ist zu groß."
        case .processFailed: return "Der lokale Starter konnte KiraBridge nicht öffnen."
        case .readFailed: return "Die Antwort des lokalen Starters konnte nicht gelesen werden."
        case .cleanupUnknown: return "Der lokale Starter konnte nicht zuverlässig beendet werden. Ein erneuter Start ist vorerst gesperrt."
        }
    }
}

enum DesktopBootstrap {
    static func runCapture(executable: URL, arguments: [String], environment: [String: String],
                           timeout: TimeInterval = 60, maxStdoutBytes: Int = 65536,
                           maxStderrBytes: Int = 65536) throws -> (status: Int32, data: Data) {
        guard timeout.isFinite, timeout > 0, timeout <= 60,
              maxStdoutBytes > 0, maxStdoutBytes <= 1024 * 1024,
              maxStderrBytes > 0, maxStderrBytes <= 1024 * 1024 else {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        let task = Process()
        task.executableURL = executable
        task.arguments = arguments
        task.environment = environment
        task.standardInput = FileHandle.nullDevice
        let streams = [Pipe(), Pipe()]
        task.standardOutput = streams[0]
        task.standardError = streams[1]
        defer {
            for stream in streams {
                try? stream.fileHandleForReading.close()
                try? stream.fileHandleForWriting.close()
            }
        }
        let now = { Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000 }
        let deadline = now() + timeout
        do { try task.run() }
        catch { throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true) }
        for stream in streams { try? stream.fileHandleForWriting.close() }
        let descriptors = streams.map { $0.fileHandleForReading.fileDescriptor }
        var ended = [false, false], counts = [0, 0]
        let limits = [maxStdoutBytes, maxStderrBytes]
        var data = Data(), buffer = [UInt8](repeating: 0, count: 4096)
        var failure: DesktopBootstrapFailure.Kind?
        var terminationPhase = 0, phaseDeadline = deadline
        while true {
            let instant = now()
            if failure == nil && instant >= deadline { failure = .timeout }
            if let failure {
                if !task.isRunning {
                    task.waitUntilExit()
                    throw DesktopBootstrapFailure(kind: failure, cleanupConfirmed: true)
                }
                if terminationPhase == 0 {
                    task.terminate()  // This exact child only; never a process group.
                    terminationPhase = 1
                    phaseDeadline = instant + 0.25
                } else if instant >= phaseDeadline {
                    if terminationPhase == 1 {
                        if task.isRunning && task.processIdentifier > 1 {
                            _ = Darwin.kill(task.processIdentifier, SIGKILL)
                        }
                        terminationPhase = 2
                        phaseDeadline = instant + 0.25
                    } else {
                        throw DesktopBootstrapFailure(kind: .cleanupUnknown, cleanupConfirmed: false)
                    }
                }
            }
            if !task.isRunning && ended.allSatisfy({ $0 }) {
                task.waitUntilExit()
                return (task.terminationStatus, data)
            }
            var ready = descriptors.enumerated().map { index, fd in
                pollfd(fd: ended[index] ? -1 : fd,
                       events: Int16(POLLIN | POLLHUP | POLLERR), revents: 0)
            }
            let status = ready.withUnsafeMutableBufferPointer { pointer in
                Darwin.poll(pointer.baseAddress, nfds_t(pointer.count), 25)
            }
            if status < 0 {
                if errno != EINTR { failure = failure ?? .readFailed }
                continue
            }
            for index in ready.indices where ready[index].revents != 0 {
                let count = buffer.withUnsafeMutableBytes { pointer in
                    Darwin.read(descriptors[index], pointer.baseAddress, pointer.count)
                }
                if count < 0 {
                    if errno != EINTR { failure = failure ?? .readFailed }
                } else if count == 0 {
                    ended[index] = true
                } else {
                    let remaining = max(0, limits[index] - counts[index])
                    if index == 0 && failure == nil {
                        data.append(contentsOf: buffer.prefix(min(count, remaining)))
                    }
                    counts[index] += min(count, remaining + 1)
                    if counts[index] > limits[index] { failure = failure ?? .outputLimit }
                }
            }
        }
    }

    static func run(executable: URL, arguments: [String], environment: [String: String],
                    timeout: TimeInterval = 60, maxStdoutBytes: Int = 65536,
                    maxStderrBytes: Int = 65536) throws -> Data {
        let (status, data) = try runCapture(executable: executable, arguments: arguments,
            environment: environment, timeout: timeout, maxStdoutBytes: maxStdoutBytes,
            maxStderrBytes: maxStderrBytes)
        guard status == 0 else {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        return data
    }

    /// Stop exactly this owned child; never a process group. Returns true only
    /// when the owned child is confirmed absent, so a caller can distinguish a
    /// confirmed cleanup from an unknown one.
    static func stop(_ task: Process) -> Bool {
        if task.isRunning { task.terminate() }
        let now = { Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000 }
        var deadline = now() + 0.5
        while task.isRunning && now() < deadline { usleep(20_000) }
        if task.isRunning && task.processIdentifier > 1 {
            _ = Darwin.kill(task.processIdentifier, SIGKILL)
            deadline = now() + 0.5
            while task.isRunning && now() < deadline { usleep(20_000) }
        }
        return !task.isRunning
    }

    /// Start an explicitly isolated Live console as this app's owned child.
    ///
    /// The child prints exactly one receipt line and keeps serving. Only that
    /// line is used; stderr is drained and discarded in the background so a full
    /// pipe can never block the server. On any failure the owned child is
    /// stopped and no production fallback is attempted.
    static func startIsolated(executable: URL, arguments: [String], environment: [String: String],
                              privateDirectory: URL, timeout: TimeInterval = 30,
                              maxStdoutBytes: Int = 65536,
                              owned: ((Process) -> Bool)? = nil) throws -> DesktopIsolatedServer {
        guard timeout.isFinite, timeout > 0, timeout <= 60,
              maxStdoutBytes > 0, maxStdoutBytes <= 1024 * 1024 else {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        let task = Process()
        task.executableURL = executable
        task.arguments = arguments
        task.environment = environment
        task.standardInput = FileHandle.nullDevice
        let output = Pipe(), errors = Pipe()
        task.standardOutput = output
        task.standardError = errors
        do { try task.run() } catch {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        // The caller keeps the owned handle immediately, so even an uncertain
        // cleanup leaves it stoppable and never starts a second child. If the
        // owner refuses the child (sealed holder), stop it here so it can never
        // become an untracked process.
        if let owned, !owned(task) {
            guard DesktopBootstrap.stop(task) else {
                throw DesktopBootstrapFailure(kind: .cleanupUnknown, cleanupConfirmed: false)
            }
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        DispatchQueue.global().async {
            // Keep draining for the whole child lifetime so a full pipe can
            // never block the server; the bytes are discarded, not stored.
            while true {
                guard let chunk = try? errors.fileHandleForReading.read(upToCount: 8192),
                      !chunk.isEmpty else { return }
            }
        }
        let now = { Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000 }
        let deadline = now() + timeout
        let descriptor = output.fileHandleForReading.fileDescriptor
        var data = Data(), buffer = [UInt8](repeating: 0, count: 4096)
        // A cleanup is only "confirmed" when the owned child is verifiably gone;
        // otherwise the failure is reported as unknown and no retry is implied.
        func failure(_ kind: DesktopBootstrapFailure.Kind) -> DesktopBootstrapFailure {
            guard DesktopBootstrap.stop(task) else {
                return DesktopBootstrapFailure(kind: .cleanupUnknown, cleanupConfirmed: false)
            }
            return DesktopBootstrapFailure(kind: kind, cleanupConfirmed: true)
        }
        while true {
            if now() >= deadline { throw failure(.timeout) }
            var ready = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
            let status = withUnsafeMutablePointer(to: &ready) { pointer in
                Darwin.poll(pointer, 1, 50)
            }
            if status < 0 {
                if errno == EINTR { continue }
                throw failure(.readFailed)
            }
            if status == 0 { continue }
            let count = buffer.withUnsafeMutableBytes { pointer in
                Darwin.read(descriptor, pointer.baseAddress, pointer.count)
            }
            if count <= 0 {
                // EOF without a receipt. A child that is still running is
                // stopped with a bounded wait; never wait for it to exit by
                // itself, and never signal anything but this owned child.
                if task.isRunning {
                    guard DesktopBootstrap.stop(task) else {
                        throw DesktopBootstrapFailure(
                            kind: .cleanupUnknown, cleanupConfirmed: false)
                    }
                }
                if !task.isRunning { task.waitUntilExit() }
                throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
            }
            data.append(contentsOf: buffer.prefix(count))
            if data.count > maxStdoutBytes { throw failure(.outputLimit) }
            if let newline = data.firstIndex(of: 0x0A) {
                data = data.prefix(upTo: newline)
                break
            }
        }
        guard let receipt = try? DesktopIsolatedReceipt(
            data: Data(data), directory: privateDirectory) else {
            throw failure(.readFailed)
        }
        return DesktopIsolatedServer(receipt: receipt, process: task)
    }

    /// Narrow positive allowlist for the isolated child: no inherited bridge or
    /// provider tokens, no production config pointer, only the fixed source path.
    static let isolatedEnvironmentKeys = [
        "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME",
        "SHELL",
    ]

    static func isolatedEnvironment(root: URL, from source: [String: String]) -> [String: String] {
        var environment: [String: String] = [:]
        for key in isolatedEnvironmentKeys {
            if let value = source[key] { environment[key] = value }
        }
        environment["PYTHONPATH"] = root.standardizedFileURL.path + "/src"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment
    }
}

struct DesktopIsolatedServer {
    let receipt: DesktopIsolatedReceipt
    let process: Process
}

/// Thread-safe handle to the one isolated child this app owns. It is adopted as
/// soon as the child starts, so an uncertain cleanup never loses the handle and
/// the app never starts a second child.
final class DesktopOwnedChild {
    typealias Stopper = (Process) -> Bool

    private let lock = NSLock()
    private let stopper: Stopper
    private var process: Process?
    private var sealed = false

    init(stopper: @escaping Stopper = DesktopBootstrap.stop) {
        self.stopper = stopper
    }

    /// Adopt the owned process. Returns false when the holder is sealed or
    /// already holds a process; the caller must then stop the child itself.
    @discardableResult
    func adopt(_ process: Process) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !sealed, self.process == nil else { return false }
        self.process = process
        return true
    }

    /// Stop the one owned child. The handle is kept — and adoption stays
    /// sealed — until the child is confirmed absent, so a failed stop reports
    /// unknown and can be retried instead of looking absent.
    @discardableResult
    func stop() -> Bool {
        lock.lock()
        sealed = true
        let owned = process
        lock.unlock()
        guard let owned else { return true }
        let confirmed = stopper(owned)
        if confirmed {
            lock.lock()
            process = nil
            lock.unlock()
        }
        return confirmed
    }

    /// Close the adoption fence without touching the child (used when a start
    /// failed uncertainly so a later start cannot adopt an untracked child).
    func seal() {
        lock.lock()
        sealed = true
        lock.unlock()
    }

    var hasHandle: Bool {
        lock.lock()
        defer { lock.unlock() }
        return process != nil
    }

    var isRunning: Bool {
        lock.lock()
        defer { lock.unlock() }
        return process?.isRunning ?? false
    }
}

enum DesktopNavigationDecision: String { case allow, external, deny }

struct DesktopLoginReceipt {
    let loginFile: URL
    static func isValidPath(_ path: String) -> Bool {
        path.hasPrefix("/") && !path.utf8.contains(0) && path.utf8.count <= 4096
            && path.hasSuffix("/approval-login.html")
    }
    init(data: Data) throws {
        guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let path = value["login_file"] as? String,
              Self.isValidPath(path) else {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        loginFile = URL(fileURLWithPath: path)
    }
    init(loginFile: URL) { self.loginFile = loginFile }
}

/// A receipt from an explicitly isolated Live instance. The origin is the exact
/// loopback origin that instance bound; the login file must stay inside its
/// private directory, and the production console port is never accepted.
struct DesktopIsolatedReceipt {
    let origin: URL
    let loginFile: URL
    static let productionPorts: Set<Int> = [8765, 8766, 8767]
    static func isValidOrigin(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "http", url.host == "127.0.0.1",
              url.user == nil, url.password == nil,
              let port = url.port, port >= 1024, port <= 65535,
              !productionPorts.contains(port),
              url.path.isEmpty || url.path == "/",
              url.query == nil, url.fragment == nil else { return false }
        return true
    }
    init(data: Data, directory: URL) throws {
        guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              value["isolated"] as? Bool == true,
              let rawOrigin = value["origin"] as? String,
              let parsed = URL(string: rawOrigin), Self.isValidOrigin(parsed),
              let path = value["login_file"] as? String,
              DesktopLoginReceipt.isValidPath(path) else {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        // Compare canonical forms on both sides. The owned base is canonicalised
        // before it is created, and resolving symlinks here rejects a login path
        // that escapes through a symlink; there is no general path allowlist.
        let owned = directory.resolvingSymlinksInPath().standardizedFileURL
        let login = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
        guard login.lastPathComponent == "approval-login.html",
              login.deletingLastPathComponent().standardizedFileURL.path == owned.path else {
            throw DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
        }
        origin = URL(string: "http://127.0.0.1:\(parsed.port!)")!
        loginFile = login
    }
}

struct DesktopNavigationPolicy {
    private(set) var loginFile: URL?
    private(set) var consolePort: Int
    /// The production default stays 8766. An explicitly isolated instance passes
    /// the exact loopback port it bound; no aliases or other ports are allowed.
    init(consolePort: Int = 8766) { self.consolePort = consolePort }
    mutating func authorizeLogin(_ receipt: DesktopLoginReceipt) { loginFile = receipt.loginFile }
    func allowsLoginPath(_ path: String) -> Bool { loginFile != nil && path == loginFile?.path }
    private func isConsoleOrigin(_ url: URL) -> Bool {
        // Must match the console origin exactly; loopback aliases are other origins.
        url.scheme?.lowercased() == "http" && url.host == "127.0.0.1"
            && url.port == consolePort
            && url.user == nil && url.password == nil
    }
    func decision(
        for url: URL?, activated: Bool, isolated: Bool = false
    ) -> DesktopNavigationDecision {
        guard let url, url.user == nil, url.password == nil else { return .deny }
        if url.isFileURL {
            let local = url.host == nil || url.host == "" || url.host == "localhost"
            return local && url.port == nil && url.query == nil && url.path == loginFile?.path
                ? .allow : .deny
        }
        if isConsoleOrigin(url) { return .allow }
        if activated, [
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
        ].contains(url.absoluteString) { return isolated ? .deny : .external }
        if activated, ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
           let host = url.host, !host.isEmpty { return isolated ? .deny : .external }
        return .deny
    }
    func allowsPopup(_ url: URL?) -> Bool {
        guard let url else { return false }
        return isConsoleOrigin(url) && url.path == "/protocol"
    }

    /// The console root, which the login redirect targets; live mode replaces it.
    func isConsoleRoot(_ url: URL) -> Bool {
        isConsoleOrigin(url) && url.path == "/"
    }
}

final class DesktopOpenRequests {
    private var pending: [(String, (Bool) -> Void)] = []
    func submit(_ files: [String], policy: DesktopNavigationPolicy, ready: Bool,
                load: (String) -> Void, reply: @escaping (Bool) -> Void) {
        guard files.count == 1, let path = files.first,
              DesktopLoginReceipt.isValidPath(path) else { reply(false); return }
        if !ready || policy.loginFile == nil {
            guard pending.count < 16 else { reply(false); return }
            pending.append((path, reply))
            return
        }
        guard policy.allowsLoginPath(path) else { reply(false); return }
        load(path)
        reply(true)
    }
    func resolve(_ policy: DesktopNavigationPolicy, ready: Bool) {
        guard ready, policy.loginFile != nil else { return }
        let waiting = pending
        pending.removeAll(keepingCapacity: true)
        // Bootstrap already requested its one verified login load; do not reload its one-use ticket.
        for (path, reply) in waiting { reply(policy.allowsLoginPath(path)) }
    }
    func failAll() {
        let waiting = pending
        pending.removeAll(keepingCapacity: true)
        for (_, reply) in waiting { reply(false) }
    }
}

// MARK: Desktop UI
import Cocoa
import WebKit

final class KiraBridgeApp: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    /// The full release version (for example 0.8.0rc41); the bundle short version is numeric only.
    @objc func showAbout(_ sender: Any?) {
        let release = Bundle.main.object(forInfoDictionaryKey: "KiraBridgeVersion") as? String
        var options: [NSApplication.AboutPanelOptionKey: Any] = [.version: ""]
        if let release { options[.applicationVersion] = release }
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: options)
    }

    var windows: [NSWindow] = []
    var mainView: WKWebView!
    var bootstrapInProgress = false
    var bootstrapCleanupUnknown = false
    var liveMode = false
    var isolatedMode = false
    let isolatedChild = DesktopOwnedChild()
    var familySwitchInProgress = false
    var familySwitchUnknown = false
    var mainNavigationGeneration: UInt64 = 0
    var navigationPolicy = DesktopNavigationPolicy()
    let openRequests = DesktopOpenRequests()

    /// Catalog-ID-only bridge. The renderer passes exactly one catalog ID and
    /// receives one of focused/failed/uncertain/missing; it never passes
    /// a URL, argv, PID or shell text.
    private static let familyBridgeScript = """
    (() => {
      window.__kbFamilyCallbacks = Object.create(null);
      window.__kbFamilySwitch = (appId) => new Promise((resolve) => {
        const id = (typeof crypto !== "undefined" && crypto.randomUUID)
          ? crypto.randomUUID() : String(Date.now()) + "-" + String(Math.random());
        window.__kbFamilyCallbacks[id] = outcome => {
          delete window.__kbFamilyCallbacks[id]; resolve(outcome);
        };
        window.webkit.messageHandlers.familySwitch.postMessage({ id: id, appId: String(appId) });
      });
    })();
    """

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        // Only the exact main console view, its main frame and the fixed console
        // origin may drive a family switch; subframes, popups and foreign origins
        // are ignored (the reply is bound to this same main view). An explicitly
        // isolated Live instance never drives the production launcher or broker.
        guard !isolatedMode,
              message.name == "familySwitch",
              let view = mainView,
              userContentController === view.configuration.userContentController,
              message.webView === mainView,
              !view.isLoading, Self.isConsoleURL(view.url),
              familySwitchAdmits(sameView: message.webView === view,
                  mainFrame: message.frameInfo.isMainFrame,
                  scheme: message.frameInfo.securityOrigin.protocol,
                  host: message.frameInfo.securityOrigin.host,
                  port: message.frameInfo.securityOrigin.port, body: message.body),
              let body = message.body as? [String: Any],
              let id = body["id"] as? String,
              let appId = body["appId"] as? String else {
            return
        }
        performFamilySwitch(id: id, appId: appId, view: view, generation: mainNavigationGeneration)
    }

    static func isConsoleURL(_ url: URL?) -> Bool {
        guard let url else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == 8766
            && url.user == nil && url.password == nil
    }

    func performFamilySwitch(id: String, appId: String, view: WKWebView, generation: UInt64) {
        guard !familySwitchUnknown else {
            replyFamilySwitch(id: id, outcome: "uncertain", view: view, generation: generation); return
        }
        guard !familySwitchInProgress else {
            replyFamilySwitch(id: id, outcome: "failed", view: view, generation: generation); return
        }
        familySwitchInProgress = true
        let home = FileManager.default.homeDirectoryForCurrentUser
        let cli = home.appendingPathComponent(".local/bin/kirabridge")
        let pid = ProcessInfo.processInfo.processIdentifier
        let arguments = ["--principal", "local", "family", "switch", appId,
                         "--source-pid", String(pid)]
        var environment = ProcessInfo.processInfo.environment
        environment["KIRABRIDGE_CONSOLE_EMBED"] = "1"
        DispatchQueue.global().async {
            let outcome: String
            do {
                let result = try DesktopBootstrap.runCapture(executable: cli,
                    arguments: arguments, environment: environment, timeout: 30)
                outcome = familySwitchOutcome(status: result.status, data: result.data, appId: appId)
            } catch {
                let failure = error as? DesktopBootstrapFailure
                outcome = failure?.kind == .processFailed && failure?.cleanupConfirmed == true
                    ? "missing" : "uncertain"
            }
            DispatchQueue.main.async {
                self.familySwitchInProgress = false
                if outcome == "uncertain" { self.familySwitchUnknown = true }
                self.replyFamilySwitch(id: id, outcome: outcome, view: view, generation: generation)
            }
        }
    }

    func replyFamilySwitch(id: String, outcome: String, view: WKWebView, generation: UInt64) {
        guard view === mainView, generation == mainNavigationGeneration,
              !view.isLoading, Self.isConsoleURL(view.url) else { return }
        let idJson = familySwitchJsonString(id)
        let outcomeJson = familySwitchJsonString(outcome)
        let script = "window.__kbFamilyCallbacks && window.__kbFamilyCallbacks[\(idJson)] && window.__kbFamilyCallbacks[\(idJson)](\(outcomeJson));"
        view.evaluateJavaScript(script, completionHandler: nil)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let item = NSMenuItem()
        menu.addItem(item)
        let applicationMenu = NSMenu()
        let about = NSMenuItem(title: "Über KiraBridge", action: #selector(showAbout(_:)), keyEquivalent: "")
        about.target = self
        applicationMenu.addItem(about)
        applicationMenu.addItem(NSMenuItem.separator())
        applicationMenu.addItem(withTitle: "KiraBridge beenden", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = applicationMenu
        NSApp.mainMenu = menu
        let domain = "de.netzwerkpunkt.kirabridge" as CFString
        func preference(_ key: String) -> CFPropertyList? {
            CFPreferencesCopyValue(key as CFString, domain, kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        }
        if let appearance = preference("appearance") as? String {
            if appearance == "light" { NSApp.appearance = NSAppearance(named: .aqua) }
            else if appearance == "dark" { NSApp.appearance = NSAppearance(named: .darkAqua) }
        }
        let storedWidth = (preference("window_width") as? NSNumber)?.doubleValue ?? 1120
        let storedHeight = (preference("window_height") as? NSNumber)?.doubleValue ?? 780
        let arguments = CommandLine.arguments
        isolatedMode = arguments.contains("--live-isolated")
        liveMode = arguments.contains("--live") || isolatedMode
        let width = liveMode
            ? 520
            : storedWidth.isFinite && (820...4096).contains(storedWidth) ? storedWidth : 1120
        let height = liveMode
            ? 680
            : storedHeight.isFinite && (620...4096).contains(storedHeight) ? storedHeight : 780
        mainView = makeWindow(
            title: liveMode ? "KiraBridge Live" : "KiraBridge", width: width, height: height
        )
        if isolatedMode { bootstrapIsolated() } else { bootstrap() }
        NSApp.activate(ignoringOtherApps: true)
    }

    func makeWindow(title: String, width: CGFloat, height: CGFloat, suppliedConfiguration: WKWebViewConfiguration? = nil) -> WKWebView {
        let configuration = suppliedConfiguration ?? WKWebViewConfiguration()
        if suppliedConfiguration == nil {
            // An explicitly isolated instance keeps no WebKit session or storage
            // beyond this process; the production window keeps its data store.
            configuration.websiteDataStore = isolatedMode ? .nonPersistent() : .default()
            // Only the production console window bridges the catalog-ID family
            // switch; an isolated instance never registers that handler.
            if !isolatedMode {
                configuration.userContentController.add(self, name: "familySwitch")
                configuration.userContentController.addUserScript(
                    WKUserScript(source: Self.familyBridgeScript, injectionTime: .atDocumentStart,
                                 forMainFrameOnly: true))
            }
        }
        configuration.applicationNameForUserAgent = "KiraBridgeDesktop"
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.uiDelegate = self
        view.navigationDelegate = self
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: height), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = title
        window.minSize = liveMode ? NSSize(width: 420, height: 420) : NSSize(width: 820, height: 620)
        window.contentView = view
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        windows.append(window)
        return view
    }

    /// Explicit opt-in only: an isolated Live instance gets its own private
    /// config directory, its own loopback console port and fresh credentials.
    /// Paths come from fixed arguments, not the environment alone; the
    /// production launcher, service or daemon is never used as a fallback.
    static func isolatedArgument(_ name: String) -> String? {
        let arguments = CommandLine.arguments
        guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
            return nil
        }
        let value = arguments[index + 1]
        return value.hasPrefix("/") && !value.utf8.contains(0) ? value : nil
    }

    static func isolatedPython(_ path: String) -> URL? {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        guard url.lastPathComponent.hasPrefix("python"),
              FileManager.default.isExecutableFile(atPath: url.path) else { return nil }
        return url
    }

    static func isolatedRoot(_ path: String) -> URL? {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory),
              isDirectory.boolValue,
              FileManager.default.fileExists(
                atPath: url.appendingPathComponent("src/kirabridge/__init__.py").path) else {
            return nil
        }
        return url
    }

    func bootstrapIsolated() {
        guard !bootstrapInProgress else { return }
        bootstrapInProgress = true
        guard let rawPython = Self.isolatedArgument("--isolated-python"),
              let rawRoot = Self.isolatedArgument("--isolated-root"),
              let python = Self.isolatedPython(rawPython),
              let root = Self.isolatedRoot(rawRoot) else {
            bootstrapInProgress = false
            showError(
                "Die isolierte Live-Anbindung braucht --isolated-python und --isolated-root "
                + "mit absoluten Pfaden zur Entwicklungsquelle. Es wird bewusst nicht auf "
                + "den produktiven Starter ausgewichen.",
                retryAllowed: false)
            return
        }
        // Canonical owned base before the directory exists, so the private
        // config and the receipt's login path agree on /var vs /private/var.
        let base = FileManager.default.temporaryDirectory
            .resolvingSymlinksInPath().standardizedFileURL
        let directory = base.appendingPathComponent(
            "kirabridge-live-isolated-" + UUID().uuidString)
        let config = directory.appendingPathComponent("config.toml")
        let environment = DesktopBootstrap.isolatedEnvironment(
            root: root, from: ProcessInfo.processInfo.environment)
        DispatchQueue.global().async {
            do {
                let server = try DesktopBootstrap.startIsolated(
                    executable: python,
                    arguments: ["-m", "kirabridge.cli", "--config", config.path,
                                "isolated-live", "--port", "0"],
                    environment: environment, privateDirectory: directory,
                    owned: { self.isolatedChild.adopt($0) })
                DispatchQueue.main.async {
                    self.bootstrapInProgress = false
                    self.bootstrapCleanupUnknown = false
                    self.navigationPolicy = DesktopNavigationPolicy(
                        consolePort: server.receipt.origin.port ?? 0)
                    self.navigationPolicy.authorizeLogin(
                        DesktopLoginReceipt(loginFile: server.receipt.loginFile))
                    self.loadLogin(server.receipt.loginFile.path)
                    self.openRequests.resolve(self.navigationPolicy, ready: self.mainView != nil)
                }
            } catch {
                let failure = (error as? DesktopBootstrapFailure)
                    ?? DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
                DispatchQueue.main.async {
                    self.bootstrapInProgress = !failure.cleanupConfirmed
                    self.bootstrapCleanupUnknown = !failure.cleanupConfirmed
                    // A failed start closes the adoption fence: a late child can
                    // never be adopted untracked while the outcome is unknown.
                    self.isolatedChild.seal()
                    self.openRequests.failAll()
                    self.showError(
                        failure.localizedDescription, retryAllowed: failure.cleanupConfirmed)
                }
            }
        }
    }

    func bootstrap() {
        guard !bootstrapInProgress else { return }
        bootstrapInProgress = true
        let home = FileManager.default.homeDirectoryForCurrentUser
        let launcher = home.appendingPathComponent(".local/bin/kirabridge")
        var environment = ProcessInfo.processInfo.environment
        environment["KIRABRIDGE_CONSOLE_EMBED"] = "1"
        DispatchQueue.global().async {
            do {
                let data = try DesktopBootstrap.run(executable: launcher,
                    arguments: ["approvals"], environment: environment)
                let receipt = try DesktopLoginReceipt(data: data)
                DispatchQueue.main.async {
                    self.bootstrapInProgress = false
                    self.bootstrapCleanupUnknown = false
                    self.navigationPolicy.authorizeLogin(receipt)
                    self.loadLogin(receipt.loginFile.path)
                    self.openRequests.resolve(self.navigationPolicy, ready: self.mainView != nil)
                }
            } catch {
                let failure = (error as? DesktopBootstrapFailure)
                    ?? DesktopBootstrapFailure(kind: .processFailed, cleanupConfirmed: true)
                DispatchQueue.main.async {
                    self.bootstrapInProgress = !failure.cleanupConfirmed
                    self.bootstrapCleanupUnknown = !failure.cleanupConfirmed
                    self.openRequests.failAll()
                    self.showError(failure.localizedDescription, retryAllowed: failure.cleanupConfirmed)
                }
            }
        }
    }

    func loadLogin(_ path: String) {
        guard navigationPolicy.allowsLoginPath(path), let file = navigationPolicy.loginFile else {
            showError("Die lokale Anmeldung konnte nicht zugeordnet werden."); return
        }
        mainView.loadFileURL(file, allowingReadAccessTo: file)
    }

    func showError(_ text: String, retryAllowed: Bool = true) {
        let alert = NSAlert()
        alert.messageText = "KiraBridge konnte nicht geöffnet werden"
        alert.informativeText = text
        if retryAllowed { alert.addButton(withTitle: "Erneut versuchen") }
        alert.addButton(withTitle: "Schließen")
        let response = alert.runModal()
        if retryAllowed && response == .alertFirstButtonReturn {
            if isolatedMode { bootstrapIsolated() } else { bootstrap() }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        mainView?.window?.makeKeyAndOrderFront(nil)
        // A family Reopen must preserve the owned main view and its state.
        // Only an unfinished first login may retry, and an isolated instance
        // retries its own isolated start — never the production launcher.
        if navigationPolicy.loginFile == nil && !bootstrapCleanupUnknown {
            if isolatedMode { bootstrapIsolated() } else { bootstrap() }
        }
        return true
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        if webView === mainView { mainNavigationGeneration &+= 1 }
    }

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        guard !bootstrapCleanupUnknown else { sender.reply(toOpenOrPrint: .failure); return }
        if mainView != nil && navigationPolicy.loginFile == nil && !bootstrapInProgress {
            if isolatedMode { bootstrapIsolated() } else { bootstrap() }
        }
        openRequests.submit(filenames, policy: navigationPolicy,
            ready: mainView != nil && !bootstrapInProgress,
            load: { self.loadLogin($0) },
            reply: { sender.reply(toOpenOrPrint: $0 ? .success : .failure) })
    }

    func applicationWillTerminate(_ notification: Notification) {
        openRequests.failAll()
        isolatedChild.stop()
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard navigationPolicy.allowsPopup(navigationAction.request.url) else { return nil }
        if let existing = windows.dropFirst().first {
            existing.makeKeyAndOrderFront(nil)
            (existing.contentView as? WKWebView)?.load(navigationAction.request)
            return nil
        }
        let view = makeWindow(title: "KiraBridge · Protokoll", width: 1000, height: 750, suppliedConfiguration: configuration)
        return view
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // Live mode: the login redirect to the console root is replaced by the
        // compact /live monitor on the same origin (same authorized projection).
        if liveMode, webView === mainView,
           navigationAction.targetFrame?.isMainFrame == true,
           let url = navigationAction.request.url,
           navigationPolicy.isConsoleRoot(url) {
            decisionHandler(.cancel)
            if let live = URL(string: "/live", relativeTo: url) {
                mainView.load(URLRequest(url: live))
            }
            return
        }
        switch navigationPolicy.decision(for: navigationAction.request.url,
                                         activated: navigationAction.navigationType == .linkActivated,
                                         isolated: isolatedMode) {
        case .external:
            if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        case .deny:
            decisionHandler(.cancel)
        case .allow:
            decisionHandler(.allow)
        }
    }
}

if CommandLine.arguments == [CommandLine.arguments[0], "--system-operation"] {
    runSystemOperationMode()
}

let delegate = KiraBridgeApp()
let application = NSApplication.shared
application.delegate = delegate
application.run()

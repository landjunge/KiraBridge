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
}

struct DesktopNavigationPolicy {
    private(set) var loginFile: URL?
    mutating func authorizeLogin(_ receipt: DesktopLoginReceipt) { loginFile = receipt.loginFile }
    func allowsLoginPath(_ path: String) -> Bool { loginFile != nil && path == loginFile?.path }
    private func isConsoleOrigin(_ url: URL) -> Bool {
        // Must match kirabridge.LOCAL_APPROVAL_URL; loopback aliases are other origins.
        url.scheme?.lowercased() == "http" && url.host == "127.0.0.1" && url.port == 8766
            && url.user == nil && url.password == nil
    }
    func decision(for url: URL?, activated: Bool) -> DesktopNavigationDecision {
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
        ].contains(url.absoluteString) { return .external }
        if activated, ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
           let host = url.host, !host.isEmpty { return .external }
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
        // are ignored (the reply is bound to this same main view).
        guard message.name == "familySwitch",
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
        liveMode = CommandLine.arguments.contains("--live")
        let width = liveMode
            ? 520
            : storedWidth.isFinite && (820...4096).contains(storedWidth) ? storedWidth : 1120
        let height = liveMode
            ? 680
            : storedHeight.isFinite && (620...4096).contains(storedHeight) ? storedHeight : 780
        mainView = makeWindow(
            title: liveMode ? "KiraBridge Live" : "KiraBridge", width: width, height: height
        )
        bootstrap()
        NSApp.activate(ignoringOtherApps: true)
    }

    func makeWindow(title: String, width: CGFloat, height: CGFloat, suppliedConfiguration: WKWebViewConfiguration? = nil) -> WKWebView {
        let configuration = suppliedConfiguration ?? WKWebViewConfiguration()
        if suppliedConfiguration == nil {
            configuration.websiteDataStore = .default()
            // Only the main console window bridges the catalog-ID family switch.
            configuration.userContentController.add(self, name: "familySwitch")
            configuration.userContentController.addUserScript(
                WKUserScript(source: Self.familyBridgeScript, injectionTime: .atDocumentStart,
                             forMainFrameOnly: true))
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
        if retryAllowed && response == .alertFirstButtonReturn { bootstrap() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        mainView?.window?.makeKeyAndOrderFront(nil)
        // A family Reopen must preserve the owned main view and its state.
        // Only an unfinished first login may need the existing bootstrap path.
        if navigationPolicy.loginFile == nil && !bootstrapCleanupUnknown { bootstrap() }
        return true
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        if webView === mainView { mainNavigationGeneration &+= 1 }
    }

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        guard !bootstrapCleanupUnknown else { sender.reply(toOpenOrPrint: .failure); return }
        if mainView != nil && navigationPolicy.loginFile == nil && !bootstrapInProgress { bootstrap() }
        openRequests.submit(filenames, policy: navigationPolicy,
            ready: mainView != nil && !bootstrapInProgress,
            load: { self.loadLogin($0) },
            reply: { sender.reply(toOpenOrPrint: $0 ? .success : .failure) })
    }

    func applicationWillTerminate(_ notification: Notification) { openRequests.failAll() }

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
                                         activated: navigationAction.navigationType == .linkActivated) {
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

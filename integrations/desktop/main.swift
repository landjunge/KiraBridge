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

struct DesktopSnapshotFailure: Error {
    let message: String
}

/// Self-screenshot mode: build the main window at the requested size, let it lay out
/// for two seconds, cache the content view into a PNG and exit. cacheDisplay works
/// without a Screen Recording grant; the web view centre may legitimately come out blank.
struct DesktopSnapshotRequest {
    let path: String
    let width: CGFloat
    let height: CGFloat

    static func parse(_ arguments: [String]) throws -> DesktopSnapshotRequest? {
        guard let index = arguments.firstIndex(of: "--snapshot") else { return nil }
        guard index + 1 < arguments.count else {
            throw DesktopSnapshotFailure(message: "--snapshot needs a .png path")
        }
        let path = arguments[index + 1]
        guard !path.isEmpty, path.lowercased().hasSuffix(".png") else {
            throw DesktopSnapshotFailure(message: "--snapshot path must end in .png")
        }
        var width: CGFloat = 1440
        var height: CGFloat = 900
        if let sizeIndex = arguments.firstIndex(of: "--size") {
            guard sizeIndex + 1 < arguments.count else {
                throw DesktopSnapshotFailure(message: "--size needs WIDTHxHEIGHT")
            }
            let parts = arguments[sizeIndex + 1].lowercased().split(separator: "x")
            guard parts.count == 2, let w = Double(parts[0]), let h = Double(parts[1]),
                  w.isFinite, h.isFinite, (820...4096).contains(w), (620...4096).contains(h) else {
                throw DesktopSnapshotFailure(message: "--size must be WIDTHxHEIGHT within the window minimum 820x620 and 4096x4096")
            }
            width = CGFloat(w)
            height = CGFloat(h)
        }
        return DesktopSnapshotRequest(path: path, width: width, height: height)
    }
}

/// Snapshot windows keep their requested frame even when it exceeds the screen;
/// cacheDisplay draws off-screen, so the usual screen constraint is counterproductive here.
final class DesktopSnapshotWindow: NSWindow {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

final class KiraBridgeApp: NSObject, NSApplicationDelegate, NSToolbarDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    /// The full release version (for example 0.8.0rc41); the bundle short version is numeric only.
    private static func aboutPanelOptions(
        release: String?, sourceCommit: String?
    ) -> [NSApplication.AboutPanelOptionKey: Any] {
        var options: [NSApplication.AboutPanelOptionKey: Any] = [.version: ""]

        if let release {
            options[.applicationVersion] = release
        }

        if let commit = sourceCommit, commit.utf8.count == 40,
           commit.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) {
            options[.version] = "App-Build \(commit.prefix(7))"
        }

        return options
    }

    @objc func showAbout(_ sender: Any?) {
        let release = Bundle.main.object(forInfoDictionaryKey: "KiraBridgeVersion") as? String
        let commit = Bundle.main.object(forInfoDictionaryKey: "KiraBridgeSourceCommit") as? String

        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(
            options: Self.aboutPanelOptions(release: release, sourceCommit: commit)
        )
    }

    var windows: [NSWindow] = []
    var mainView: WKWebView!
    var mainSplit: MainSplitController?
    var familyContent: FamilyContentController?
    var bootstrapInProgress = false
    var bootstrapCleanupUnknown = false
    var familySwitchInProgress = false
    var familySwitchUnknown = false
    var mainNavigationGeneration: UInt64 = 0
    var navigationPolicy = DesktopNavigationPolicy()
    let openRequests = DesktopOpenRequests()
    /// Set before application.run() by the --snapshot entry; suppresses the login bootstrap.
    var snapshot: DesktopSnapshotRequest?

    /// Catalog-ID-only bridge. The renderer passes exactly one catalog ID and
    /// receives one of focused/failed/uncertain/missing; it never passes
    /// a URL, argv, PID or shell text. `__kbNativeShell` only marks this window as
    /// native-shelled so the login redirect keeps the console's shell=native query.
    private static let familyBridgeScript = """
    (() => {
      window.__kbNativeShell = true;
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

    func performFamilySwitch(id: String, appId: String, view: WKWebView, generation: UInt64,
                             completion: ((String) -> Void)? = nil) {
        guard !familySwitchUnknown else {
            replyFamilySwitch(id: id, outcome: "uncertain", view: view, generation: generation)
            completion?("uncertain"); return
        }
        guard !familySwitchInProgress else {
            replyFamilySwitch(id: id, outcome: "failed", view: view, generation: generation)
            completion?("failed"); return
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
                completion?(outcome)
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
        let width = snapshot?.width ?? (storedWidth.isFinite && (820...4096).contains(storedWidth) ? storedWidth : 1120)
        let height = snapshot?.height ?? (storedHeight.isFinite && (620...4096).contains(storedHeight) ? storedHeight : 780)
        mainView = makeMainWindow(title: "KiraBridge", width: width, height: height)
        if let snapshot {
            // The screenshot pass never bootstraps: no launcher run, no login load.
            // The view-controller fitting size shrinks the window on ordering; restore it.
            windows.first?.setContentSize(NSSize(width: snapshot.width, height: snapshot.height))
            NSApp.activate(ignoringOtherApps: true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                self.finishSnapshot(snapshot)
            }
            return
        }
        bootstrap()
        NSApp.activate(ignoringOtherApps: true)
    }

    private func finishSnapshot(_ request: DesktopSnapshotRequest) {
        func fail(_ message: String) -> Never {
            FileHandle.standardError.write(Data("snapshot failed: \(message)\n".utf8))
            exit(1)
        }
        guard let window = windows.first, let content = window.contentView else {
            fail("the main window is missing")
        }
        guard let rep = content.bitmapImageRepForCachingDisplay(in: content.bounds) else {
            fail("the window cannot allocate a cache rep")
        }
        content.cacheDisplay(in: content.bounds, to: rep)
        guard let data = rep.representation(using: .png, properties: [:]) else {
            fail("PNG encoding failed")
        }
        do {
            try data.write(to: URL(fileURLWithPath: request.path))
        } catch {
            fail("writing \(request.path): \(error.localizedDescription)")
        }
        exit(0)
    }

    /// The Agent Authority shell: native family header, native process sidebar, the
    /// console web view in the middle column and a native details placeholder on the right.
    func makeMainWindow(title: String, width: CGFloat, height: CGFloat) -> WKWebView {
        let configuration = mainConsoleConfiguration()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.uiDelegate = self
        view.navigationDelegate = self
        let split = MainSplitController(webView: view)
        let content = FamilyContentController(split: split)
        content.header.products.onOpen = { [weak self] target in self?.switchFamilyProduct(target) }
        content.header.onLanguage = { [weak self] code in self?.applyFamilyLanguage(code) }
        split.sidebar.onSettings = { [weak self] in self?.openConsoleView(named: "settings") }
        split.sidebar.onSystemHost = { [weak self] in self?.openConsoleView(named: "permissions") }
        let frame = NSRect(x: 0, y: 0, width: width, height: height)
        let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable]
        let window: NSWindow = snapshot == nil
            ? NSWindow(contentRect: frame, styleMask: style, backing: .buffered, defer: false)
            : DesktopSnapshotWindow(contentRect: frame, styleMask: style, backing: .buffered, defer: false)
        window.title = title
        window.minSize = NSSize(width: 820, height: 620)
        window.contentViewController = content
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        let toolbar = NSToolbar(identifier: "KiraBridgeFamilyToolbar")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        window.toolbar = toolbar
        window.toolbarStyle = .unifiedCompact
        window.center()
        window.makeKeyAndOrderFront(nil)
        mainSplit = split
        familyContent = content
        windows.append(window)
        return view
    }

    func applyFamilyLanguage(_ code: String) {
        mainSplit?.localize()
        for item in windows.first?.toolbar?.items ?? [] { item.label = L(item.itemIdentifier.rawValue) }
        guard let view = mainView, !view.isLoading, Self.isConsoleURL(view.url) else { return }
        view.evaluateJavaScript("window.kbSetLanguage && window.kbSetLanguage('\(code == "en" ? "en" : "de")');", completionHandler: nil)
    }

    /// The family header only ever passes one catalog ID into the existing switch path.
    func switchFamilyProduct(_ appId: String) {
        guard let view = mainView, !view.isLoading, Self.isConsoleURL(view.url) else {
            familyContent?.header.showDetail(L("family.notReady")); return
        }
        familyContent?.header.showDetail(L("family.switching"))
        performFamilySwitch(id: "native-" + String(ProcessInfo.processInfo.systemUptime),
                            appId: appId, view: view, generation: mainNavigationGeneration) { [weak self] outcome in
            self?.familyContent?.header.showDetail(L("family." + outcome))
        }
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.init("toolbar.sidebar"), .flexibleSpace, .init("toolbar.permissions"),
         .init("toolbar.settings"), .init("toolbar.inspector")]
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        toolbarDefaultItemIdentifiers(toolbar)
    }

    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier id: NSToolbarItem.Identifier,
                 willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        let item = NSToolbarItem(itemIdentifier: id)
        item.label = L(id.rawValue); item.toolTip = L(id.rawValue); item.target = self
        switch id.rawValue {
        case "toolbar.sidebar":
            item.image = NSImage(systemSymbolName: "sidebar.left", accessibilityDescription: item.label)
            item.action = #selector(toggleSidebar)
        case "toolbar.permissions":
            item.image = NSImage(systemSymbolName: "desktopcomputer", accessibilityDescription: item.label)
            item.action = #selector(openConsolePermissions)
        case "toolbar.settings":
            item.image = NSImage(systemSymbolName: "gearshape", accessibilityDescription: item.label)
            item.action = #selector(openConsoleSettings)
        case "toolbar.inspector":
            item.image = NSImage(systemSymbolName: "sidebar.right", accessibilityDescription: item.label)
            item.action = #selector(toggleInspector)
        default: return nil
        }
        return item
    }

    @objc func toggleSidebar() { mainSplit?.toggleSidebar() }
    @objc func toggleInspector() { mainSplit?.toggleInspector() }
    @objc func openConsolePermissions() { openConsoleView(named: "permissions") }
    @objc func openConsoleSettings() { openConsoleView(named: "settings") }

    /// Drives the console's own data-go tab buttons through the existing showView
    /// mechanism; no URL, no reload of the one-use login view.
    func openConsoleView(named view: String) {
        let selector = "[data-go=\"\(view)\"]"
        guard view == "permissions" || view == "settings",
              let web = mainView, !web.isLoading, Self.isConsoleURL(web.url) else {
            familyContent?.header.showDetail(L("family.notReady")); return
        }
        web.evaluateJavaScript("document.querySelector('\(selector)')?.click();", completionHandler: nil)
    }

    private func mainConsoleConfiguration() -> WKWebViewConfiguration {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        // Only the main console window bridges the catalog-ID family switch.
        configuration.userContentController.add(self, name: "familySwitch")
        configuration.userContentController.addUserScript(
            WKUserScript(source: Self.familyBridgeScript, injectionTime: .atDocumentStart,
                         forMainFrameOnly: true))
        return configuration
    }

    func makeWindow(title: String, width: CGFloat, height: CGFloat, suppliedConfiguration: WKWebViewConfiguration? = nil) -> WKWebView {
        let configuration = suppliedConfiguration ?? mainConsoleConfiguration()
        configuration.applicationNameForUserAgent = "KiraBridgeDesktop"
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.uiDelegate = self
        view.navigationDelegate = self
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: height), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = title
        window.minSize = NSSize(width: 820, height: 620)
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
        if snapshot == nil, navigationPolicy.loginFile == nil && !bootstrapCleanupUnknown { bootstrap() }
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

let snapshotRequest: DesktopSnapshotRequest?
do {
    snapshotRequest = try DesktopSnapshotRequest.parse(CommandLine.arguments)
} catch let failure as DesktopSnapshotFailure {
    FileHandle.standardError.write(Data("snapshot: \(failure.message)\n".utf8))
    exit(1)
} catch {
    FileHandle.standardError.write(Data("snapshot: \(error.localizedDescription)\n".utf8))
    exit(1)
}
let delegate = KiraBridgeApp()
delegate.snapshot = snapshotRequest
let application = NSApplication.shared
application.delegate = delegate
application.run()

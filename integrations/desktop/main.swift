import Cocoa
import WebKit

final class KiraBridgeApp: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var windows: [NSWindow] = []
    var mainView: WKWebView!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let item = NSMenuItem()
        menu.addItem(item)
        let applicationMenu = NSMenu()
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
        let width = storedWidth.isFinite && (820...4096).contains(storedWidth) ? storedWidth : 1120
        let height = storedHeight.isFinite && (620...4096).contains(storedHeight) ? storedHeight : 780
        mainView = makeWindow(title: "KiraBridge", width: width, height: height)
        bootstrap()
        NSApp.activate(ignoringOtherApps: true)
    }

    func makeWindow(title: String, width: CGFloat, height: CGFloat, suppliedConfiguration: WKWebViewConfiguration? = nil) -> WKWebView {
        let configuration = suppliedConfiguration ?? WKWebViewConfiguration()
        if suppliedConfiguration == nil { configuration.websiteDataStore = .default() }
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
        let home = FileManager.default.homeDirectoryForCurrentUser
        let launcher = home.appendingPathComponent(".local/bin/kirabridge")
        let task = Process()
        task.executableURL = launcher
        task.arguments = ["approvals"]
        var environment = ProcessInfo.processInfo.environment
        environment["KIRABRIDGE_CONSOLE_EMBED"] = "1"
        task.environment = environment
        let output = Pipe()
        task.standardOutput = output
        task.standardError = Pipe()
        DispatchQueue.global().async {
            do {
                try task.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()
                guard task.terminationStatus == 0,
                      let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let file = value["login_file"] as? String else {
                    throw NSError(domain: "KiraBridge", code: 1, userInfo: [NSLocalizedDescriptionKey: "Der lokale Starter konnte KiraBridge nicht öffnen."])
                }
                DispatchQueue.main.async { self.loadLogin(file) }
            } catch {
                DispatchQueue.main.async { self.showError(error.localizedDescription) }
            }
        }
    }

    func loadLogin(_ path: String) {
        let expected = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".config/kirabridge/approval-login.html").path
        guard path == expected else { showError("Die lokale Anmeldung konnte nicht zugeordnet werden."); return }
        let file = URL(fileURLWithPath: path)
        mainView.loadFileURL(file, allowingReadAccessTo: file.deletingLastPathComponent())
    }

    func showError(_ text: String) {
        let alert = NSAlert()
        alert.messageText = "KiraBridge konnte nicht geöffnet werden"
        alert.informativeText = text
        alert.addButton(withTitle: "Erneut versuchen")
        alert.addButton(withTitle: "Schließen")
        if alert.runModal() == .alertFirstButtonReturn { bootstrap() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        windows.first?.makeKeyAndOrderFront(nil)
        bootstrap()
        return true
    }

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        if mainView != nil, let file = filenames.first { loadLogin(file) }
        sender.reply(toOpenOrPrint: .success)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = navigationAction.request.url,
              url.host == "127.0.0.1", url.port == 8766, url.path == "/protocol" else { return nil }
        if let existing = windows.dropFirst().first {
            existing.makeKeyAndOrderFront(nil)
            (existing.contentView as? WKWebView)?.load(navigationAction.request)
            return nil
        }
        let view = makeWindow(title: "KiraBridge · Protokoll", width: 1000, height: 750, suppliedConfiguration: configuration)
        return view
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url, !url.isFileURL,
           url.host != "127.0.0.1" && url.host != "localhost" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
}

if CommandLine.arguments == [CommandLine.arguments[0], "--system-operation"] {
    runSystemOperationMode()
}

let delegate = KiraBridgeApp()
let application = NSApplication.shared
application.delegate = delegate
application.run()

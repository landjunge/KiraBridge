import Cocoa
import Darwin

// Acceptance-only app: synthetic controls and private receipt/exit files. This
// code never reads user windows, clipboard, arguments or environment secrets.
func processIdentity(_ pid: pid_t) -> [String: Any] {
    var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, pid]
    var info = kinfo_proc(), size = MemoryLayout<kinfo_proc>.size
    let status = sysctl(&mib, 4, &info, &size, nil, 0)
    if status == 0 && size == 0 { return ["state": "absent", "pid": Int(pid)] }
    guard status == 0, size == MemoryLayout<kinfo_proc>.size, info.kp_proc.p_pid == pid else {
        return ["state": "unknown", "pid": Int(pid)]
    }
    let time = info.kp_proc.p_un.__p_starttime
    guard time.tv_sec > 0, time.tv_usec >= 0, time.tv_usec < 1000000 else {
        return ["state": "unknown", "pid": Int(pid)]
    }
    return ["state": "present", "pid": Int(pid), "uid": Int(info.kp_eproc.e_ucred.cr_uid),
        "ppid": Int(info.kp_eproc.e_ppid),
        "start": String(time.tv_sec) + "." + String(format: "%06d", time.tv_usec)]
}

if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--inspect-process",
   let pid = Int32(CommandLine.arguments[2]), pid > 0 {
    let data = try JSONSerialization.data(withJSONObject: processIdentity(pid), options: [.sortedKeys])
    print(String(decoding: data, as: UTF8.self)); exit(0)
}
if CommandLine.arguments.count != 1 { exit(64) }

final class OwnedFixture: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var text: NSTextField!
    var counter: NSTextField!
    var timer: Timer?
    var clicks = 0
    let nonce: String
    let state: URL
    let exitRequest: URL
    init(nonce: String, state: URL, exitRequest: URL) {
        self.nonce = nonce; self.state = state; self.exitRequest = exitRequest
    }
    func receipt(_ phase: String) {
        var value = processIdentity(getpid())
        value["fixture_uuid"] = nonce; value["phase"] = phase; value["clicks"] = clicks
        if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
            try? data.write(to: state, options: [.atomic])
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: state.path)
        }
    }
    @objc func pressed(_ sender: Any?) {
        clicks += 1; counter.stringValue = "owned-count-\(clicks)"; receipt("button_pressed")
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 270),
            styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "KiraBridge owned fixture \(nonce)"
        window.isRestorable = false; window.isReleasedWhenClosed = false
        window.setAccessibilityIdentifier("fixture-\(nonce)-window")
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 520, height: 270))
        let heading = NSTextField(labelWithString: "Synthetic owned acceptance window")
        heading.frame = NSRect(x: 24, y: 222, width: 470, height: 24)
        text = NSTextField(string: "owned-text-\(nonce)")
        text.frame = NSRect(x: 24, y: 165, width: 470, height: 28)
        text.setAccessibilityIdentifier("fixture-\(nonce)-text")
        let secure = NSSecureTextField(string: "synthetic-secret-\(nonce)")
        secure.frame = NSRect(x: 24, y: 115, width: 470, height: 28)
        secure.setAccessibilityIdentifier("fixture-\(nonce)-secure")
        let button = NSButton(title: "Owned fixture button", target: self, action: #selector(pressed(_:)))
        button.frame = NSRect(x: 24, y: 58, width: 220, height: 34)
        button.setAccessibilityIdentifier("fixture-\(nonce)-button")
        counter = NSTextField(labelWithString: "owned-count-0")
        counter.frame = NSRect(x: 270, y: 62, width: 220, height: 24)
        counter.setAccessibilityIdentifier("fixture-\(nonce)-counter")
        for view in [heading, text!, secure, button, counter!] { content.addSubview(view) }
        window.contentView = content; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true); receipt("ready")
        // Cleanup is an owned private-file request, never a generic OS signal or
        // user notification. The finite lifetime also covers an interrupted runner.
        let deadline = Date().addingTimeInterval(180)
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            guard let self else { return }
            let request = try? Data(contentsOf: self.exitRequest)
            if Date() > deadline || request == Data(self.nonce.utf8) { NSApp.terminate(nil) }
        }
    }
    func applicationWillTerminate(_ notification: Notification) { receipt("terminating") }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

guard let nonce = Bundle.main.object(forInfoDictionaryKey: "FixtureUUID") as? String,
      nonce.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
      let statePath = Bundle.main.object(forInfoDictionaryKey: "FixtureStatePath") as? String,
      let exitPath = Bundle.main.object(forInfoDictionaryKey: "FixtureExitPath") as? String else { exit(64) }
let stateURL = URL(fileURLWithPath: statePath).standardizedFileURL
let exitURL = URL(fileURLWithPath: exitPath).standardizedFileURL
let parent = stateURL.deletingLastPathComponent()
guard parent == exitURL.deletingLastPathComponent(), parent.resolvingSymlinksInPath() == parent,
      stateURL.lastPathComponent == "fixture-state.json", exitURL.lastPathComponent == "fixture-exit.request",
      let attributes = try? FileManager.default.attributesOfItem(atPath: parent.path),
      (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
      ((attributes[.posixPermissions] as? NSNumber)?.intValue ?? 0o777) & 0o077 == 0 else { exit(64) }
let delegate = OwnedFixture(nonce: nonce, state: stateURL, exitRequest: exitURL)
let application = NSApplication.shared
application.delegate = delegate
application.run()

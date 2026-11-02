import AppKit
import CryptoKit

/// Own controlled receiver for real native events; never opens user documents.
@MainActor
final class KeyboardTextView: NSTextView {
    var downCount = 0
    var upCount = 0
    var returnCount = 0

    override func keyDown(with event: NSEvent) {
        downCount += 1
        if event.keyCode == 36 || event.keyCode == 76 {
            returnCount += 1
            return
        }
        if event.keyCode == 0,
           event.modifierFlags.intersection([.command, .control, .option]).isEmpty,
           let text = event.characters {
            // Explicit literal receiver: test event transport including CR/LF/tab.
            insertText(text, replacementRange: selectedRange())
        } else {
            super.keyDown(with: event)
        }
    }
    override func keyUp(with event: NSEvent) { upCount += 1 }
}

@main
@MainActor
struct KeyboardFixture {
    static func main() throws {
        let info = Bundle.main.infoDictionary ?? [:]
        let path = CommandLine.arguments.count == 3 ? CommandLine.arguments[1] : info["FixtureRoot"] as? String
        let identifier = CommandLine.arguments.count == 3 ? CommandLine.arguments[2] : info["FixtureUUID"] as? String
        guard let path, let nonce = identifier,
              nonce.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else { exit(2) }
        let root = URL(fileURLWithPath: path, isDirectory: true)
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let window = NSWindow(contentRect: NSRect(x: 120, y: 120, width: 760, height: 420),
                              styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "KiraBridge native keyboard acceptance – \(nonce)"
        window.collectionBehavior = [.moveToActiveSpace]
        let scroll = NSScrollView(frame: window.contentView!.bounds)
        scroll.autoresizingMask = [.width, .height]
        scroll.hasVerticalScroller = true
        let editor = KeyboardTextView(frame: scroll.bounds)
        editor.isEditable = true
        editor.isSelectable = true
        editor.setAccessibilityEnabled(true)
        editor.isRichText = false
        editor.isAutomaticQuoteSubstitutionEnabled = false
        editor.isAutomaticDashSubstitutionEnabled = false
        editor.isAutomaticSpellingCorrectionEnabled = false
        editor.isAutomaticTextReplacementEnabled = false
        editor.setAccessibilitySubrole(NSAccessibility.Subrole(rawValue: ""))
        scroll.documentView = editor
        window.contentView = scroll
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(editor)
        app.activate(ignoringOtherApps: true)

        func receipt(_ name: String, extra: [String: Any] = [:]) throws {
            let identity = NSRunningApplication.current
            let selection = editor.selectedRange()
            var value: [String: Any] = [
                "pid": Int(getpid()), "nonce": nonce,
                "started_at": identity.launchDate?.timeIntervalSince1970 as Any? ?? NSNull(),
                "app_path": Bundle.main.bundleURL.path,
                "text_sha256": SHA256.hash(data: Data(editor.string.utf8)).map { String(format: "%02x", $0) }.joined(),
                "utf8_bytes": editor.string.utf8.count, "utf16_units": editor.string.utf16.count,
                "selection_utf16": ["location": selection.location, "length": selection.length],
                "down_count": editor.downCount, "up_count": editor.upCount,
                "return_count": editor.returnCount, "clipboard_generation": NSPasteboard.general.changeCount,
                "window_key": window.isKeyWindow, "editor_first_responder": window.firstResponder === editor,
                "accessibility_enabled": editor.isAccessibilityEnabled(),
                "accessibility_focused": editor.isAccessibilityFocused(),
                "accessibility_role": editor.accessibilityRole()?.rawValue ?? "missing",
            ]
            value.merge(extra) { _, new in new }
            try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(
                to: root.appendingPathComponent(name), options: [.atomic])
        }
        try receipt("ready.json")
        let deadline = Date().addingTimeInterval(600)
        let timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in
            MainActor.assumeIsolated {
                if Date() >= deadline { app.terminate(nil); return }
                let command = root.appendingPathComponent("command.json")
                guard let raw = try? Data(contentsOf: command),
                      let data = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
                      data["nonce"] as? String == nonce,
                      let id = data["id"] as? String, UUID(uuidString: id) != nil,
                      let operation = data["operation"] as? String else { return }
                try? FileManager.default.removeItem(at: command)
                if operation == "reset" {
                    window.makeKeyAndOrderFront(nil)
                    window.makeFirstResponder(editor)
                    editor.string = ""
                    editor.setSelectedRange(NSRange(location: 0, length: 0))
                    editor.downCount = 0; editor.upCount = 0; editor.returnCount = 0
                }
                try? receipt("receipt-\(id).json")
                if operation == "close" { app.terminate(nil) }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        app.run()
    }
}

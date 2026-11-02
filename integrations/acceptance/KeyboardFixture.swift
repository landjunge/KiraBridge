import AppKit
import CryptoKit

/// Captures only this owned application's event stream, before Cocoa consumes
/// key equivalents such as Cmd+A. No global tap or event monitor is installed.
@MainActor
final class KeyboardFixtureApplication: NSApplication {
    static let maxRecords = 4096
    var eventRecords: [[String: Any]] = []
    var eventCounts: [String: Int] = [:]
    var eventSequence: UInt64 = 0
    var droppedRecords = 0

    func clearEvents() {
        eventRecords.removeAll(keepingCapacity: true)
        eventCounts.removeAll(keepingCapacity: true)
        droppedRecords = 0
    }

    override func sendEvent(_ event: NSEvent) {
        let type: String
        switch event.type {
        case .keyDown: type = "key_down"
        case .keyUp: type = "key_up"
        case .flagsChanged: type = "flags_changed"
        case .systemDefined: type = "system_defined"
        default: super.sendEvent(event); return
        }
        eventSequence += 1
        eventCounts[type, default: 0] += 1
        var record: [String: Any] = [
            "sequence": eventSequence, "type": type, "raw_type": event.type.rawValue,
            "flags": UInt64(event.modifierFlags.rawValue), "window_number": event.windowNumber,
            "timestamp": event.timestamp,
        ]
        if event.type == .systemDefined {
            record["code"] = (event.data1 >> 16) & 0xffff
            record["subtype"] = event.subtype.rawValue
            record["data1"] = event.data1
            record["data2"] = event.data2
        } else {
            record["code"] = Int(event.keyCode)
            if event.type != .flagsChanged { record["is_repeat"] = event.isARepeat }
        }
        if eventRecords.count == Self.maxRecords {
            eventRecords.removeFirst()
            droppedRecords += 1
        }
        eventRecords.append(record)
        super.sendEvent(event)
    }
}

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

/// A separate non-text focus target records pairs without invoking an action.
@MainActor
final class KeyboardButton: NSButton {
    var downCount = 0
    var upCount = 0
    override var acceptsFirstResponder: Bool { true }
    override func keyDown(with event: NSEvent) { downCount += 1 }
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
        let app = KeyboardFixtureApplication()
        app.setActivationPolicy(.regular)
        let window = NSWindow(contentRect: NSRect(x: 120, y: 120, width: 760, height: 420),
                              styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "KiraBridge native keyboard acceptance – \(nonce)"
        window.isReleasedWhenClosed = false
        var secondWindow: NSWindow?
        window.collectionBehavior = [.moveToActiveSpace]
        let content = NSView(frame: window.contentView!.bounds)
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 48, width: content.bounds.width,
                                               height: content.bounds.height - 48))
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
        if info["FixtureLegacyEmptySubrole"] as? Bool == true {
            editor.setAccessibilitySubrole(NSAccessibility.Subrole(rawValue: ""))
        }
        scroll.documentView = editor
        let button = KeyboardButton(frame: NSRect(x: 12, y: 8, width: 280, height: 32))
        button.title = "Keyboard receiver (no action)"
        button.action = nil
        content.addSubview(scroll)
        content.addSubview(button)
        // Standard Cocoa key-equivalent routing, also visible to menu discovery.
        let menu = NSMenu(title: "Keyboard Fixture")
        let applicationItem = NSMenuItem()
        applicationItem.submenu = NSMenu(title: "Keyboard Fixture")
        menu.addItem(applicationItem)
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")
        let selectAll = NSMenuItem(title: "Select All", action: #selector(NSTextView.selectAll(_:)), keyEquivalent: "a")
        selectAll.keyEquivalentModifierMask = [.command]
        selectAll.target = editor
        editMenu.addItem(selectAll)
        editItem.submenu = editMenu
        menu.addItem(editItem)
        app.mainMenu = menu
        window.contentView = content
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
                "main_window_number": window.windowNumber, "main_window_visible": window.isVisible,
                "second_window_number": secondWindow?.windowNumber as Any? ?? NSNull(),
                "second_window_visible": secondWindow?.isVisible ?? false,
                "second_window_key": secondWindow?.isKeyWindow ?? false,
                "active_window_number": app.keyWindow?.windowNumber as Any? ?? NSNull(),
                "ordered_window_numbers": app.orderedWindows.map { $0.windowNumber },
                "button_first_responder": window.firstResponder === button,
                "button_down_count": button.downCount, "button_up_count": button.upCount,
                "accessibility_enabled": editor.isAccessibilityEnabled(),
                "accessibility_focused": editor.isAccessibilityFocused(),
                "accessibility_role": editor.accessibilityRole()?.rawValue ?? "missing",
                "accessibility_subrole": editor.accessibilitySubrole()?.rawValue as Any? ?? NSNull(),
                "event_records": app.eventRecords, "event_counts": app.eventCounts,
                "event_record_limit": KeyboardFixtureApplication.maxRecords,
                "event_sequence": app.eventSequence, "event_records_dropped": app.droppedRecords,
                "event_record_scope": "own application sendEvent before Cocoa key equivalents; no global tap",
            ]
            value.merge(extra) { _, new in new }
            let temporary = root.appendingPathComponent(".receipt-\(UUID().uuidString).json")
            try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(
                to: temporary, options: [.withoutOverwriting])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
            try FileManager.default.moveItem(at: temporary, to: root.appendingPathComponent(name))
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
                    button.downCount = 0; button.upCount = 0
                    app.clearEvents()
                } else if operation == "focus_button" {
                    window.makeKeyAndOrderFront(nil)
                    window.makeFirstResponder(button)
                } else if operation == "focus_editor" || operation == "focus_main" {
                    window.makeKeyAndOrderFront(nil)
                    if operation == "focus_editor" { window.makeFirstResponder(editor) }
                } else if operation == "clear_events" {
                    app.clearEvents()
                } else if operation == "open_second_window" {
                    if secondWindow == nil {
                        let owned = NSWindow(contentRect: NSRect(x: 180, y: 180, width: 500, height: 220),
                            styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
                        owned.title = "KiraBridge keyboard second owned window – \(nonce)"
                        owned.isReleasedWhenClosed = false
                        owned.collectionBehavior = [.moveToActiveSpace]
                        let label = NSTextField(labelWithString: "Owned window-cycle receiver; no user documents")
                        label.frame = NSRect(x: 16, y: 80, width: 460, height: 30)
                        owned.contentView?.addSubview(label)
                        secondWindow = owned
                    }
                    secondWindow?.makeKeyAndOrderFront(nil)
                } else if operation == "focus_second" {
                    secondWindow?.makeKeyAndOrderFront(nil)
                }
                try? receipt("receipt-\(id).json")
                if operation == "close" { app.terminate(nil) }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        app.run()
    }
}

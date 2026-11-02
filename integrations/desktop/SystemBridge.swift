import AppKit
import Darwin
import ApplicationServices
import CoreGraphics
import CryptoKit
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers
import UserNotifications

struct SystemBridgeFailure: Error {
    let code: String
    let message: String
    var effectUnknown: Bool = false
}

@MainActor
enum SystemBridgeRuntime {
    static let generation = UUID().uuidString
    static var principal = ""
}

/// This mode is entered before NSApplication is created. It has no windows, OS
/// authorization requests or fallback scripts. EOF terminates the child.
enum SystemRequestFrameFailure: Error { case oversized }

enum SystemRequestFrames {
    static func read(from input: FileHandle, consume: (Data) throws -> Void) throws {
        try read({ requested in
            var data = Data(count: requested)
            while true {
                let count = data.withUnsafeMutableBytes { pointer in
                    Darwin.read(input.fileDescriptor, pointer.baseAddress, requested)
                }
                if count >= 0 {
                    data.removeSubrange(count..<data.count)
                    return data
                }
                if errno != EINTR { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            }
        }, consume: consume)
    }
    static func read(_ reader: (Int) throws -> Data,
                     consume: (Data) throws -> Void) throws {
        var line = Data()
        while true {
            let chunk = try reader(8192)
            if chunk.isEmpty { return }  // Partial final frames are never dispatched.
            for byte in chunk {
                if byte == 10 {
                    try consume(line)
                    line.removeAll(keepingCapacity: true)
                } else {
                    guard line.count < 65535 else { throw SystemRequestFrameFailure.oversized }
                    line.append(byte)
                }
            }
        }
    }
}

func runSystemOperationMode() -> Never {
    let ownerPID = getppid()
    guard ownerPID > 1 else { exit(0) }
    let parentWatch = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
    parentWatch.schedule(deadline: .now() + 1, repeating: 1)
    parentWatch.setEventHandler { if getppid() != ownerPID { exit(0) } }
    parentWatch.resume()
    // A plain command-line AppKit process has no window/event source. Keep its
    // main runloop alive while the owned stdin reader waits for the next request.
    RunLoop.main.add(Timer(timeInterval: 3600, repeats: true) { _ in }, forMode: .default)
    DispatchQueue.global(qos: .userInitiated).async {
        let input = FileHandle.standardInput
        do {
            try SystemRequestFrames.read(from: input) { request in
                let completed = DispatchSemaphore(value: 0)
                Task { @MainActor in
                    let response = await SystemBridge.respond(request)
                    do {
                        var output = try JSONSerialization.data(withJSONObject: response, options: [.sortedKeys])
                        guard output.count < 12 * 1024 * 1024 else { exit(65) }
                        output.append(10)
                        try FileHandle.standardOutput.write(contentsOf: output)
                    } catch { exit(74) }
                    completed.signal()
                }
                // handle() may await while principal is worker-global. Finish it before the next frame.
                completed.wait()
            }
            exit(0)
        } catch SystemRequestFrameFailure.oversized { exit(65) }
        catch { exit(0) }
    }
    withExtendedLifetime(parentWatch) { RunLoop.main.run() }
    exit(0)
}

@MainActor
enum SystemBridge {
    static let bundleID = "de.netzwerkpunkt.kirabridge"
    static let preferenceKeys: Set<String> = ["appearance", "notification_sound", "capture_max_side", "window_width", "window_height"]
    static func fail(_ code: String, _ text: String, unknown: Bool = false) -> SystemBridgeFailure {
        SystemBridgeFailure(code: code, message: text, effectUnknown: unknown)
    }
    static func hash(_ object: Any) throws -> String {
        SHA256.hash(data: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])).map { String(format: "%02x", $0) }.joined()
    }
    static func integer(_ args: [String: Any], _ key: String, default fallback: Int? = nil) throws -> Int {
        if args[key] == nil, let fallback { return fallback }
        guard let value = args[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite, value.doubleValue == Double(value.intValue) else {
            throw fail("invalid_arguments", "Expected an exact integer")
        }
        return value.intValue
    }
    static func text(_ args: [String: Any], _ key: String) throws -> String {
        guard let value = args[key] as? String else { throw fail("invalid_arguments", "Expected a string") }
        return value
    }
    static func bool(_ args: [String: Any], _ key: String, default fallback: Bool = false) throws -> Bool {
        guard let raw = args[key] else { return fallback }
        guard let value = raw as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else {
            throw fail("invalid_arguments", "Expected a boolean")
        }
        return value.boolValue
    }
    static func start(_ app: NSRunningApplication) throws -> String {
        guard !app.isTerminated, let date = app.launchDate else {
            throw fail("macos_target_changed", "Application start identity is unavailable")
        }
        return String(format: "%.6f", locale: Locale(identifier: "en_US_POSIX"), date.timeIntervalSince1970)
    }
    static func application(pid: Int, expectedStart: String) throws -> NSRunningApplication {
        guard pid > 0, pid <= Int(Int32.max), let app = NSRunningApplication(processIdentifier: pid_t(pid)),
              try start(app) == expectedStart else {
            throw fail("macos_target_changed", "Application PID/start identity no longer matches")
        }
        return app
    }
    static func target(_ args: [String: Any]) throws -> NSRunningApplication {
        try application(pid: integer(args, "expected_pid"), expectedStart: text(args, "expected_start"))
    }
    static func axGranted() throws {
        guard AXIsProcessTrusted() else { throw fail("macos_permission_denied", "This worker has no Accessibility grant; no request was made") }
    }
    static func screenGranted() throws {
        guard CGPreflightScreenCaptureAccess() else { throw fail("macos_permission_denied", "This worker has no Screen Recording grant; no request was made") }
    }
    static func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
        return value
    }
    static func axWindows(_ app: NSRunningApplication) throws -> [AXUIElement] {
        try axGranted()
        let root = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 1.0)
        guard let values = attribute(root, kAXWindowsAttribute) as? [AXUIElement] else {
            throw fail("macos_ax_unavailable", "Application windows are unavailable through Accessibility")
        }
        guard values.count <= 250 else { throw fail("system_result_limit", "Application has too many Accessibility windows") }
        for value in values {
            AXUIElementSetMessagingTimeout(value, 1.0)
            var actualPID: pid_t = 0
            guard AXUIElementGetPid(value, &actualPID) == .success, actualPID == app.processIdentifier else {
                throw fail("macos_target_changed", "Accessibility window belongs to another process")
            }
        }
        return values
    }
    static func windowRows(titles: Bool) throws -> [[String: Any]] {
        guard let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
            throw fail("macos_windows_unavailable", "Public window inventory is unavailable")
        }
        guard windows.count <= 10000 else { throw fail("system_result_limit", "Window inventory exceeds limit") }
        var rows: [[String: Any]] = []
        for window in windows {
            guard let number = window[kCGWindowNumber as String] as? NSNumber,
                  let owner = window[kCGWindowOwnerPID as String] as? NSNumber,
                  let app = NSRunningApplication(processIdentifier: pid_t(owner.intValue)),
                  let started = try? start(app),
                  let bounds = window[kCGWindowBounds as String] as? [String: Any] else { continue }
            var row: [String: Any] = ["window_id": number.intValue, "owner_pid": owner.intValue,
                "application_start": started, "bounds": bounds,
                "layer": (window[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 0,
                "on_screen": true]
            row["revision"] = try hash(row)
            row["title_available"] = titles
            if titles, let title = window[kCGWindowName as String] as? String { row["title"] = String(title.prefix(4096)) }
            rows.append(row)
        }
        return rows.sorted { ($0["window_id"] as? Int ?? 0) < ($1["window_id"] as? Int ?? 0) }
    }
    static func displays() throws -> [[String: Any]] {
        var count: UInt32 = 0
        guard CGGetActiveDisplayList(0, nil, &count) == .success, count <= 64 else {
            throw fail("macos_displays_unavailable", "Display inventory unavailable")
        }
        var identifiers = [CGDirectDisplayID](repeating: 0, count: Int(count))
        guard CGGetActiveDisplayList(count, &identifiers, &count) == .success else {
            throw fail("macos_displays_unavailable", "Display inventory changed")
        }
        return try identifiers.prefix(Int(count)).sorted().map { id in
            let bounds = CGDisplayBounds(id)
            guard let uuid = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue(),
                  let uuidText = CFUUIDCreateString(nil, uuid) else {
                throw fail("macos_target_changed", "Display UUID identity unavailable")
            }
            var row: [String: Any] = ["display_id": Int(id), "bounds": ["x": bounds.minX, "y": bounds.minY, "width": bounds.width, "height": bounds.height],
                "display_uuid": uuidText as String, "built_in": CGDisplayIsBuiltin(id) != 0,
                "pixel_width": CGDisplayPixelsWide(id), "pixel_height": CGDisplayPixelsHigh(id),
                "main": CGDisplayIsMain(id) != 0, "rotation": CGDisplayRotation(id)]
            row["revision"] = try hash(row)
            return row
        }
    }
    static func window(_ args: [String: Any], titles: Bool = false) throws -> [String: Any] {
        let app = try target(args)
        let id = try integer(args, "window_id")
        guard let row = try windowRows(titles: titles).first(where: { $0["window_id"] as? Int == id }),
              row["owner_pid"] as? Int == Int(app.processIdentifier),
              row["application_start"] as? String == (try start(app)) else {
            throw fail("macos_target_changed", "Window no longer belongs to the expected application")
        }
        if let revision = args["expected_revision"] as? String, row["revision"] as? String != revision {
            throw fail("macos_target_changed", "Window metadata revision changed")
        }
        return row
    }
    static func preference(_ key: String) throws -> [String: Any] {
        guard preferenceKeys.contains(key) else { throw fail("invalid_arguments", "Preference key is not allowed") }
        let value = CFPreferencesCopyValue(key as CFString, bundleID as CFString, kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        var result: [String: Any] = ["domain": bundleID, "key": key, "exists": value != nil]
        if let value {
            guard value is String || value is NSNumber else { throw fail("macos_preference_invalid", "Stored preference type is unsupported") }
            result["value"] = value
        }
        result["revision"] = try hash(result)
        return result
    }
    static func validPreference(_ key: String, _ value: Any) -> Bool {
        if key == "appearance", let string = value as? String { return ["system", "light", "dark"].contains(string) }
        guard let number = value as? NSNumber else { return false }
        if key == "notification_sound" { return CFGetTypeID(number) == CFBooleanGetTypeID() }
        let minima = ["capture_max_side": 64, "window_width": 820, "window_height": 620]
        guard let low = minima[key], CFGetTypeID(number) != CFBooleanGetTypeID() else { return false }
        return number.doubleValue == Double(number.intValue) && number.intValue >= low && number.intValue <= 4096
    }
    static func changePreference(_ operation: String, _ args: [String: Any]) throws -> [String: Any] {
        let key = try text(args, "key")
        let before = try preference(key)
        guard before["revision"] as? String == (try text(args, "expected_revision")) else { throw fail("macos_preference_conflict", "Preference changed since inspection") }
        guard !CFPreferencesAppValueIsForced(key as CFString, bundleID as CFString) else { throw fail("macos_preference_managed", "Managed preferences cannot be changed") }
        let desired = operation == "preferences.reset" ? nil : args["value"]
        if operation == "preferences.write" {
            guard let desired, validPreference(key, desired) else { throw fail("invalid_arguments", "Preference value is invalid") }
        }
        CFPreferencesSetValue(key as CFString, desired as CFPropertyList?, bundleID as CFString, kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        guard CFPreferencesSynchronize(bundleID as CFString, kCFPreferencesCurrentUser, kCFPreferencesAnyHost) else {
            throw fail("macos_preference_unknown", "Preference synchronization failed; do not replay", unknown: true)
        }
        let after: [String: Any]
        do { after = try preference(key) }
        catch { throw fail("macos_preference_unknown", "Preference readback failed; do not replay", unknown: true) }
        if let desired {
            guard let actual = after["value"], (actual as AnyObject).isEqual(desired) else { throw fail("macos_preference_unknown", "Preference readback changed; do not replay", unknown: true) }
        } else if after["exists"] as? Bool != false { throw fail("macos_preference_unknown", "Preference reset readback changed; do not replay", unknown: true) }
        return ["previous_revision": before["revision"]!, "preference": after, "readback_verified": true,
            "comparison_scope": "fresh revision and readback within serialized native worker; external preference writers are not locked"]
    }
    static func notificationStatus() async -> [String: Any] {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return ["bundle_id": bundleID, "authorization_status": settings.authorizationStatus.rawValue,
            "authorized": settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional,
            "alert_setting": settings.alertSetting.rawValue, "sound_setting": settings.soundSetting.rawValue,
            "requests_authorization": false, "display_or_read_verified": false]
    }
    static func postNotification(_ args: [String: Any]) async throws -> [String: Any] {
        guard await notificationStatus()["authorized"] as? Bool == true else { throw fail("macos_permission_denied", "Notification authorization is absent; no request was made") }
        let identifier = try text(args, "identifier")
        guard identifier.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { throw fail("invalid_arguments", "Notification task identity is required") }
        let content = UNMutableNotificationContent()
        content.title = try text(args, "title")
        content.body = try text(args, "body")
        guard content.title.count <= 1024, !content.body.isEmpty, content.body.count <= 8192 else { throw fail("invalid_arguments", "Notification text exceeds limit") }
        let defaultSound = (try? preference("notification_sound")["value"] as? Bool) ?? false
        if try bool(args, "sound", default: defaultSound) { content.sound = .default }
        do { try await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil)) }
        catch { throw fail("macos_notification_unknown", "Notification acceptance failed; do not replay", unknown: true) }
        return ["identifier": identifier, "accepted_by_notification_center": true, "display_or_read_verified": false]
    }
    static func png(_ image: CGImage) throws -> Data {
        guard image.width > 0, image.height > 0, image.width <= 4096, image.height <= 4096,
              let color = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                bytesPerRow: image.width * 4, space: color,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else {
            throw fail("image_limit", "Screenshot dimensions exceed limit")
        }
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        guard let normalized = context.makeImage() else { throw fail("image_invalid", "Screenshot conversion failed") }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, UTType.png.identifier as CFString, 1, nil) else { throw fail("image_invalid", "PNG encoder unavailable") }
        CGImageDestinationAddImage(destination, normalized, [kCGImagePropertyPNGDictionary: [kCGImagePropertyPNGInterlaceType: 0]] as CFDictionary)
        guard CGImageDestinationFinalize(destination), output.length <= 8 * 1024 * 1024 else { throw fail("image_limit", "Screenshot PNG exceeds limit") }
        return output as Data
    }
    @available(macOS 14.0, *)
    static func capture(_ operation: String, _ args: [String: Any]) async throws -> [String: Any] {
        try screenGranted()
        let content: SCShareableContent
        do { content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true) }
        catch { throw fail("macos_capture_unavailable", "Shareable capture inventory unavailable") }
        let filter: SCContentFilter
        let before: [String: Any]
        let width: Int
        let height: Int
        if operation == "capture.window" {
            before = try window(args)
            let id = try integer(args, "window_id")
            let pid = try integer(args, "expected_pid")
            guard let item = content.windows.first(where: { Int($0.windowID) == id && Int($0.owningApplication?.processID ?? -1) == pid }) else {
                throw fail("macos_target_changed", "Window is not in the current capture inventory")
            }
            filter = SCContentFilter(desktopIndependentWindow: item)
            width = max(1, Int(item.frame.width.rounded(.up)))
            height = max(1, Int(item.frame.height.rounded(.up)))
        } else {
            let id = try integer(args, "display_id")
            guard let row = try displays().first(where: { $0["display_id"] as? Int == id }),
                  row["revision"] as? String == (try text(args, "expected_revision")),
                  let item = content.displays.first(where: { Int($0.displayID) == id }) else {
                throw fail("macos_target_changed", "Display metadata revision changed")
            }
            before = row
            filter = SCContentFilter(display: item, excludingWindows: [])
            width = item.width
            height = item.height
        }
        let defaultSide = (try? preference("capture_max_side")["value"] as? Int) ?? 2048
        let side = try integer(args, "max_side", default: defaultSide)
        guard side >= 64, side <= 4096, width > 0, height > 0 else { throw fail("invalid_arguments", "Screenshot dimensions are invalid") }
        let scale = min(1.0, Double(side) / Double(max(width, height)))
        let configuration = SCStreamConfiguration()
        configuration.width = max(1, Int(Double(width) * scale))
        configuration.height = max(1, Int(Double(height) * scale))
        configuration.showsCursor = false
        try screenGranted()
        let image: CGImage
        do { image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) }
        catch { throw fail("macos_capture_unavailable", "Screenshot capture failed") }
        if operation == "capture.window" { _ = try window(args) }
        else {
            guard let after = try displays().first(where: { $0["display_id"] as? Int == before["display_id"] as? Int }),
                  after["revision"] as? String == before["revision"] as? String else { throw fail("macos_target_changed", "Display changed during capture") }
        }
        let data = try png(image)
        return ["image_data": data.base64EncodedString(), "mime_type": "image/png", "bytes": data.count,
            "width": image.width, "height": image.height,
            "content_sha256": SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
            "target": before, "captured_at": ISO8601DateFormatter().string(from: Date())]
    }
    static func handle(_ operation: String, arguments args: [String: Any]) async throws -> [String: Any] {
        switch operation {
        case "windows.list":
            let titlesRequested = try bool(args, "include_titles")
            let titles = titlesRequested && CGPreflightScreenCaptureAccess()
            var rows = try windowRows(titles: titles)
            if let pid = args["owner_pid"] as? NSNumber {
                if let expected = args["expected_start"] as? String { _ = try application(pid: pid.intValue, expectedStart: expected) }
                rows = rows.filter { $0["owner_pid"] as? Int == pid.intValue }
            }
            let limit = try integer(args, "limit", default: 50)
            let offset = try integer(args, "offset", default: 0)
            guard limit >= 1, limit <= 100, offset >= 0, offset <= 10000 else { throw fail("invalid_arguments", "Window range is invalid") }
            let revision = try hash(rows.map { ["window_id": $0["window_id"]!, "revision": $0["revision"]!] })
            if let expected = args["expected_revision"] as? String, expected != revision {
                throw fail("macos_target_changed", "Window inventory changed; restart traversal")
            }
            guard offset == 0 || args["expected_revision"] as? String == revision else {
                throw fail("invalid_arguments", "Window continuation requires an inventory revision")
            }
            let page = Array(rows.dropFirst(offset).prefix(limit))
            var result: [String: Any] = ["windows": page, "total": rows.count,
                "offset": offset, "next_offset": offset + page.count, "revision": revision,
                "truncated": offset + page.count < rows.count,
                "displays": try displays(), "titles_redacted": titlesRequested && !titles]
            if try bool(args, "include_ax") {
                let app = try application(pid: integer(args, "owner_pid"), expectedStart: text(args, "expected_start"))
                result["accessibility_windows"] = try axWindows(app).map { element -> [String: Any] in
                    ["ax_identifier": attribute(element, kAXIdentifierAttribute) as? String ?? "", "role": attribute(element, kAXRoleAttribute) as? String ?? ""]
                }
                _ = try application(pid: Int(app.processIdentifier), expectedStart: text(args, "expected_start"))
            }
            return result
        case "windows.inspect":
            return ["window": try window(args, titles: bool(args, "include_titles") && CGPreflightScreenCaptureAccess())]
        case "app.focus":
            let app = try target(args)
            guard app.processIdentifier != ProcessInfo.processInfo.processIdentifier else { throw fail("macos_protected_target", "Worker cannot focus itself") }
            guard app.activate(options: [.activateIgnoringOtherApps]) else { throw fail("macos_focus_unknown", "Application activation outcome is unknown", unknown: true) }
            let observedStart: String
            do { observedStart = try start(target(args)) }
            catch { throw fail("macos_focus_unknown", "Application identity changed after activation", unknown: true) }
            return ["activation_requested": true, "active_observed": app.isActive, "pid": Int(app.processIdentifier), "application_start": observedStart]
        case "windows.focus":
            let app = try target(args)
            let identifier = try text(args, "ax_identifier")
            guard !identifier.isEmpty, identifier.count <= 256 else { throw fail("invalid_arguments", "Exact public AXIdentifier required") }
            let matches = try axWindows(app).filter { attribute($0, kAXIdentifierAttribute) as? String == identifier }
            guard matches.count == 1 else { throw fail("macos_window_identity_unavailable", "No unique public AXIdentifier; window-title matching is not used") }
            _ = try target(args)
            try axGranted()
            guard attribute(matches[0], kAXIdentifierAttribute) as? String == identifier else {
                throw fail("macos_target_changed", "Accessibility window identifier changed")
            }
            guard AXUIElementPerformAction(matches[0], kAXRaiseAction as CFString) == .success else { throw fail("macos_focus_unknown", "Window raise outcome is unknown", unknown: true) }
            guard app.activate(options: [.activateIgnoringOtherApps]) else { throw fail("macos_focus_unknown", "Window activation outcome is unknown", unknown: true) }
            do { _ = try target(args) }
            catch { throw fail("macos_focus_unknown", "Application identity changed after window raise", unknown: true) }
            return ["raise_requested": true, "active_observed": app.isActive, "ax_identifier": identifier]
        case "capture.window", "capture.display":
            guard #available(macOS 14.0, *) else { throw fail("macos_capture_unavailable", "Screenshot capture requires macOS 14 or newer") }
            return try await capture(operation, args)
        case "notifications.status": return await notificationStatus()
        case "notifications.post": return try await postNotification(args)
        case "preferences.read": return ["preference": try preference(text(args, "key"))]
        case "preferences.write", "preferences.reset": return try changePreference(operation, args)
        default:
            if let result = try await SystemKeyboard.handle(operation, arguments: args) { return result }
            if let result = try await SystemControl.handle(operation, arguments: args) { return result }
            throw fail("unknown_operation", "Unknown native system operation")
        }
    }
    static func respond(_ data: Data) async -> [String: Any] {
        let commit = Bundle.main.object(forInfoDictionaryKey: "KiraBridgeSourceCommit") as? String ?? ""
        let revision = "system-v1:" + commit
        let helper: [String: Any] = ["pid": Int(ProcessInfo.processInfo.processIdentifier),
            "executable": Bundle.main.executableURL?.path ?? "", "bundle_id": Bundle.main.bundleIdentifier ?? "",
            "source_commit": commit, "generation": SystemBridgeRuntime.generation]
        var response: [String: Any] = ["protocol": 1, "revision": revision, "request_id": "", "helper": helper]
        do {
            guard let request = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  Set(request.keys) == Set(["protocol", "revision", "request_id", "principal", "operation", "arguments"]),
                  try integer(request, "protocol") == 1,
                  request["revision"] as? String == revision,
                  let id = request["request_id"] as? String, id.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
                  let principal = request["principal"] as? String, !principal.isEmpty, principal.utf8.count <= 256,
                  let operation = request["operation"] as? String, operation.utf8.count <= 80,
                  let args = request["arguments"] as? [String: Any],
                  Bundle.main.bundleIdentifier == bundleID,
                  Bundle.main.object(forInfoDictionaryKey: "KiraBridgeSystemProtocol") as? Int == 1 else {
                throw fail("system_protocol_mismatch", "Native request protocol or identity is invalid")
            }
            response["request_id"] = id
            SystemBridgeRuntime.principal = principal
            defer { SystemBridgeRuntime.principal = "" }
            response["result"] = try await handle(operation, arguments: args)
        } catch let error as SystemBridgeFailure {
            response["error"] = ["code": error.code, "message": error.message, "effect_unknown": error.effectUnknown]
        } catch {
            response["error"] = ["code": "system_native_unknown", "message": "Native operation failed; no automatic replay", "effect_unknown": true]
        }
        return response
    }
}

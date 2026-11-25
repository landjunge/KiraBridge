import AppKit
import ApplicationServices
import CoreGraphics

/// Coordinate-bound CGEvent mouse synthesis for the native system worker.
/// Same guard model as the native keyboard path: Accessibility plus PostEvent
/// preflight before any effect, complete down/up pairs, no permission request,
/// no retry, and no claim that a receiver processed the posted events.
@MainActor
enum SystemMouse {
    static func failure(_ code: String, _ message: String, unknown: Bool = false) -> SystemBridgeFailure {
        SystemBridgeFailure(code: code, message: message, effectUnknown: unknown)
    }
    static func inputAllowed() throws {
        guard AXIsProcessTrusted() else {
            throw failure("macos_permission_denied", "This native worker has no current Accessibility grant; no request was made")
        }
        guard CGPreflightPostEventAccess() else {
            throw failure("macos_permission_denied", "Native event post access is absent; no request was made")
        }
    }
    static func number(_ args: [String: Any], _ key: String) throws -> Double {
        guard let value = args[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite else {
            throw failure("invalid_arguments", "Expected a finite number")
        }
        return value.doubleValue
    }
    static func integer(_ args: [String: Any], _ key: String) throws -> Int {
        guard let value = args[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite, value.doubleValue == Double(value.intValue) else {
            throw failure("invalid_arguments", "Expected an exact integer")
        }
        return value.intValue
    }
    static func point(_ args: [String: Any]) throws -> CGPoint {
        let x = try number(args, "x"), y = try number(args, "y")
        guard abs(x) <= 100000, abs(y) <= 100000 else {
            throw failure("invalid_arguments", "Mouse coordinates exceed the supported range")
        }
        let point = CGPoint(x: x, y: y)
        var count: UInt32 = 0
        guard CGGetActiveDisplayList(0, nil, &count) == .success, count > 0, count <= 64 else {
            throw failure("macos_displays_unavailable", "Display inventory unavailable")
        }
        var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
        guard CGGetActiveDisplayList(count, &ids, &count) == .success else {
            throw failure("macos_displays_unavailable", "Display inventory changed")
        }
        guard ids.prefix(Int(count)).contains(where: { CGDisplayBounds($0).contains(point) }) else {
            throw failure("invalid_arguments", "Mouse coordinates are outside the active displays")
        }
        return point
    }
    static func source() throws -> CGEventSource {
        guard let source = CGEventSource(stateID: .hidSystemState) else {
            throw failure("macos_mouse_unavailable", "Mouse event source is unavailable; nothing was posted")
        }
        return source
    }
    static func evidence(_ operation: String, events: Int, position: CGPoint? = nil,
                         button: String? = nil, delta: [String: Int]? = nil) -> [String: Any] {
        var result: [String: Any] = [
            "operation": operation, "events_posted": events, "input_attempted": true,
            "receiver_processing_confirmed": false, "automatic_retry": false,
            "permission_requested": false,
            "scope": "CGEvent synthesis at screen coordinates; not application acknowledgement or physical hardware"
        ]
        if let position { result["position"] = ["x": position.x, "y": position.y] }
        if let button { result["button"] = button }
        if let delta { result["delta"] = delta }
        return result
    }
    static func move(_ args: [String: Any]) throws -> [String: Any] {
        let target = try point(args)
        try inputAllowed()
        let eventSource = try source()
        guard let event = CGEvent(mouseEventSource: eventSource, mouseType: .mouseMoved,
                                  mouseCursorPosition: target, mouseButton: .left) else {
            throw failure("macos_mouse_unavailable", "Mouse move event could not be created; nothing was posted")
        }
        try inputAllowed()
        event.post(tap: .cghidEventTap)
        return evidence("mouse.move", events: 1, position: target)
    }
    static func click(_ args: [String: Any]) throws -> [String: Any] {
        let target = try point(args)
        let button = (args["button"] as? String) ?? "left"
        guard button == "left" || button == "right" else {
            throw failure("invalid_arguments", "Mouse button must be left or right")
        }
        try inputAllowed()
        let eventSource = try source()
        let downType: CGEventType = button == "left" ? .leftMouseDown : .rightMouseDown
        let upType: CGEventType = button == "left" ? .leftMouseUp : .rightMouseUp
        let cgButton: CGMouseButton = button == "left" ? .left : .right
        // Both events exist before the first post; failed creation never leaves a half pair.
        guard let down = CGEvent(mouseEventSource: eventSource, mouseType: downType,
                                 mouseCursorPosition: target, mouseButton: cgButton),
              let up = CGEvent(mouseEventSource: eventSource, mouseType: upType,
                               mouseCursorPosition: target, mouseButton: cgButton) else {
            throw failure("macos_mouse_unavailable", "Mouse click pair could not be created; nothing was posted")
        }
        down.setIntegerValueField(.mouseEventClickState, value: 1)
        up.setIntegerValueField(.mouseEventClickState, value: 1)
        try inputAllowed()
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return evidence("mouse.click", events: 2, position: target, button: button)
    }
    static func scroll(_ args: [String: Any]) throws -> [String: Any] {
        let dx = try integer(args, "dx"), dy = try integer(args, "dy")
        guard abs(dx) <= 1000, abs(dy) <= 1000, dx != 0 || dy != 0 else {
            throw failure("invalid_arguments", "Scroll needs bounded non-zero wheel deltas")
        }
        try inputAllowed()
        let eventSource = try source()
        guard let event = CGEvent(scrollWheelEvent2Source: eventSource, units: .line,
                                  wheelCount: 1, wheel1: Int32(dy), wheel2: Int32(dx), wheel3: 0) else {
            throw failure("macos_mouse_unavailable", "Scroll event could not be created; nothing was posted")
        }
        try inputAllowed()
        event.post(tap: .cghidEventTap)
        return evidence("mouse.scroll", events: 1, delta: ["dx": dx, "dy": dy])
    }
    static func handle(_ operation: String, arguments args: [String: Any]) async throws -> [String: Any]? {
        switch operation {
        case "mouse.move": return try move(args)
        case "mouse.click": return try click(args)
        case "mouse.scroll": return try scroll(args)
        default: return nil
        }
    }
}

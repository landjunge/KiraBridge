// Data access for the native views. The console session token lives in the web view's
// localStorage ("kirabridge.session"), so requests are made by the already
// authenticated web view; no second login, no token handling in Swift.
import AppKit
import WebKit

struct AgentInfo: Equatable {
    let id: String, name: String, state: String
    let active: Bool, retired: Bool, configured: Bool
    var model = "", kind = "", version = ""
    var dotColor: NSColor {
        if retired || !configured { return Palette.muted }
        return active ? Palette.green : Palette.amber
    }
    init(id: String, name: String, state: String, active: Bool, retired: Bool, configured: Bool) {
        self.id = id; self.name = name; self.state = state
        self.active = active; self.retired = retired; self.configured = configured
    }
    init?(json: [String: Any]) {
        guard let id = json["id"] as? String else { return nil }
        self.init(id: id, name: (json["name"] as? String) ?? id, state: (json["state"] as? String) ?? "",
                  active: (json["active"] as? Bool) ?? false, retired: (json["retired"] as? Bool) ?? false,
                  configured: (json["configured"] as? Bool) ?? false)
        model = (json["model"] as? String) ?? ""
        kind = (json["kind"] as? String) ?? ""
        version = (json["version"] as? String) ?? ""
    }
    static func parse(_ payload: Any?) -> [AgentInfo] {
        let rows = ((payload as? [String: Any])?["agents"] as? [[String: Any]]) ?? []
        return rows.compactMap(AgentInfo.init(json:))
    }
    /// Offline sample used by --snapshot (no bridge running) so the layout can be checked.
    static let sample: [AgentInfo] = [
        AgentInfo(id: "codex", name: "Codex", state: "active", active: true, retired: false, configured: true),
        AgentInfo(id: "claude", name: "Claude", state: "active", active: true, retired: false, configured: true),
        AgentInfo(id: "qwen", name: "Qwen", state: "inactive", active: false, retired: false, configured: true),
        AgentInfo(id: "gemini", name: "Gemini", state: "inactive", active: false, retired: false, configured: true),
        AgentInfo(id: "grok", name: "Grok", state: "retired", active: false, retired: true, configured: true),
    ]
}

final class ConsoleAPI {
    weak var webView: WKWebView?
    init(webView: WKWebView?) { self.webView = webView }
    /// GET a console JSON endpoint through the authenticated web view; nil on any failure.
    func get(_ path: String, completion: @escaping (Any?) -> Void) {
        guard let webView, path.hasPrefix("/api/") else { return completion(nil) }
        let body = """
        let token = ""; try { token = localStorage.getItem("kirabridge.session") || ""; } catch (_) {}
        const r = await fetch(path, {headers: {"Authorization": "Bearer " + token}});
        return r.ok ? await r.text() : null;
        """
        webView.callAsyncJavaScript(body, arguments: ["path": path], in: nil, in: .page) { result in
            guard case .success(let value) = result, let text = value as? String,
                  let data = text.data(using: .utf8) else { return completion(nil) }
            completion(try? JSONSerialization.jsonObject(with: data))
        }
    }
}

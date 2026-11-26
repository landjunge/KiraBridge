// Right column: details of the agent selected in the sidebar (key/value rows of 29 px)
// plus the entry points to the unchanged web console (permissions, consent, terminals,
// keyboard, doctor, coordinator hand-off).
import AppKit

final class InspectorViewController: NSViewController {
    var onPermissions: (() -> Void)?
    var onAdvanced: (() -> Void)?
    private var agent: AgentInfo?
    private var heading: NSTextField!, subtitle: NSTextField!
    private var keys: [NSTextField] = [], values: [NSTextField] = []
    private var permissions: NSButton!, advanced: NSButton!

    override func loadView() {
        let root = LayoutView(); root.color = Palette.surface; view = root
        heading = label("family.details", size: 18, weight: .semibold)
        subtitle = wrapping(L("inspector.none"))
        root.addSubview(heading); root.addSubview(subtitle)
        for _ in 0..<4 {
            let k = NSTextField(labelWithString: ""), v = NSTextField(labelWithString: "")
            k.font = .systemFont(ofSize: 11); k.textColor = Palette.muted
            v.font = .systemFont(ofSize: 12); v.textColor = Palette.accent
            v.lineBreakMode = .byTruncatingTail
            root.addSubview(k); root.addSubview(v); keys.append(k); values.append(v)
        }
        permissions = compactButton(L("inspector.permissions"), target: self, action: #selector(permissionsPressed), symbol: "lock.shield")
        advanced = compactButton(L("inspector.terminals"), target: self, action: #selector(advancedPressed), symbol: "terminal")
        root.addSubview(permissions); root.addSubview(advanced)
        root.arrange = { [weak self] r in self?.arrange(r) }
        render()
    }

    private func arrange(_ r: NSRect) {
        let pad = FamilyLayout.pad, w = max(0, r.width - 2 * pad)
        heading.frame = NSRect(x: pad, y: 16, width: w, height: 24)
        subtitle.frame = NSRect(x: pad, y: 46, width: w, height: 18)
        var y: CGFloat = 76
        for i in keys.indices {
            keys[i].frame = NSRect(x: pad, y: y, width: 80, height: 17)
            values[i].frame = NSRect(x: pad + 84, y: y, width: max(0, w - 84), height: 17)
            y += FamilyLayout.rowHeight
        }
        let h = FamilyLayout.buttonHeight
        advanced.frame = NSRect(x: pad, y: max(y, r.height - h - pad), width: w, height: h)
        permissions.frame = NSRect(x: pad, y: max(y, r.height - 2 * h - pad - 8), width: w, height: h)
    }

    func show(_ agent: AgentInfo?) { self.agent = agent; render() }

    private func render() {
        guard isViewLoaded else { return }
        let a = agent
        subtitle.stringValue = a?.name ?? L("inspector.none")
        let rows: [(String, String)] = a == nil ? [] : [
            ("inspector.state", a!.state), ("inspector.model", a!.model.isEmpty ? "—" : a!.model),
            ("inspector.kind", a!.kind.isEmpty ? "—" : a!.kind), ("inspector.version", a!.version.isEmpty ? "—" : a!.version),
        ]
        for i in keys.indices {
            keys[i].stringValue = i < rows.count ? L(rows[i].0) : ""
            values[i].stringValue = i < rows.count ? rows[i].1 : ""
        }
        view.needsLayout = true
    }
    @objc private func permissionsPressed() { onPermissions?() }
    @objc private func advancedPressed() { onAdvanced?() }
    func localize() {
        guard isViewLoaded else { return }
        heading.stringValue = L("family.details")
        permissions.title = L("inspector.permissions"); advanced.title = L("inspector.terminals")
        render()
    }
}

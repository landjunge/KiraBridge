// Left column: native agent list (Agent Authority measurements: row 29, pitch 34).
// Rows come from /api/cli, which lists every configured agent. One scroll view, only
// when the rows do not fit; bottom buttons stay pinned.
import AppKit

/// One agent row: keyboard-focusable (Up/Down/Home/End move, Return/Space select) with a
/// visible selection bar and a focus ring.
final class AgentRowView: SurfaceView {
    var onKey: ((Int) -> Void)?
    var onChoose: (() -> Void)?
    var isSelected = false { didSet { needsDisplay = true } }
    override var acceptsFirstResponder: Bool { true }
    override func becomeFirstResponder() -> Bool {
        let ok = super.becomeFirstResponder()
        if ok { needsDisplay = true; scrollToVisible(bounds) }
        return ok
    }
    override func resignFirstResponder() -> Bool { let ok = super.resignFirstResponder(); needsDisplay = true; return ok }
    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case 125: onKey?(1)
        case 126: onKey?(-1)
        case 119: onKey?(Int.max)
        case 115: onKey?(Int.min)
        case 36, 49, 76: onChoose?()
        default: super.keyDown(with: event)
        }
    }
    override func draw(_ dirtyRect: NSRect) {
        (isSelected ? Palette.raised : Palette.surface).setFill()
        bounds.fill()
        if isSelected { Palette.brand.setFill(); NSRect(x: 0, y: 0, width: 3, height: bounds.height).fill() }
        if window?.firstResponder === self {
            NSColor.keyboardFocusIndicatorColor.setStroke()
            let p = NSBezierPath(rect: bounds.insetBy(dx: 1, dy: 1)); p.lineWidth = 2; p.stroke()
        }
    }
}

final class AgentSidebarViewController: NSViewController {
    private(set) var agents: [AgentInfo] = []
    var api: ConsoleAPI?
    var onSettings: (() -> Void)?
    var onSystemHost: (() -> Void)?
    var onSelect: ((AgentInfo) -> Void)?
    private var heading: NSTextField!
    private let scroll = NSScrollView()
    private let document = SurfaceView(frame: .zero)
    private var rows: [AgentRowView] = [], names: [NSTextField] = [], states: [NSTextField] = []
    private var hostButton: NSButton!, settingsButton: NSButton!
    private var timer: Timer?
    private var selectedFirst = false
    private(set) var selectedID: String?

    override func loadView() {
        let root = LayoutView(); root.color = Palette.surface; view = root
        heading = label("family.processes", size: 18, weight: .semibold)
        scroll.drawsBackground = false; scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay; scroll.documentView = document
        document.color = Palette.surface
        hostButton = navigationButton(L("toolbar.permissions"), symbol: "desktopcomputer", action: #selector(hostPressed))
        settingsButton = navigationButton(L("toolbar.settings"), symbol: "gearshape", action: #selector(settingsPressed))
        for v in [heading!, scroll, hostButton!, settingsButton!] as [NSView] { root.addSubview(v) }
        root.arrange = { [weak self] rect in self?.arrange(rect) }
    }

    private func arrange(_ rect: NSRect) {
        let h = FamilyLayout.rowHeight, w = max(0, rect.width - 20)
        heading.frame = NSRect(x: 14, y: 14, width: max(0, rect.width - 28), height: 24)
        settingsButton.frame = NSRect(x: 10, y: max(48, rect.height - h - 10), width: w, height: h)
        hostButton.frame = NSRect(x: 10, y: max(48, rect.height - 2 * h - 15), width: w, height: h)
        let top: CGFloat = 48
        scroll.frame = NSRect(x: 0, y: top, width: rect.width, height: max(0, hostButton.frame.minY - 6 - top))
        let content = CGFloat(rows.count) * FamilyLayout.rowPitch
        document.frame = NSRect(x: 0, y: 0, width: rect.width, height: max(content, scroll.frame.height))
        for i in rows.indices {
            let y = CGFloat(i) * FamilyLayout.rowPitch
            rows[i].frame = NSRect(x: 0, y: y, width: rect.width, height: FamilyLayout.rowHeight)
            names[i].frame = NSRect(x: 27, y: 6, width: max(0, rect.width - 41), height: 17)
        }
    }

    func setAgents(_ list: [AgentInfo]) {
        guard isViewLoaded, list != agents else { return }
        agents = list
        if let first = list.first, selectedFirst == false { selectedFirst = true; select(first) }
        rows.forEach { $0.removeFromSuperview() }
        rows = []; names = []; states = []
        for (i, agent) in list.enumerated() {
            let row = AgentRowView(frame: .zero)
            row.isSelected = agent.id == selectedID
            row.setAccessibilityRole(.button)
            row.setAccessibilityLabel(agent.name + ", " + agent.stateText)
            row.onKey = { [weak self] delta in self?.move(from: i, delta) }
            row.onChoose = { [weak self] in self?.select(agent) }
            let dot = SurfaceView(frame: NSRect(x: 14, y: 11, width: 7, height: 7))
            dot.color = agent.dotColor; dot.rounded = 3.5
            let name = NSTextField(labelWithString: agent.name)
            name.font = .systemFont(ofSize: 12); name.lineBreakMode = .byTruncatingTail
            name.textColor = agent.retired ? Palette.muted : Palette.accent
            name.toolTip = agent.name + " · " + agent.stateText
            row.addSubview(dot); row.addSubview(name)
            row.addGestureRecognizer(NSClickGestureRecognizer(target: self, action: #selector(rowClicked(_:))))
            row.identifier = NSUserInterfaceItemIdentifier(String(i))
            document.addSubview(row); rows.append(row); names.append(name)
        }
        view.needsLayout = true
    }

    @objc private func rowClicked(_ g: NSClickGestureRecognizer) {
        guard let id = g.view?.identifier?.rawValue, let i = Int(id), agents.indices.contains(i) else { return }
        view.window?.makeFirstResponder(rows[i])
        select(agents[i])
    }

    private func select(_ agent: AgentInfo) {
        selectedID = agent.id
        for (i, row) in rows.enumerated() { row.isSelected = agents[i].id == agent.id }
        onSelect?(agent)
    }

    private func move(from index: Int, _ delta: Int) {
        guard !rows.isEmpty else { return }
        let target = delta == Int.max ? rows.count - 1 : delta == Int.min ? 0 : min(max(index + delta, 0), rows.count - 1)
        view.window?.makeFirstResponder(rows[target])
        select(agents[target])
    }

    func startPolling(sample: Bool = false) {
        _ = view
        if sample { setAgents(AgentInfo.sample); return }
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }
    func stopPolling() { timer?.invalidate(); timer = nil }
    private func refresh() {
        api?.get("/api/cli") { [weak self] payload in
            guard payload != nil else { return }
            DispatchQueue.main.async { self?.setAgents(AgentInfo.parse(payload)) }
        }
    }

    private func navigationButton(_ text: String, symbol: String, action: Selector) -> NSButton {
        let b = NSButton(title: text, target: self, action: action)
        b.image = NSImage(systemSymbolName: symbol, accessibilityDescription: text)
        b.imagePosition = .imageLeading; b.isBordered = false; b.alignment = .left
        b.font = .systemFont(ofSize: 12); b.contentTintColor = Palette.muted
        return b
    }
    @objc private func hostPressed() { onSystemHost?() }
    @objc private func settingsPressed() { onSettings?() }
    func localize() {
        guard isViewLoaded else { return }
        heading.stringValue = L("family.processes")
        hostButton.title = L("toolbar.permissions"); settingsButton.title = L("toolbar.settings")
    }
}

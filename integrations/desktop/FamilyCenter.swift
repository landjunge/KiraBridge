// Middle column: native overview and inbox next to the unchanged web console ("Erweitert").
// Measurements as in Agent Authority: segmented control 25, metric cards 66, rows 29/34,
// padding 16. Each native page has exactly one scroll view, shown only when content overflows.
import AppKit
import WebKit

struct InboxItem: Equatable {
    let sender: String, recipient: String, kind: String, body: String, acknowledged: Bool
    static func parse(_ payload: Any?) -> [InboxItem] {
        let rows = ((payload as? [String: Any])?["messages"] as? [[String: Any]]) ?? []
        return rows.reversed().map {
            InboxItem(sender: ($0["sender"] as? String) ?? "?", recipient: ($0["recipient"] as? String) ?? "?",
                      kind: ($0["kind"] as? String) ?? "", body: ($0["body"] as? String) ?? "",
                      acknowledged: !($0["acknowledged"] is NSNull) && $0["acknowledged"] != nil)
        }
    }
    static let sample: [InboxItem] = [
        InboxItem(sender: "codex", recipient: "claude", kind: "result", body: "Build finished, 3 checks green.", acknowledged: true),
        InboxItem(sender: "claude", recipient: "coordinator", kind: "question", body: "Which branch should the next slice use?", acknowledged: false),
    ]
}

struct OverviewState: Equatable {
    var bridgeRunning = false, pending = 0, coordinator = "—"
    var agents: [AgentInfo] = []
    var inbox: [InboxItem] = []
}

/// A titled value tile (Agent Authority metric card).
final class MetricCard: SurfaceView {
    let title = NSTextField(labelWithString: ""), value = NSTextField(labelWithString: "")
    override init(frame: NSRect) {
        super.init(frame: frame); color = Palette.raised; rounded = 0
        title.font = .systemFont(ofSize: 11); title.textColor = Palette.muted
        value.font = .systemFont(ofSize: 18, weight: .semibold); value.textColor = Palette.accent
        for f in [title, value] { f.lineBreakMode = .byTruncatingTail; addSubview(f) }
    }
    required init?(coder: NSCoder) { fatalError() }
    override func layout() {
        super.layout()
        title.frame = NSRect(x: 12, y: 8, width: max(0, bounds.width - 24), height: 15)
        value.frame = NSRect(x: 12, y: 28, width: max(0, bounds.width - 24), height: 26)
    }
}

/// A flipped list with one scroll view; rows are fixed-height text lines, optionally led by a status dot.
final class ListPage: LayoutView {
    let scroll = NSScrollView(), document = SurfaceView(frame: .zero)
    private var lines: [NSTextField] = [], dots: [SurfaceView?] = []
    private var dotted = false
    override init(frame: NSRect) {
        super.init(frame: frame); color = Palette.surface
        scroll.drawsBackground = false; scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay; scroll.documentView = document; document.color = Palette.surface
        addSubview(scroll)
    }
    required init?(coder: NSCoder) { fatalError() }
    func setLines(_ items: [(String, NSColor)], dots colors: [NSColor?] = []) {
        lines.forEach { $0.removeFromSuperview() }
        dots.forEach { $0?.removeFromSuperview() }
        lines = items.map { text, color in
            let f = NSTextField(labelWithString: text)
            f.font = .systemFont(ofSize: 12); f.textColor = color; f.lineBreakMode = .byTruncatingTail
            document.addSubview(f); return f
        }
        dotted = !colors.isEmpty
        dots = items.indices.map { i in
            guard i < colors.count, let color = colors[i] else { return nil }
            let d = SurfaceView(frame: .zero); d.color = color; d.rounded = 3.5
            document.addSubview(d); return d
        }
        needsLayout = true
    }
    func place(in rect: NSRect) {
        scroll.frame = rect
        let h = max(CGFloat(lines.count) * FamilyLayout.rowPitch, rect.height)
        document.frame = NSRect(x: 0, y: 0, width: rect.width, height: h)
        for (i, f) in lines.enumerated() {
            let y = CGFloat(i) * FamilyLayout.rowPitch
            let inset: CGFloat = dotted ? 17 : 0
            dots[i]?.frame = NSRect(x: 0, y: y + 11, width: 7, height: 7)
            f.frame = NSRect(x: inset, y: y + 6, width: max(0, rect.width - inset), height: 18)
        }
    }
}

final class CenterViewController: NSViewController {
    enum Page: Int { case overview, inbox, advanced }
    let webView: WKWebView
    var api: ConsoleAPI?
    private let tabs = NSSegmentedControl(labels: [], trackingMode: .selectOne, target: nil, action: nil)
    private var refreshButton: NSButton!
    private var cards: [MetricCard] = []
    private let agentList = ListPage(frame: .zero), inboxList = ListPage(frame: .zero)
    private let webHost = SurfaceView(frame: .zero)
    private var state = OverviewState()
    private(set) var page: Page = .overview
    private var timer: Timer?

    init(webView: WKWebView) { self.webView = webView; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let root = LayoutView(); root.color = Palette.surface; view = root
        tabs.segmentCount = 3; tabs.controlSize = .small; tabs.segmentStyle = .rounded
        tabs.target = self; tabs.action = #selector(tabChanged)
        tabs.selectedSegment = 0
        refreshButton = compactButton(L("center.refresh"), target: self, action: #selector(refreshPressed), symbol: "arrow.clockwise")
        for _ in 0..<3 { let c = MetricCard(frame: .zero); cards.append(c); root.addSubview(c) }
        webHost.color = Palette.surface
        webView.translatesAutoresizingMaskIntoConstraints = true
        webView.autoresizingMask = [.width, .height]
        webHost.addSubview(webView)
        for v in [tabs, refreshButton, agentList, inboxList, webHost] as [NSView] { root.addSubview(v) }
        localize()
        root.arrange = { [weak self] r in self?.arrange(r) }
        show(.overview)
    }

    private func arrange(_ r: NSRect) {
        let pad = FamilyLayout.pad, w = max(0, r.width - 2 * pad)
        tabs.frame = NSRect(x: pad, y: 12, width: min(360, w), height: FamilyLayout.fieldHeight)
        refreshButton.frame = NSRect(x: r.width - pad - 100, y: 11, width: 100, height: FamilyLayout.buttonHeight)
        let top: CGFloat = 12 + FamilyLayout.buttonHeight + 12
        if page == .advanced {
            webHost.frame = NSRect(x: 0, y: top, width: r.width, height: max(0, r.height - top))
            webView.frame = webHost.bounds
            return
        }
        let gap: CGFloat = 10, cw = (w - 2 * gap) / 3
        for (i, c) in cards.enumerated() {
            c.frame = NSRect(x: pad + CGFloat(i) * (cw + gap), y: top, width: cw, height: 66)
        }
        let listTop = top + 66 + 10
        let list = NSRect(x: pad, y: 0, width: w, height: max(0, r.height - listTop - pad))
        agentList.frame = NSRect(x: 0, y: listTop, width: r.width, height: list.height + pad)
        agentList.place(in: NSRect(x: pad, y: 0, width: w, height: list.height))
        inboxList.frame = NSRect(x: 0, y: top, width: r.width, height: max(0, r.height - top - pad))
        inboxList.place(in: NSRect(x: pad, y: 0, width: w, height: inboxList.frame.height))
    }

    func show(_ p: Page) {
        page = p; tabs.selectedSegment = p.rawValue
        let native = p == .overview
        cards.forEach { $0.isHidden = !native }
        agentList.isHidden = !native
        inboxList.isHidden = p != .inbox; webHost.isHidden = p != .advanced
        refreshButton.isHidden = p == .advanced
        view.needsLayout = true
    }
    @objc private func tabChanged() { show(Page(rawValue: tabs.selectedSegment) ?? .overview) }
    @objc private func refreshPressed() { refresh() }

    func localize() {
        guard isViewLoaded else { return }
        tabs.setLabel(L("center.overview"), forSegment: 0); tabs.setLabel(L("center.inbox"), forSegment: 1)
        tabs.setLabel(L("center.advanced"), forSegment: 2)
        refreshButton.title = L("center.refresh")
        render()
    }

    func apply(_ s: OverviewState) { state = s; render() }
    private func render() {
        guard isViewLoaded else { return }
        let activeCount = state.agents.filter { $0.active }.count
        // Bridge reachability lives in the header (one source); the first card names the coordinator.
        cards[0].title.stringValue = L("center.coordinator")
        cards[0].value.stringValue = state.coordinator
        cards[1].title.stringValue = L("center.agents")
        cards[1].value.stringValue = "\(activeCount) / \(state.agents.count)"
        cards[2].title.stringValue = L("center.pending")
        cards[2].value.stringValue = String(state.pending)
        agentList.setLines(state.agents.isEmpty ? [(L("center.noAgents"), Palette.muted)]
            : state.agents.map { ($0.name + "  ·  " + $0.stateText, $0.retired ? Palette.muted : Palette.accent) },
            dots: state.agents.map { $0.dotColor })
        inboxList.setLines(state.inbox.isEmpty ? [(L("center.noMessages"), Palette.muted)]
            : state.inbox.map { ($0.sender + " → " + $0.recipient + "  ·  " + $0.body.replacingOccurrences(of: "\n", with: " "),
                                 $0.acknowledged ? Palette.muted : Palette.accent) })
        view.needsLayout = true
    }

    func startPolling(sample: Bool) {
        _ = view
        if sample {
            apply(OverviewState(bridgeRunning: true, pending: 1, coordinator: "claude",
                                agents: AgentInfo.sample, inbox: InboxItem.sample)); return
        }
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in self?.refresh() }
    }

    /// The API pages oldest-first (limit 50), so walk the cursor to the end and keep the newest
    /// `inboxLimit` rows. The next poll restarts at the first retained row, so those rows (and
    /// their acknowledged state) are re-read; only the first poll walks the whole history.
    private static let inboxLimit = 30
    private var inboxTeam = "", inboxBase = 0
    private func newestMessages(_ api: ConsoleAPI, teamID: String, completion: @escaping (Any?) -> Void) {
        DispatchQueue.main.async {
            if teamID != self.inboxTeam { self.inboxTeam = teamID; self.inboxBase = 0 }
            self.walkMessages(api, teamID: teamID, after: self.inboxBase, collected: [], pages: 0, completion: completion)
        }
    }
    private func walkMessages(_ api: ConsoleAPI, teamID: String, after: Int, collected: [[String: Any]], pages: Int,
                              completion: @escaping (Any?) -> Void) {
        api.get("/api/team/" + teamID + "/messages?limit=50&after=" + String(after)) { payload in
            DispatchQueue.main.async {
                let dict = payload as? [String: Any]
                guard let rows = dict?["messages"] as? [[String: Any]] else {
                    return completion(collected.isEmpty ? nil : ["messages": Array(collected.suffix(Self.inboxLimit))])
                }
                let all = collected + rows
                if rows.count == 50, pages < 200, let next = dict?["next_cursor"] as? Int {
                    return self.walkMessages(api, teamID: teamID, after: next, collected: all, pages: pages + 1, completion: completion)
                }
                let kept = Array(all.suffix(Self.inboxLimit))
                if let first = kept.first?["seq"] as? Int { self.inboxBase = max(0, first - 1) }
                completion(["messages": kept])
            }
        }
    }

    func refresh() {
        guard let api else { return }
        api.get("/api/control/status") { [weak self] status in
            api.get("/api/cli") { agents in
                api.get("/api/team") { teams in
                    let team = ((teams as? [String: Any])?["teams"] as? [[String: Any]])?.first
                    let teamID = team?["id"] as? String
                    let finish: (Any?) -> Void = { messages in
                        DispatchQueue.main.async {
                            guard let self else { return }
                            let bridge = (status as? [String: Any])?["bridge"] as? [String: Any]
                            var next = OverviewState()
                            next.bridgeRunning = (bridge?["dispatcher_active"] as? Bool) ?? false
                            next.pending = ((status as? [String: Any])?["pending"] as? [Any])?.count ?? 0
                            next.coordinator = (team?["coordinator"] as? String) ?? "—"
                            next.agents = AgentInfo.parse(agents)
                            next.inbox = InboxItem.parse(messages)
                            if next != self.state { self.apply(next) }
                        }
                    }
                    if let teamID { self?.newestMessages(api, teamID: teamID, completion: finish) } else { finish(nil) }
                }
            }
        }
    }
}

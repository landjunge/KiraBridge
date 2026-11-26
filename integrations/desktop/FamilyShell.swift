// The KiraBridge desktop shell, reused from the Agent Authority native app
// (native/macos/Sources/AgentAuthorityMac): Theme.swift (Palette, SurfaceView),
// Controllers.swift (LayoutView, MainSplitController), FamilyHeader.swift
// (FamilyHeaderView, FamilyContentController) and ProductHeader.swift
// (ProductHeaderView, ProductIconButton, ProductHeaderAssetManifest).
// Names, measurements and colours are kept; only AuthorityCore dependencies are
// replaced: AppState/Proof/Warning are absent, Localization becomes the small DE/EN
// table below and FamilySwitchClient.productIDs becomes the fixed catalog list.
// Block 2 adds KiraBridge-specific header state on top of the reused renderer:
// installed products are coloured, missing ones grayed out, the active product keeps
// a brand glow, and a polled bridge-status dot with a confirmed restart sits left of DE/EN.
import AppKit
import CoreImage
import WebKit

// MARK: Theme.swift

/// Single source for column and window minimum sizes (window.minSize must be >= the column sum).
enum FamilyLayout {
    static let sidebarMin: CGFloat = 176, sidebarMax: CGFloat = 220
    static let mainMin: CGFloat = 670
    static let inspectorMin: CGFloat = 292, inspectorMax: CGFloat = 370
    static let dividers: CGFloat = 4
    static let minWindowWidth: CGFloat = sidebarMin + mainMin + inspectorMin + dividers
    static let minWindowHeight: CGFloat = 560
}

enum Palette {
    static func adaptive(_ dark: String, _ light: String) -> NSColor {
        NSColor(name: nil) { appearance in
            hex(appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light)
        }
    }

    static func hex(_ s: String) -> NSColor {
        let v = UInt64(s, radix: 16) ?? 0
        return NSColor(srgbRed: Double((v >> 16) & 255) / 255, green: Double((v >> 8) & 255) / 255,
                       blue: Double(v & 255) / 255, alpha: 1)
    }

    // NetzwerkPunkt Bedienbasis 0.1 roles; native adaptive Light surfaces retained.
    static let background = adaptive("121316", "f5f6f8"), surface = adaptive("1a1c20", "ffffff")
    static let raised = adaptive("25282e", "eceef2")
    static let border = adaptive("353940", "d8dce4"), accent = adaptive("edf0f4", "172539")
    static let muted = adaptive("afb6c1", "5b6370")
    static let decoration = border.withAlphaComponent(0.35)
    static let wordmark = adaptive("ffffff", "17191f")

    // KiraBridge brand frame, the pinned manifest colour of the own icon.
    static let brand = hex("fc63ad")
    static let green = adaptive("7bdaa7", "246943"), amber = adaptive("e4be70", "805f15")
    static let risk = adaptive("f49b9b", "963737")
}

/// The small local DE/EN table that replaces AuthorityCore's Localization.
enum FamilyLocalization {
    static let changed = Notification.Name("KiraBridgeFamilyLocalizationChanged")
    static private(set) var language = "de"
    private static let table: [String: (String, String)] = [
        "app.tagline": ("Deine Agenten. Ein Überblick.", "Your agents. One overview."),
        "toolbar.sidebar": ("Prozesse", "Processes"),
        "toolbar.inspector": ("Details", "Details"),
        "family.products": ("Produkte der Familie", "Family products"),
        "family.language": ("Sprache der Familienoberfläche", "Family header language"),
        "family.processes": ("Prozesse", "Processes"),
        "family.details": ("Details", "Details"),
        "family.placeholder": ("Weitere Inhalte folgen.", "More content will follow."),
        "family.unknown": ("Status ungeprüft", "Status not checked"),
        "family.version": ("Version [version]", "Version [version]"),
        "family.versionUnknown": ("Version unbekannt", "Version unknown"),
        "family.switching": ("Wechsel wird ausgeführt …", "Switching …"),
        "family.notReady": ("Die Konsole ist noch nicht geladen.", "The console is not loaded yet."),
        "family.focused": ("Fenster fokussiert.", "Window focused."),
        "family.failed": ("Wechsel fehlgeschlagen.", "Switch failed."),
        "family.uncertain": ("Ausgang des Wechsels unklar.", "Switch outcome unknown."),
        "family.missing": ("Der Familienvermittler fehlt.", "The family broker is missing."),
        "family.notInstalled": ("nicht installiert", "not installed"),
        "status.running": ("KiraBridge läuft", "KiraBridge running"),
        "status.unreachable": ("Bridge nicht erreichbar", "Bridge unreachable"),
        "header.restart": ("Neustart", "Restart"),
        "restart.title": ("KiraBridge-Dienst neu starten", "Restart the KiraBridge service"),
        "restart.question": ("Der Hintergrunddienst wird sofort neu gestartet. Laufende Aufträge können unterbrochen werden.",
                             "The background service restarts immediately. Running tasks may be interrupted."),
        "restart.cancel": ("Abbrechen", "Cancel"),
        "restart.confirm": ("Neustart", "Restart"),
        "toolbar.permissions": ("Rechte", "Permissions"),
        "toolbar.settings": ("Einstellungen", "Settings"),
    ]

    static func choose(_ code: String) {
        language = code == "en" ? "en" : "de"
        NotificationCenter.default.post(name: changed, object: nil)
    }

    static func text(_ key: String, _ arguments: [String: String] = [:]) -> String {
        guard let pair = table[key] else { return key }
        var value = language == "en" ? pair.1 : pair.0
        for (name, replacement) in arguments { value = value.replacingOccurrences(of: "[" + name + "]", with: replacement) }
        return value
    }
}

func L(_ key: String, _ arguments: [String: String] = [:]) -> String {
    FamilyLocalization.text(key, arguments)
}

func label(_ key: String, size: CGFloat = 12, weight: NSFont.Weight = .regular,
           color: NSColor = .labelColor) -> NSTextField {
    let view = NSTextField(labelWithString: L(key))
    view.font = .systemFont(ofSize: size, weight: weight)
    view.textColor = color
    view.lineBreakMode = .byTruncatingTail
    view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    return view
}

func wrapping(_ text: String, size: CGFloat = 12, color: NSColor = Palette.muted) -> NSTextField {
    let v = NSTextField(wrappingLabelWithString: text)
    v.font = .systemFont(ofSize: size)
    v.textColor = color
    v.lineBreakMode = .byWordWrapping
    return v
}

class SurfaceView: NSView {
    override init(frame: NSRect) { super.init(frame: frame); clipsToBounds = true }
    required init?(coder: NSCoder) { super.init(coder: coder); clipsToBounds = true }
    var color: NSColor = Palette.surface { didSet { needsDisplay = true } }
    var rounded: CGFloat = 0
    override var isFlipped: Bool { true }
    override var wantsDefaultClipping: Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        color.setFill()
        NSBezierPath(roundedRect: bounds, xRadius: rounded, yRadius: rounded).fill()
        if rounded > 0 {
            Palette.decoration.setStroke()
            let p = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: rounded, yRadius: rounded)
            p.lineWidth = 1
            p.stroke()
        }
    }
}

// MARK: Controllers.swift (LayoutView)

class LayoutView: SurfaceView {
    var arrange: ((NSRect) -> Void)?
    override func layout() { super.layout(); arrange?(bounds) }
}

// MARK: ProductHeader.swift

/// Asynchronous reachability poll of the local bridge (127.0.0.1:8765). Any HTTP
/// answer counts as live; the main thread is never blocked by the request.
final class BridgeServiceProbe {
    var onUpdate: ((Bool) -> Void)?
    private var timer: Timer?
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 1.5
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        return URLSession(configuration: configuration)
    }()

    func start() {
        guard timer == nil else { return }
        check()
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            self?.check()
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    private func check() {
        guard let url = URL(string: "http://127.0.0.1:8765/") else { return }
        session.dataTask(with: url) { [weak self] _, response, _ in
            let live = response is HTTPURLResponse
            DispatchQueue.main.async { self?.onUpdate?(live) }
        }.resume()
    }

    deinit { stop() }
}

/// UI metadata only. No collector, process or transport state is inferred.
final class ProductHeaderView: NSStackView {
    private let names = ["KiraBridge", "ThreadDesk", "4AllPass", "TollGate", "Agent Authority"]
    private let ids = ["kirabridge", "threaddesk", "4allpass", "tollgate", "agent-authority"]
    /// The KiraBridge desktop app is the first catalog entry.
    private let selfIndex = 0
    var onOpen: ((String) -> Void)?
    var onDetail: ((String) -> Void)?

    /// An installed family app is one whose bundle sits in /Applications or ~/Applications.
    static func isInstalled(bundleName: String) -> Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let directories = ["/Applications", home.appendingPathComponent("Applications").path]
        return directories.contains {
            FileManager.default.fileExists(atPath: $0 + "/" + bundleName + ".app")
        }
    }

    /// CIColorControls at zero saturation; not-installed products render gray.
    static func grayscale(_ image: NSImage) -> NSImage? {
        guard let tiff = image.tiffRepresentation, let input = CIImage(data: tiff),
              let filter = CIFilter(name: "CIColorControls", parameters: [
                  kCIInputImageKey: input, kCIInputSaturationKey: 0.0,
              ]), let output = filter.outputImage else { return nil }
        guard let bitmap = CIContext().createCGImage(output, from: output.extent) else { return nil }
        return NSImage(cgImage: bitmap, size: image.size)
    }

    private var buttons: [ProductIconButton] = []
    private var observer: NSObjectProtocol?
    init() {
        super.init(frame: .zero)
        orientation = .horizontal; alignment = .centerY; spacing = 4
        wantsLayer = true; layer?.backgroundColor = NSColor.clear.cgColor
        edgeInsets = NSEdgeInsets(top: 0, left: 0, bottom: 0, right: 0)
        let assets = ProductHeaderAssetManifest.load()?.files ?? []
        for index in ids.indices {
            let button = ProductIconButton(title: "", target: self, action: #selector(openProduct(_:)))
            button.identifier = NSUserInterfaceItemIdentifier(ids[index])
            button.onFocus = { [weak self] text in self?.onDetail?(text) }
            button.tag = index; button.isBordered = false; button.focusRingType = .exterior
            button.isInstalled = Self.isInstalled(bundleName: names[index])
            button.isActive = index == selfIndex
            if let asset = assets.first(where: { $0.appId == ids[index] }), asset.viewport.count == 4,
               asset.viewport.allSatisfy({ $0.isFinite && $0 >= 0 }), asset.viewport[2] > 0, asset.viewport[3] > 0,
               let url = productHeaderResourceURL(asset.file, extension: nil) {
                button.crop = NSRect(x: asset.viewport[0], y: asset.viewport[1],
                                     width: asset.viewport[2], height: asset.viewport[3])
                button.original = NSImage(contentsOf: url)
                button.original?.size = NSSize(width: 256, height: 256)
            }
            button.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([button.widthAnchor.constraint(equalToConstant: 44),
                                         button.heightAnchor.constraint(equalToConstant: 44)])
            addArrangedSubview(button); buttons.append(button)
        }
        localize()
        observer = NotificationCenter.default.addObserver(forName: FamilyLocalization.changed, object: nil, queue: .main) { [weak self] _ in
            self?.localize()
        }
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }

    func localize() {
        for index in buttons.indices {
            let installed = buttons[index].isInstalled
            // No collector runs in this app, so an installed product honestly reports "unknown".
            let version = index == selfIndex
                ? Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String : nil
            let text = installed
                ? names[index] + " · " + L("family.unknown") + " · "
                    + (version.map { L("family.version", ["version": $0]) } ?? L("family.versionUnknown"))
                : names[index] + " · " + L("family.notInstalled")
            buttons[index].toolTip = text
            buttons[index].setAccessibilityLabel(text)
            buttons[index].needsDisplay = true
        }
        setAccessibilityLabel(L("family.products"))
    }

    @objc private func openProduct(_ button: NSButton) {
        guard ids.indices.contains(button.tag) else { return }
        onOpen?(ids[button.tag])
    }
}

private final class ProductIconButton: NSButton {
    var onFocus: ((String) -> Void)?
    var original: NSImage?
    var crop = NSRect.zero
    var isInstalled = true { didSet { gray = nil; needsDisplay = true } }
    var isActive = false { didSet { needsDisplay = true } }
    private var gray: NSImage?
    override var acceptsFirstResponder: Bool { true }
    override func becomeFirstResponder() -> Bool {
        let accepted = super.becomeFirstResponder()
        if accepted { onFocus?(toolTip ?? ""); needsDisplay = true }
        return accepted
    }
    override func resignFirstResponder() -> Bool {
        let accepted = super.resignFirstResponder(); needsDisplay = true; return accepted
    }
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 || event.keyCode == 49 { performClick(nil) } else { super.keyDown(with: event) }
    }
    override func draw(_ dirtyRect: NSRect) {
        let frame = NSRect(x: 3, y: 3, width: 38, height: 38)
        NSColor.clear.setStroke()
        let border = NSBezierPath(rect: frame.insetBy(dx: 0.5, dy: 0.5))
        if isActive {
            // Active product: subtle brand-coloured outline, glow kept at a quarter intensity.
            NSGraphicsContext.saveGraphicsState()
            let shadow = NSShadow()
            shadow.shadowColor = Palette.brand.withAlphaComponent(0.25)
            shadow.shadowBlurRadius = 6
            shadow.set()
            Palette.brand.withAlphaComponent(0.9).setStroke()
            border.lineWidth = 1.5
            border.stroke()
            NSGraphicsContext.restoreGraphicsState()
        } else if isInstalled {
            Palette.border.setStroke()
            border.stroke()
        } else {
            Palette.muted.setStroke()
            border.setLineDash([1, 2], count: 2, phase: 0)
            border.stroke()
        }
        var icon = original
        if !isInstalled, let original {
            if gray == nil { gray = ProductHeaderView.grayscale(original) }
            icon = gray ?? original
        }
        if let icon, crop.width > 0, crop.height > 0 {
            let scale = 32 / max(crop.width, crop.height)
            let target = NSRect(x: frame.midX - crop.width * scale / 2, y: frame.midY - crop.height * scale / 2,
                                width: crop.width * scale, height: crop.height * scale)
            let source = NSRect(x: crop.minX, y: 256 - crop.maxY, width: crop.width, height: crop.height)
            icon.draw(in: target, from: source, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        }
        if window?.firstResponder === self {
            NSColor.labelColor.setStroke()
            let focus = NSBezierPath(rect: bounds.insetBy(dx: 1, dy: 1)); focus.lineWidth = 2; focus.stroke()
        }
        if isHighlighted { NSColor(calibratedWhite: 1, alpha: 0.12).setFill(); bounds.fill() }
    }
}

// Consume the pinned shared manifest, rather than maintaining a second set of crop rectangles.
struct ProductHeaderAssetManifest: Decodable {
    struct Asset: Decodable {
        let appId: String
        let file: String
        let sha256: String
        let viewport: [Double]
    }
    let version: String
    let files: [Asset]
    static func load() -> ProductHeaderAssetManifest? {
        guard let url = productHeaderResourceURL("networkpunkt-appbar-assets", extension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(Self.self, from: data)
    }
}

func productHeaderResourceURL(_ name: String, extension ext: String?) -> URL? {
    // Packaged apps must resolve their own resources; there is no SwiftPM resource bundle here.
    Bundle.main.url(forResource: name, withExtension: ext, subdirectory: "ProductHeader")
}

// MARK: FamilyHeader.swift

/// Reuses the existing native five-icon renderer; the split controllers stay alive below it.
final class FamilyHeaderView: LayoutView {
    let products = ProductHeaderView()
    let wordmark = NSTextField(labelWithString: "")
    let language = NSSegmentedControl(labels: ["DE", "EN"], trackingMode: .selectOne, target: nil, action: nil)
    let detail = NSTextField(labelWithString: "")
    /// Service state sits between the product icons and the DE/EN switch.
    let statusDot = SurfaceView(frame: .zero)
    let statusText = NSTextField(labelWithString: "")
    let restartButton = NSButton(title: L("header.restart"), target: nil, action: nil)
    var onLanguage: ((String) -> Void)?
    private let probe = BridgeServiceProbe()
    private var bridgeRunning = false
    override init(frame: NSRect) {
        super.init(frame: frame)
        color = Palette.background
        let name = NSMutableAttributedString(string: "Kira", attributes: [
            .foregroundColor: Palette.wordmark, .font: NSFont.systemFont(ofSize: 21, weight: .bold)])
        name.append(NSAttributedString(string: "Bridge", attributes: [
            .foregroundColor: Palette.brand, .font: NSFont.systemFont(ofSize: 21, weight: .bold)]))
        wordmark.attributedStringValue = name; wordmark.setAccessibilityLabel("KiraBridge")
        language.setWidth(44, forSegment: 0); language.setWidth(44, forSegment: 1)
        language.target = self; language.action = #selector(changeLanguage)
        language.setAccessibilityLabel(L("family.language"))
        detail.font = .systemFont(ofSize: 11); detail.textColor = Palette.muted
        detail.lineBreakMode = .byTruncatingTail; detail.alignment = .center
        products.onDetail = { [weak self] text in self?.showDetail(text) }
        statusDot.rounded = 4.5
        statusText.font = .systemFont(ofSize: 11); statusText.textColor = Palette.muted
        statusText.lineBreakMode = .byTruncatingTail
        statusText.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        restartButton.target = self; restartButton.action = #selector(restartService)
        restartButton.controlSize = .small
        restartButton.font = .systemFont(ofSize: 11)
        restartButton.toolTip = L("restart.title")
        probe.onUpdate = { [weak self] live in self?.setBridgeRunning(live) }
        [wordmark, products, statusDot, statusText, restartButton, language, detail].forEach { addSubview($0) }
        localize()
        probe.start()
        arrange = { [weak self] rect in
            guard let self else { return }
            self.wordmark.frame = NSRect(x: 16, y: 8, width: 240, height: 30)
            self.products.frame = NSRect(x: (rect.width - 236) / 2, y: 0, width: 236, height: 44)
            self.language.frame = NSRect(x: rect.width - 112, y: 0, width: 96, height: 44)
            let limit = rect.width - 120
            let restartWidth: CGFloat = 74
            self.statusDot.frame = NSRect(x: self.products.frame.maxX + 14, y: 17, width: 9, height: 9)
            self.restartButton.frame = NSRect(x: limit - restartWidth, y: 10, width: restartWidth, height: 24)
            let textX = self.products.frame.maxX + 29
            self.statusText.frame = NSRect(x: textX, y: 13,
                                           width: max(40, limit - restartWidth - 10 - textX), height: 16)
            self.detail.frame = NSRect(x: 16, y: 45, width: rect.width - 32, height: 16)
        }
    }

    required init?(coder: NSCoder) { fatalError() }
    deinit { probe.stop() }
    func localize() {
        language.selectedSegment = FamilyLocalization.language == "en" ? 1 : 0
        language.setAccessibilityLabel(L("family.language"))
        products.localize()
        restartButton.title = L("header.restart")
        restartButton.toolTip = L("restart.title")
        setBridgeRunning(bridgeRunning)
        showDetail(L("app.tagline"))
    }
    func showDetail(_ text: String) { detail.stringValue = text; detail.toolTip = text }
    private func setBridgeRunning(_ running: Bool) {
        bridgeRunning = running
        statusDot.color = running ? Palette.green : Palette.muted
        statusText.stringValue = L(running ? "status.running" : "status.unreachable")
        statusText.toolTip = statusText.stringValue
    }
    @objc private func restartService() {
        let alert = NSAlert()
        alert.messageText = L("restart.title")
        alert.informativeText = L("restart.question")
        // Cancel is the default button; the restart only runs on explicit confirmation.
        alert.addButton(withTitle: L("restart.cancel"))
        alert.addButton(withTitle: L("restart.confirm"))
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        let uid = getuid()
        DispatchQueue.global().async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            task.arguments = ["kickstart", "-k", "gui/\(uid)/com.kirabridge.bridge"]
            task.standardOutput = FileHandle.nullDevice
            task.standardError = FileHandle.nullDevice
            do { try task.run() } catch {
                DispatchQueue.main.async { self.showDetail(L("restart.title") + " · " + error.localizedDescription) }
            }
        }
    }
    @objc private func changeLanguage() {
        let code = language.selectedSegment == 1 ? "en" : "de"
        FamilyLocalization.choose(code)
        localize()
        onLanguage?(code)
    }
}

final class FamilyContentController: NSViewController {
    let header = FamilyHeaderView()
    let split: MainSplitController
    init(split: MainSplitController) { self.split = split; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError() }
    override func loadView() {
        let root = LayoutView(); root.color = Palette.background; view = root
        addChild(split); root.addSubview(header); root.addSubview(split.view)
        root.arrange = { [weak self] rect in
            guard let self else { return }
            self.split.adaptToFamilyWidth(rect.width)
            self.header.frame = NSRect(x: 0, y: 0, width: rect.width, height: 64)
            self.split.view.frame = NSRect(x: 0, y: 64, width: rect.width, height: max(0, rect.height - 64))
        }
    }
}

// MARK: MainSplitController.swift (three columns, KiraBridge content)

/// Left column: the native process list. The rows and status dots are placeholders;
/// the live process data arrives with a later slice.
final class ProcessesViewController: NSViewController {
    private let titles = ["KiraBridge", "Codex", "Claude", "Qwen", "Konsole"]
    private var heading: NSTextField!
    private var names: [NSTextField] = []
    private var dots: [SurfaceView] = []
    var onSettings: (() -> Void)?
    var onSystemHost: (() -> Void)?
    private var hostButton: NSButton!
    private var settingsButton: NSButton!
    override func loadView() {
        let root = LayoutView(); root.color = Palette.surface; view = root
        heading = label("family.processes", size: 18, weight: .semibold)
        root.addSubview(heading)
        for title in titles {
            let dot = SurfaceView(frame: .zero); dot.color = Palette.muted; dot.rounded = 3.5
            let field = NSTextField(labelWithString: title)
            field.font = .systemFont(ofSize: 12); field.textColor = Palette.accent
            field.lineBreakMode = .byTruncatingTail
            root.addSubview(dot); root.addSubview(field)
            dots.append(dot); names.append(field)
        }
        hostButton = navigationButton(L("toolbar.permissions"), symbol: "desktopcomputer",
                                      action: #selector(systemHostPressed))
        settingsButton = navigationButton(L("toolbar.settings"), symbol: "gearshape",
                                          action: #selector(settingsPressed))
        root.addSubview(hostButton); root.addSubview(settingsButton)
        root.arrange = { [weak self] rect in
            guard let self else { return }
            self.heading.frame = NSRect(x: 14, y: 14, width: max(0, rect.width - 28), height: 24)
            var y: CGFloat = 48
            for index in self.names.indices {
                self.dots[index].frame = NSRect(x: 14, y: y + 7, width: 7, height: 7)
                self.names[index].frame = NSRect(x: 27, y: y + 2, width: max(0, rect.width - 41), height: 18)
                y += 28
            }
            self.hostButton.frame = NSRect(x: 10, y: max(430, rect.height - 84), width: max(0, rect.width - 20), height: 30)
            self.settingsButton.frame = NSRect(x: 10, y: max(464, rect.height - 46), width: max(0, rect.width - 20), height: 30)
        }
    }
    private func navigationButton(_ text: String, symbol: String, action: Selector) -> NSButton {
        let button = NSButton(title: text, target: self, action: action)
        button.image = NSImage(systemSymbolName: symbol, accessibilityDescription: text)
        button.imagePosition = .imageLeading
        button.isBordered = false
        button.alignment = .left
        button.font = .systemFont(ofSize: 12)
        button.contentTintColor = Palette.muted
        return button
    }
    @objc private func systemHostPressed() { onSystemHost?() }
    @objc private func settingsPressed() { onSettings?() }
    func localize() {
        guard isViewLoaded else { return }
        heading.stringValue = L("family.processes")
        hostButton.title = L("toolbar.permissions")
        settingsButton.title = L("toolbar.settings")
    }
}

/// Middle column: the existing console web view, unchanged.
final class ConsoleViewController: NSViewController {
    let webView: WKWebView
    init(webView: WKWebView) { self.webView = webView; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError() }
    override func loadView() {
        let root = SurfaceView(frame: .zero); root.color = Palette.surface
        webView.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            webView.topAnchor.constraint(equalTo: root.topAnchor),
            webView.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: root.bottomAnchor),
        ])
        view = root
    }
}

/// Right column: placeholder until the detail slice arrives.
final class InspectorPlaceholderController: NSViewController {
    private var heading: NSTextField!
    private var note: NSTextField!
    override func loadView() {
        let root = LayoutView(); root.color = Palette.surface; view = root
        heading = label("family.details", size: 18, weight: .semibold)
        note = wrapping(L("family.placeholder"))
        root.addSubview(heading); root.addSubview(note)
        root.arrange = { [weak self] rect in
            guard let self else { return }
            self.heading.frame = NSRect(x: 16, y: 16, width: max(0, rect.width - 32), height: 24)
            self.note.frame = NSRect(x: 16, y: 46, width: max(0, rect.width - 32), height: 40)
        }
    }
    func localize() {
        guard isViewLoaded else { return }
        heading.stringValue = L("family.details")
        note.stringValue = L("family.placeholder")
    }
}

final class MainSplitController: NSSplitViewController {
    let sidebar: ProcessesViewController
    let main: ConsoleViewController
    let inspector: InspectorPlaceholderController
    private var narrowFamilyWidth = false, inspectorCollapsedForWidth = false
    init(webView: WKWebView) {
        sidebar = ProcessesViewController(); main = ConsoleViewController(webView: webView)
        inspector = InspectorPlaceholderController()
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }
    override func viewDidLoad() {
        super.viewDidLoad()
        let s = NSSplitViewItem(sidebarWithViewController: sidebar)
        s.minimumThickness = FamilyLayout.sidebarMin; s.maximumThickness = FamilyLayout.sidebarMax; s.preferredThicknessFraction = 0.11; s.canCollapse = true
        let m = NSSplitViewItem(viewController: main); m.minimumThickness = FamilyLayout.mainMin
        let i = NSSplitViewItem(viewController: inspector)
        i.minimumThickness = FamilyLayout.inspectorMin; i.maximumThickness = FamilyLayout.inspectorMax; i.canCollapse = true; i.preferredThicknessFraction = 0.18
        addSplitViewItem(s); addSplitViewItem(m); addSplitViewItem(i)
    }
    func localize() { sidebar.localize(); inspector.localize() }
    func adaptToFamilyWidth(_ width: CGFloat) {
        let narrow = width < 1150
        if splitViewItems.count == 3 {
            let inspectorMinimum = splitViewItems[2].minimumThickness
            let dividerBudget = 2 * splitView.dividerThickness
            splitViewItems[1].minimumThickness = narrow
                ? min(670, max(600, width - inspectorMinimum - dividerBudget))
                : 670
        }
        guard splitViewItems.count == 3, narrow != narrowFamilyWidth else { return }
        narrowFamilyWidth = narrow
        if narrow {
            inspectorCollapsedForWidth = !splitViewItems[2].isCollapsed
            if inspectorCollapsedForWidth { splitViewItems[2].isCollapsed = true }
        } else if inspectorCollapsedForWidth {
            splitViewItems[2].isCollapsed = false; inspectorCollapsedForWidth = false
        }
    }
    func toggleSidebar() {
        if narrowFamilyWidth && splitViewItems[0].isCollapsed {
            splitViewItems[2].isCollapsed = true; inspectorCollapsedForWidth = false
        }
        splitViewItems[0].isCollapsed.toggle()
    }
    func toggleInspector() {
        inspectorCollapsedForWidth = false
        if narrowFamilyWidth && splitViewItems[2].isCollapsed { splitViewItems[0].isCollapsed = true }
        splitViewItems[2].isCollapsed.toggle()
    }
}

// Compact native components, measurements taken 1:1 from Agent Authority
// (native/macos Theme.swift / Controllers.swift). One source for all sizes:
// window.minSize must never be smaller than the sum of the column minimums.
import AppKit

enum FamilyLayout {
    // Columns (NSSplitViewController)
    static let sidebarMin: CGFloat = 176, sidebarMax: CGFloat = 220
    static let mainMin: CGFloat = 670
    static let inspectorMin: CGFloat = 292, inspectorMax: CGFloat = 370
    static let dividers: CGFloat = 2
    static let minWindowWidth: CGFloat = sidebarMin + mainMin + inspectorMin + dividers
    static let minWindowHeight: CGFloat = 600
    static let headerHeight: CGFloat = 68
    // Controls
    static let buttonHeight: CGFloat = 28, fieldHeight: CGFloat = 25
    static let rowHeight: CGFloat = 29, rowPitch: CGFloat = 34
    static let pad: CGFloat = 16
}

/// Agent Authority button: rounded, small, optional leading symbol.
func compactButton(_ title: String, target: AnyObject?, action: Selector, symbol: String? = nil) -> NSButton {
    let b = NSButton(title: title, target: target, action: action)
    b.bezelStyle = .rounded
    b.controlSize = .small
    if let symbol {
        b.image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)
        b.imagePosition = .imageLeading
    }
    b.toolTip = title
    return b
}

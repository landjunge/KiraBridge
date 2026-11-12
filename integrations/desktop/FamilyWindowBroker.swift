import Foundation

struct FamilyFailure: Error {
    let code: String
    let unknown: Bool
    init(_ code: String, unknown: Bool = false) { self.code = code; self.unknown = unknown }
}
struct FamilyRect: Equatable {
    var x: Double; var y: Double; var width: Double; var height: Double
    var valid: Bool { [x,y,width,height].allSatisfy(\.isFinite) && width > 0 && height > 0 }
    var json: [String: Any] { ["x":x,"y":y,"width":width,"height":height] }
    func near(_ b: FamilyRect) -> Bool {
        zip([x,y,width,height],[b.x,b.y,b.width,b.height]).allSatisfy { abs($0-$1) <= 1.0 }
    }
    func clamped(to screens: [FamilyRect]) throws -> FamilyRect {
        guard valid, !screens.isEmpty, screens.allSatisfy(\.valid) else { throw FamilyFailure("family_geometry_invalid") }
        func area(_ r: FamilyRect) -> Double {
            max(0,min(x+width,r.x+r.width)-max(x,r.x)) * max(0,min(y+height,r.y+r.height)-max(y,r.y))
        }
        let display=screens.max { a,b in
            if area(a) != area(b) { return area(a)<area(b) }
            return hypot(x-a.x,y-a.y)>hypot(x-b.x,y-b.y)
        }!
        let w=min(width,display.width), h=min(height,display.height)
        return FamilyRect(x:max(display.x,min(x,display.x+display.width-w)),
                          y:max(display.y,min(y,display.y+display.height-h)),width:w,height:h)
    }
}
struct FamilyIdentity: Equatable {
    let product: String; let pid: Int32; let start: String; let uid: UInt32
    let path: String; let executable: String; let installation: String
    var json: [String: Any] { ["product":product,"pid":Int(pid),"start":start,"uid":Int(uid),
        "app_path":path,"executable":executable,"installation_revision":installation] }
}
struct FamilyWindow {
    let token: String; let bounds: FamilyRect; let visible: Bool
}
@MainActor
protocol FamilyWindowPort: AnyObject {
    func caller(pid: Int32, start: String?) throws -> FamilyIdentity
    func identity(_ product: String) throws -> FamilyIdentity?
    func window(_ app: FamilyIdentity) throws -> FamilyWindow?
    func validate(_ app: FamilyIdentity) throws
    func policy() throws
    func destination(_ product: String) throws
    func screens() throws -> [FamilyRect]
    func launch(_ product: String, check: () throws -> Void) async throws -> FamilyIdentity
    func bounds(_ app: FamilyIdentity, _ window: FamilyWindow, _ rect: FamilyRect, check: () throws -> Void) throws
    func focus(_ app: FamilyIdentity, _ window: FamilyWindow, check: () throws -> Void) async throws
    func hide(_ app: FamilyIdentity, _ window: FamilyWindow, check: () throws -> Void) async throws
    func restore(_ app: FamilyIdentity, _ window: FamilyWindow, check: () throws -> Void) async throws
    func frontmost() -> Int32?
}
@MainActor
protocol FamilyWindowJournal: AnyObject {
    func begin(source: FamilyIdentity, target: String) throws -> String
    func finish(_ result: [String: Any]) throws
    func unknown(_ operation: String) throws
    func noEffect(_ operation: String) throws
}

/// A single admitted attempt. The native caller owns a cross-process flock for
/// its whole lifetime. All waits are read-only; effects are never replayed.
@MainActor
final class FamilyWindowBroker {
    static let products=["kirabridge","threaddesk","4allpass","tollgate","agent-authority"]
    let port: FamilyWindowPort
    let journal: FamilyWindowJournal
    var source: FamilyIdentity!
    var sourceWindow: FamilyWindow!
    var bound: [String: FamilyIdentity]=[:]
    var windows: [String: FamilyWindow]=[:]
    var attempted=false
    var displayFrames: [FamilyRect]=[]
    init(_ port: FamilyWindowPort, _ journal: FamilyWindowJournal) { self.port=port; self.journal=journal }
    func guardAll() throws {
        try port.policy()
        guard try port.screens()==displayFrames else { throw FamilyFailure("family_display_changed") }
        guard try port.caller(pid:source.pid,start:source.start)==source else { throw FamilyFailure("family_caller_changed") }
        for product in Self.products {
            guard try port.identity(product)==bound[product] else { throw FamilyFailure("family_roster_changed") }
        }
        for (product, app) in bound {
            try port.validate(app)
            if let old=windows[product] {
                guard let current=try port.window(app), current.token==old.token else {
                    throw FamilyFailure("family_window_changed")
                }
            }
        }
        if source.product != targetProduct, let current=try port.window(source),
           !current.bounds.near(sourceWindow.bounds) { throw FamilyFailure("family_source_moved") }
    }
    var targetProduct=""
    func switchTo(_ target: String, sourcePID: Int32, sourceStart: String?) async throws -> [String: Any] {
        guard Self.products.contains(target) else { throw FamilyFailure("family_target_invalid") }
        targetProduct=target
        try port.policy()
        source=try port.caller(pid:sourcePID,start:sourceStart)
        guard port.frontmost()==source.pid else { throw FamilyFailure("family_source_not_frontmost") }
        for product in Self.products { bound[product]=try port.identity(product) }
        guard bound[source.product]==source, let main=try port.window(source), main.visible else {
            throw FamilyFailure("family_source_window_unavailable")
        }
        sourceWindow=main
        try port.destination(target)
        // Before starting any app, refuse ambiguous/modal windows in existing
        // registered apps. Unregistered installations/helpers are never selected.
        for (product,app) in bound {
            guard let w=try port.window(app) else { throw FamilyFailure("family_main_window_unavailable") }
            windows[product]=w
        }
        displayFrames=try port.screens()
        let desired=try main.bounds.clamped(to:displayFrames)
        try guardAll()
        let operation=try journal.begin(source:source,target:target)
        do {
            if bound[target]==nil {
                try guardAll(); attempted=true
                let app=try await port.launch(target,check:guardAll)
                bound[target]=app
                let deadline=ProcessInfo.processInfo.systemUptime+5
                repeat {
                    try guardAll()
                    if let w=try port.window(app) { windows[target]=w; break }
                    try await Task.sleep(nanoseconds:50_000_000)
                } while ProcessInfo.processInfo.systemUptime<deadline
                guard windows[target] != nil else { throw FamilyFailure("family_launch_unknown",unknown:true) }
            }
            let app=bound[target]!, window=windows[target]!
            try guardAll(); attempted=true
            try port.bounds(app,window,desired,check:guardAll)
            try guardAll()
            try await port.focus(app,window,check:guardAll)
            guard let actual=try port.window(app), actual.bounds.near(desired), actual.visible,
                  port.frontmost()==app.pid else { throw FamilyFailure("family_focus_unknown",unknown:true) }
            // Source is hidden last. Never hide anything until target show/focus
            // and actual outer bounds have been observed, not merely accepted.
            let others=bound.values.filter { $0.product != target }.sorted {
                if $0.product==source.product { return false }
                if $1.product==source.product { return true }
                return $0.product<$1.product
            }
            for other in others {
                try guardAll()
                try await port.hide(other,windows[other.product]!,check:guardAll)
                guard try port.window(other)?.visible==false else { throw FamilyFailure("family_hide_unknown",unknown:true) }
            }
            try guardAll()
            guard port.frontmost()==app.pid else { throw FamilyFailure("family_focus_unknown",unknown:true) }
            let visible=try bound.values.filter { try port.window($0)?.visible==true }
            guard visible.count==1,visible[0]==app,let final=try port.window(app),final.bounds.near(desired) else {
                throw FamilyFailure("family_visibility_unknown",unknown:true)
            }
            let result: [String: Any]=["success":true,"active_product":target,"actual_outer_bounds":final.bounds.json,
                "visible_family_windows":1,"operation_id":operation,"source_identity":source.json,
                "target_identity":app.json,"window_identity":final.token,"automatic_retry":false,
                "evidence":["registered_apps":bound.values.sorted { $0.product<$1.product }.map(\.json),
                    "geometry_space":"logical_outer_desktop_points","display_visible_frames":displayFrames.map(\.json),
                    "identities_revalidated_after_effect":true]]
            try journal.finish(result)
            return result
        } catch {
            if attempted {
                // Recovery is limited to the exact original source and policy;
                // changed identities never receive a compensating write.
                try? await port.restore(source,sourceWindow) { try self.port.policy(); try self.port.validate(self.source) }
                try? journal.unknown(operation)
                throw FamilyFailure((error as? FamilyFailure)?.code ?? "family_effect_unknown",unknown:true)
            }
            try? journal.noEffect(operation)
            throw error
        }
    }
}

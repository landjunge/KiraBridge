import Foundation
import Darwin

@MainActor
func check(_ value: @autoclosure () -> Bool,_ message: String) throws {
    if !value() { throw FamilyFailure("fixture_"+message) }
}
@MainActor
final class Journal: FamilyWindowJournal {
    var pending=false; var begins=0;var receipt: [String:Any]?
    func begin(source: FamilyIdentity,target: String) throws -> String {
        if pending { throw FamilyFailure("family_previous_unknown",unknown:true) }
        pending=true;begins+=1;return "fixture-operation"
    }
    func finish(_ value: [String:Any]) throws { receipt=value;pending=false }
    func unknown(_ operation: String) throws { pending=true }
    func noEffect(_ operation: String) throws { pending=false }
}
@MainActor
final class Port: FamilyWindowPort {
    var apps: [String:FamilyIdentity]=[:];var views: [String:FamilyWindow]=[:]
    var active: Int32=100;var events: [String]=[];var missing=false;var ambiguous="";var modal=""
    var focusFailure=false;var resizeRace=false;var focusRace=false;var launchFailure=false
    var frames=[FamilyRect(x:0,y:24,width:1600,height:850)]
    init() {
        for (n,p) in FamilyWindowBroker.products.enumerated() {
            let id=make(p,n)
            apps[p]=id;views[p]=FamilyWindow(token:p,bounds:FamilyRect(x:100,y:50,width:1358,height:664),visible:true)
        }
    }
    func make(_ p: String,_ n: Int) -> FamilyIdentity {
        FamilyIdentity(product:p,pid:Int32(100+n),start:"1700000000.123456",uid:getuid(),path:"/fixture/"+p+".app",
                       executable:"/fixture/"+p+".app/Contents/MacOS/main",installation:"stable-install")
    }
    func caller(pid: Int32,start: String?) throws -> FamilyIdentity {
        guard let a=apps["kirabridge"],pid==a.pid,start==nil || start==a.start else { throw FamilyFailure("family_source_changed") };return a
    }
    func identity(_ product: String) throws -> FamilyIdentity? { apps[product] }
    func validate(_ app: FamilyIdentity) throws { guard apps[app.product]==app else { throw FamilyFailure("family_identity_changed") } }
    func policy() throws {}
    func destination(_ product: String) throws { if missing { throw FamilyFailure("family_file_unavailable") } }
    func window(_ app: FamilyIdentity) throws -> FamilyWindow? {
        try validate(app)
        if app.product==ambiguous { throw FamilyFailure("family_window_ambiguous") }
        if app.product==modal { throw FamilyFailure("family_modal_or_fullscreen") }
        return views[app.product]
    }
    func screens() throws -> [FamilyRect] { frames }
    func launch(_ product: String,check: () throws -> Void) async throws -> FamilyIdentity {
        try check();events.append("launch:"+product)
        if launchFailure { throw FamilyFailure("family_launch_unknown",unknown:true) }
        let a=make(product,FamilyWindowBroker.products.firstIndex(of:product)!)
        apps[product]=a;views[product]=FamilyWindow(token:product,bounds:FamilyRect(x:0,y:0,width:1000,height:780),visible:false);return a
    }
    func bounds(_ app: FamilyIdentity,_ w: FamilyWindow,_ r: FamilyRect,check: () throws -> Void) throws {
        try check();events.append("bounds:"+app.product)
        views[app.product]=FamilyWindow(token:w.token,bounds:r,visible:w.visible)
        if resizeRace { apps["kirabridge"]=FamilyIdentity(product:"kirabridge",pid:100,start:"1900000000.000001",uid:getuid(),path:"/changed",executable:"/changed",installation:"changed") }
        try check()
    }
    func focus(_ app: FamilyIdentity,_ w: FamilyWindow,check: () throws -> Void) async throws {
        try check();events.append("focus:"+app.product)
        if focusFailure { throw FamilyFailure("family_focus_unknown",unknown:true) }
        active=app.pid;let current=views[app.product]!
        views[app.product]=FamilyWindow(token:current.token,bounds:current.bounds,visible:true)
        if focusRace { apps[app.product]=FamilyIdentity(product:app.product,pid:app.pid,start:"1900000000.000001",uid:getuid(),path:app.path,executable:app.executable,installation:app.installation) }
    }
    func hide(_ app: FamilyIdentity,_ w: FamilyWindow,check: () throws -> Void) async throws {
        try check();events.append("hide:"+app.product)
        views[app.product]=FamilyWindow(token:w.token,bounds:w.bounds,visible:false)
    }
    func restore(_ app: FamilyIdentity,_ w: FamilyWindow,check: () throws -> Void) async throws {
        try check();events.append("restore:"+app.product);active=app.pid
        views[app.product]=FamilyWindow(token:w.token,bounds:w.bounds,visible:true)
    }
    func frontmost() -> Int32? { active }
}
@main
struct FamilyFixture {
    @MainActor static func main() async throws {
        let p=Port(),j=Journal();let original=p.apps
        let result=try await FamilyWindowBroker(p,j).switchTo("threaddesk",sourcePID:100,sourceStart:nil)
        try check(result["success"] as? Bool==true,"success_receipt")
        try check(result["visible_family_windows"] as? Int==1,"single_visible")
        try check(p.apps==original,"processes_and_paths_preserved")
        try check(p.events.prefix(2)==["bounds:threaddesk","focus:threaddesk"],"show_before_hide")
        try check(p.events.last=="hide:kirabridge","source_last")
        try check(p.events.filter { $0.hasPrefix("hide:") }.count==4,"registered_only")
        for mode in ["foreign","stale","missing","ambiguous","modal"] {
            let p=Port(),j=Journal()
            if mode=="missing" { p.missing=true };if mode=="ambiguous" { p.ambiguous="4allpass" };if mode=="modal" { p.modal="4allpass" }
            do {
                _=try await FamilyWindowBroker(p,j).switchTo("threaddesk",sourcePID:mode=="foreign" ? 31781:100,sourceStart:mode=="stale" ? "1900000000.000000":nil)
                throw FamilyFailure("fixture_preflight_accepted")
            } catch let e as FamilyFailure { try check(!e.unknown && !e.code.hasPrefix("fixture_"),"preflight_known") }
            try check(p.events.isEmpty && j.begins==0,"no_preflight_effect")
        }
        for mode in ["focus","resize_race","focus_race","launch_unknown"] {
            let p=Port(),j=Journal()
            p.focusFailure=mode=="focus";p.resizeRace=mode=="resize_race";p.focusRace=mode=="focus_race";p.launchFailure=mode=="launch_unknown"
            if p.launchFailure { p.apps.removeValue(forKey:"threaddesk");p.views.removeValue(forKey:"threaddesk") }
            do { _=try await FamilyWindowBroker(p,j).switchTo("threaddesk",sourcePID:100,sourceStart:nil);throw FamilyFailure("fixture_race_accepted") }
            catch let e as FamilyFailure { try check(e.unknown,"effect_unknown") }
            try check(!p.events.contains { $0.hasPrefix("hide:") },"no_hide_after_failure")
            try check(j.pending,"unknown_durable")
            let count=p.events.count
            if mode != "resize_race" {
                do { _=try await FamilyWindowBroker(p,j).switchTo("threaddesk",sourcePID:100,sourceStart:nil);throw FamilyFailure("fixture_replayed") }
                catch let e as FamilyFailure { try check(e.code=="family_previous_unknown","no_blind_retry") }
            }
            try check(p.events.count==count,"no_retry_effect")
        }
        let launch=Port(),launchJournal=Journal();launch.apps.removeValue(forKey:"threaddesk");launch.views.removeValue(forKey:"threaddesk")
        _=try await FamilyWindowBroker(launch,launchJournal).switchTo("threaddesk",sourcePID:100,sourceStart:nil)
        try check(launch.events.filter { $0.hasPrefix("launch:") }.count==1,"one_launch")
        let input=FamilyRect(x:-1800,y:-10,width:1700,height:1000)
        let clamped=try input.clamped(to:[FamilyRect(x:-1600,y:0,width:1600,height:900),FamilyRect(x:0,y:24,width:1600,height:850)])
        try check(clamped==FamilyRect(x:-1600,y:0,width:1600,height:900),"negative_monitor_clamp")
        let source=p.make("kirabridge",0)
        func record(_ pid: Int32,_ parent: Int32,_ uid: UInt32=getuid(),_ start: String="1700000000.123456") -> SystemServices.Record {
            SystemServices.Record(pid:pid,parent:parent,uid:uid,realUID:uid,savedUID:uid,name:"fixture",path:nil,start:start,tty:false)
        }
        let valid=try FamilyNativePort.callerChain(source,first:200) { record($0,$0==200 ? 100:1) }
        try check(valid==source,"native_ancestry")
        for mode in ["foreign_uid","foreign_parent","changed_start"] {
            do {
                _=try FamilyNativePort.callerChain(source,first:200) { id in
                    record(id,mode=="foreign_parent" ? 1:100,mode=="foreign_uid" ? getuid()+1:getuid(),mode=="changed_start" ? "1900000000.000000":"1700000000.123456")
                };throw FamilyFailure("fixture_ancestry_accepted")
            } catch let e as FamilyFailure { try check(!e.code.hasPrefix("fixture_"),"native_ancestry_refused") }
        }
        try check(FamilyNativePort.processMatches(record(100,1),observedExecutable:source.executable,expectedExecutable:source.executable),"native_path_match")
        try check(!FamilyNativePort.processMatches(record(100,1,getuid()+1),observedExecutable:source.executable,expectedExecutable:source.executable),"foreign_uid_refused")
        try check(!FamilyNativePort.processMatches(record(100,1),observedExecutable:"/foreign/main",expectedExecutable:source.executable),"foreign_path_refused")
        let directory=FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString).path
        defer { try? FileManager.default.removeItem(atPath:directory) }
        var first: FamilyNativeJournal?=try FamilyNativeJournal(directory:directory)
        _=try first!.begin(source:source,target:"threaddesk")
        do { _=try FamilyNativeJournal(directory:directory);throw FamilyFailure("fixture_concurrent_lock") }
        catch let e as FamilyFailure { try check(e.code=="family_busy","global_lock") }
        first=nil
        let second=try FamilyNativeJournal(directory:directory)
        do { _=try second.begin(source:source,target:"threaddesk");throw FamilyFailure("fixture_restart_replay") }
        catch let e as FamilyFailure { try check(e.code=="family_previous_unknown" && e.unknown,"restart_unknown") }
        try check(!FamilyNativePort.isRegisteredCandidate(path:source.path,regular:false,pid:31781,expectedPath:source.path,worker:getpid()),"accessory_helper_excluded")
        try check(!FamilyNativePort.isRegisteredCandidate(path:"/Applications/ThreadDesk.app",regular:true,pid:123,expectedPath:"/Users/fixture/Applications/ThreadDesk.app",worker:getpid()),"second_installation_excluded")
        try check(!FamilyNativePort.isRegisteredCandidate(path:"/System/Applications/Utilities/Terminal.app",regular:true,pid:123,expectedPath:source.path,worker:getpid()),"terminal_excluded")
        let own=try SystemServices.kernelRecord(getpid());try check(own.uid==getuid(),"real_readonly_uid")
        let data=try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys]);print(String(decoding:data,as:UTF8.self))
        print("family identity/foreign PID/missing/modal/focus/race/geometry/order/serialization passed; effects_on_real_windows=0")
    }
}

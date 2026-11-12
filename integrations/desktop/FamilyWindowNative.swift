import AppKit
import ApplicationServices
import CryptoKit
import Darwin

@MainActor
enum FamilyFiles {
    static func canonical(_ path: String) throws -> String {
        guard let p=SystemControl.canonicalExecutablePath(path),p==path else { throw FamilyFailure("family_path_alias") }
        return p
    }
    static func read(_ path: String, limit: Int=65536, privateMode: Bool=false) throws -> Data {
        let fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK)
        guard fd>=0 else { throw FamilyFailure("family_file_unavailable") }
        defer { close(fd) }
        var s=stat()
        guard fstat(fd,&s)==0,(s.st_mode&S_IFMT)==S_IFREG,s.st_uid==getuid() || s.st_uid==0,
              s.st_mode&0o022==0,(!privateMode || (s.st_uid==getuid() && s.st_mode&0o077==0)),
              s.st_size>=0,s.st_size<=limit else { throw FamilyFailure("family_file_untrusted") }
        let data=try FileHandle(fileDescriptor:fd,closeOnDealloc:false).read(upToCount:Int(s.st_size)+1) ?? Data()
        var after=stat()
        guard data.count==s.st_size,fstat(fd,&after)==0,s.st_ino==after.st_ino,
              s.st_size==after.st_size,s.st_mtimespec.tv_sec==after.st_mtimespec.tv_sec,
              s.st_mtimespec.tv_nsec==after.st_mtimespec.tv_nsec else { throw FamilyFailure("family_file_changed") }
        return data
    }
    static func hash(_ data: Data) -> String { SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined() }
    static func fileID(_ path: String) throws -> String {
        var s=stat()
        guard lstat(path,&s)==0,(s.st_mode&S_IFMT)==S_IFREG,s.st_mode&0o022==0,
              s.st_uid==getuid() || s.st_uid==0 else { throw FamilyFailure("family_installation_untrusted") }
        return "\(s.st_dev):\(s.st_ino):\(s.st_size):\(s.st_mtimespec.tv_sec):\(s.st_mtimespec.tv_nsec)"
    }
}

@MainActor
final class FamilyNativePort: FamilyWindowPort {
    static let bundles=["kirabridge":"de.netzwerkpunkt.kirabridge","threaddesk":"de.netzwerkpunkt.threaddesk.tauri",
        "4allpass":"de.netzwerkpunkt.fourallpass","tollgate":"de.netzwerkpunkt.tollgate","agent-authority":"de.agentauthority.observer"]
    let registryPath: String
    let registryData: Data
    let registry: [String: Any]
    let paths: [String: String]
    let policyPath: String
    let policySHA: String
    var elements: [String: AXUIElement]=[:]
    var changingGeometry=Set<String>()
    var reopenedWindowIDs: [String:Int]=[:]
    init(home: String=NSHomeDirectory()) throws {
        registryPath=home+"/.config/kirabridge/family-windows.json"
        _=try FamilyFiles.canonical(registryPath)
        registryData=try FamilyFiles.read(registryPath,privateMode:true)
        guard let r=try JSONSerialization.jsonObject(with:registryData) as? [String: Any],
              Set(r.keys)==Set(["schema","enabled","policy","apps"]),
              r["schema"] as? String=="kirabridge.family-windows.v1",r["enabled"] as? Bool==true,
              let policy=r["policy"] as? [String: Any],Set(policy.keys)==Set(["path","sha256","principal","operations"]),
              policy["principal"] as? String=="local",
              policy["operations"] as? [String]==["windows.focus","accessibility.set","apps.launch"],
              let pp=policy["path"] as? String,let sha=policy["sha256"] as? String,
              sha.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,
              let apps=r["apps"] as? [String: [String: String]],Set(apps.keys)==Set(Self.bundles.keys) else {
            throw FamilyFailure("family_registry_invalid")
        }
        var registered: [String:String]=[:]
        for (product,item) in apps {
            guard Set(item.keys)==Set(["path","bundle_id"]),item["bundle_id"]==Self.bundles[product],
                  let path=item["path"],path.hasSuffix(".app") else { throw FamilyFailure("family_registry_invalid") }
            registered[product]=try FamilyFiles.canonical(path)
        }
        guard Set(registered.values).count==5 else { throw FamilyFailure("family_registry_invalid") }
        paths=registered;registry=r;policyPath=try FamilyFiles.canonical(pp);policySHA=sha
        try self.policy()
    }
    func policy() throws {
        guard try FamilyFiles.read(registryPath,privateMode:true)==registryData,
              try FamilyFiles.hash(FamilyFiles.read(policyPath,limit:2*1024*1024))==policySHA else {
            throw FamilyFailure("family_policy_changed")
        }
    }
    func registeredBundle(_ product: String) throws -> (String,String,String) {
        guard let path=paths[product],let expected=Self.bundles[product] else { throw FamilyFailure("family_target_invalid") }
        let data=try FamilyFiles.read(path+"/Contents/Info.plist")
        guard let p=try PropertyListSerialization.propertyList(from:data,format:nil) as? [String:Any],
              p["CFBundleIdentifier"] as? String==expected,let executable=p["CFBundleExecutable"] as? String,
              !executable.isEmpty,!executable.contains("/"),executable != ".",executable != ".." else {
            throw FamilyFailure("family_installation_invalid")
        }
        let exe=try FamilyFiles.canonical(path+"/Contents/MacOS/"+executable)
        return (path,exe,try FamilyFiles.hash(data)+":"+FamilyFiles.fileID(exe))
    }
    func destination(_ product: String) throws { _=try registeredBundle(product) }
    func identity(_ product: String) throws -> FamilyIdentity? {
        guard let expectedPath=paths[product],let bundle=Self.bundles[product] else { throw FamilyFailure("family_target_invalid") }
        let apps=NSRunningApplication.runningApplications(withBundleIdentifier:bundle).filter {
            !$0.isTerminated && Self.isRegisteredCandidate(path:$0.bundleURL?.path,
                regular:$0.activationPolicy == .regular,pid:$0.processIdentifier,
                expectedPath:expectedPath,worker:getpid())
        }
        guard apps.count<=1 else { throw FamilyFailure("family_multiple_instances") }
        guard let app=apps.first else { return nil }
        let (path,exe,revision)=try registeredBundle(product)
        let before=try SystemServices.kernelRecord(app.processIdentifier)
        guard Self.processMatches(before,observedExecutable:SystemServices.codeExecutablePath(app.processIdentifier),expectedExecutable:exe),
              app.bundleURL?.path==path,app.executableURL?.path==exe,
              try SystemServices.kernelRecord(app.processIdentifier)==before else { throw FamilyFailure("family_identity_changed") }
        return FamilyIdentity(product:product,pid:before.pid,start:before.start,uid:before.uid,path:path,
                              executable:exe,installation:revision)
    }
    static func isRegisteredCandidate(path: String?,regular: Bool,pid: Int32,expectedPath: String,worker: Int32) -> Bool {
        regular && pid>1 && pid != worker && path==expectedPath
    }
    static func processMatches(_ record: SystemServices.Record, observedExecutable: String?,expectedExecutable: String) -> Bool {
        record.uid==getuid() && record.realUID==getuid() && record.savedUID==getuid() && !record.tty &&
        observedExecutable.flatMap(SystemControl.canonicalExecutablePath)==expectedExecutable
    }
    func validate(_ app: FamilyIdentity) throws {
        guard try identity(app.product)==app else { throw FamilyFailure("family_identity_changed") }
    }
    func source(_ pid: Int32, _ start: String?) throws -> FamilyIdentity {
        guard pid>1,pid != getpid() else { throw FamilyFailure("family_source_invalid") }
        for product in FamilyWindowBroker.products {
            if let app=try identity(product),app.pid==pid {
                guard start==nil || app.start==start else { throw FamilyFailure("family_source_changed") }
                return app
            }
        }
        throw FamilyFailure("family_source_unregistered")
    }
    func caller(pid: Int32, start: String?) throws -> FamilyIdentity {
        let app=try source(pid,start)
        return try Self.callerChain(app,first:getppid(),read:SystemServices.kernelRecord)
    }
    static func callerChain(_ app: FamilyIdentity,first: Int32,read: (Int32) throws -> SystemServices.Record) throws -> FamilyIdentity {
        // The source must really own this native CLI call, not merely be another
        // same-UID process named by a web request. No argv/environment is read.
        var current=first,seen=Set<Int32>()
        for _ in 0..<12 {
            guard current>1,seen.insert(current).inserted else { break }
            let record=try read(current)
            guard record.uid==getuid(),record.realUID==getuid(),record.savedUID==getuid() else { throw FamilyFailure("family_caller_uid") }
            if current==app.pid {
                guard record.start==app.start else { throw FamilyFailure("family_source_changed") }
                return app
            }
            current=record.parent
        }
        throw FamilyFailure("family_caller_not_native_source")
    }
    func running(_ app: FamilyIdentity) throws -> NSRunningApplication {
        try validate(app)
        guard let value=NSRunningApplication(processIdentifier:app.pid),!value.isTerminated else { throw FamilyFailure("family_identity_changed") }
        return value
    }
    func element(_ app: FamilyIdentity, _ window: FamilyWindow) throws -> AXUIElement {
        guard let value=try self.window(app),value.token==window.token,let e=elements[value.token] else {
            throw FamilyFailure("family_window_changed")
        }
        return e
    }
    static func retainedMainID(_ ids: [Int]) throws -> Int {
        guard ids.count==1,ids[0]>0 else { throw FamilyFailure("family_reopen_main_unknown",unknown:true) }
        return ids[0]
    }
    static func checkRetainedMain(_ expected: Int, _ current: [Int]) throws {
        guard try retainedMainID(current)==expected else { throw FamilyFailure("family_reopen_window_changed",unknown:true) }
    }
    func retainedWindowIDs(_ identity: FamilyIdentity) throws -> [Int] {
        try validate(identity)
        guard let rows=CGWindowListCopyWindowInfo([.optionAll,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] else {
            throw FamilyFailure("family_inventory_unavailable")
        }
        return rows.filter { ($0[kCGWindowOwnerPID as String] as? Int)==Int(identity.pid) &&
            ($0[kCGWindowLayer as String] as? Int)==0 }.compactMap { $0[kCGWindowNumber as String] as? Int }
    }
    func window(_ identity: FamilyIdentity) throws -> FamilyWindow? {
        let app=try running(identity)
        let all=try SystemBridge.axWindows(app)
        if all.isEmpty { return nil }
        guard all.count==1 else { throw FamilyFailure("family_window_ambiguous") }
        let w=all[0]
        if let expected=reopenedWindowIDs[identity.product] { try Self.checkRetainedMain(expected,retainedWindowIDs(identity)) }
        guard SystemBridge.attribute(w,kAXSubroleAttribute) as? String==kAXStandardWindowSubrole,
              SystemBridge.attribute(w,kAXModalAttribute) as? Bool==false,
              (SystemBridge.attribute(w,"AXSheets") as? [AXUIElement] ?? []).isEmpty,
              SystemBridge.attribute(w,"AXFullScreen") as? Bool != true else { throw FamilyFailure("family_modal_or_fullscreen") }
        let children=SystemBridge.attribute(w,kAXChildrenAttribute) as? [AXUIElement] ?? []
        guard children.count<=512,!children.contains(where: { SystemBridge.attribute($0,kAXRoleAttribute) as? String==kAXSheetRole }) else {
            throw FamilyFailure("family_modal_or_fullscreen")
        }
        var p=CGPoint.zero,s=CGSize.zero
        guard let pv=SystemBridge.attribute(w,kAXPositionAttribute),CFGetTypeID(pv)==AXValueGetTypeID(),
              AXValueGetValue(unsafeBitCast(pv,to:AXValue.self),.cgPoint,&p),
              let sv=SystemBridge.attribute(w,kAXSizeAttribute),CFGetTypeID(sv)==AXValueGetTypeID(),
              AXValueGetValue(unsafeBitCast(sv,to:AXValue.self),.cgSize,&s) else { throw FamilyFailure("family_geometry_unavailable") }
        let rect=FamilyRect(x:p.x,y:p.y,width:s.width,height:s.height)
        guard rect.valid else { throw FamilyFailure("family_geometry_invalid") }
        let token=elements.first { CFEqual($0.value,w) }?.key ?? UUID().uuidString
        elements[token]=w
        guard let rows=CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] else { throw FamilyFailure("family_inventory_unavailable") }
        let visible=rows.filter { ($0[kCGWindowOwnerPID as String] as? Int)==Int(identity.pid) &&
            ($0[kCGWindowLayer as String] as? Int)==0 && ($0[kCGWindowAlpha as String] as? Double ?? 1)>0 }
        guard visible.count<=1 else { throw FamilyFailure("family_window_ambiguous") }
        var coherent=true
        if let row=visible.first {
            guard let b=row[kCGWindowBounds as String] as? [String:Any],
                  let x=b["X"] as? Double,let y=b["Y"] as? Double,
                  let width=b["Width"] as? Double,let height=b["Height"] as? Double else {
                throw FamilyFailure("family_window_inventory_mismatch")
            }
            coherent=rect.near(FamilyRect(x:x,y:y,width:width,height:height))
            if !coherent && !changingGeometry.contains(identity.product) {
                throw FamilyFailure("family_window_inventory_mismatch")
            }
        }
        // On-screen inventory must converge after resize/hide. An app's hidden
        // Boolean alone is not evidence that its window disappeared on screen.
        return FamilyWindow(token:token,bounds:rect,visible:!visible.isEmpty && coherent)
    }
    func invisible(_ identity: FamilyIdentity) throws -> Bool {
        try validate(identity)
        guard let rows=CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] else {
            throw FamilyFailure("family_inventory_unavailable")
        }
        return !rows.contains { ($0[kCGWindowOwnerPID as String] as? Int)==Int(identity.pid) &&
            ($0[kCGWindowLayer as String] as? Int)==0 && ($0[kCGWindowAlpha as String] as? Double ?? 1)>0 }
    }
    func screens() throws -> [FamilyRect] {
        guard let primary=NSScreen.screens.first else { throw FamilyFailure("family_display_unavailable") }
        // AX/CG outer window coordinates are logical desktop points from the
        // top-left; NSScreen visibleFrame uses a bottom-left AppKit origin.
        return NSScreen.screens.map { let r=$0.visibleFrame
            return FamilyRect(x:r.minX,y:primary.frame.maxY-r.maxY,width:r.width,height:r.height) }
    }
    func launch(_ product: String, check: () throws -> Void) async throws -> FamilyIdentity {
        _=try registeredBundle(product)
        guard try identity(product)==nil else { throw FamilyFailure("family_roster_changed") }
        try check()
        let scope=try await FamilyPathScope.authorize(target:product,path:paths[product]!,policyPath:policyPath,
            policySHA:policySHA,registrySHA:FamilyFiles.hash(registryData))
        try check()
        _=try registeredBundle(product)
        try FamilyPathScope.revalidate(scope,path:paths[product]!)
        let configuration=NSWorkspace.OpenConfiguration()
        configuration.activates=false;configuration.createsNewApplicationInstance=false
        let app: NSRunningApplication=try await withCheckedThrowingContinuation { continuation in
            NSWorkspace.shared.openApplication(at:URL(fileURLWithPath:paths[product]!),configuration:configuration) { app,_ in
                if let app=app { continuation.resume(returning:app) }
                else { continuation.resume(throwing:FamilyFailure("family_launch_unknown",unknown:true)) }
            }
        }
        try policy()
        guard let exact=try identity(product),exact.pid==app.processIdentifier else { throw FamilyFailure("family_launch_unknown",unknown:true) }
        return exact
    }
    func reopen(_ expected: FamilyIdentity, check: () throws -> Void) async throws {
        try validate(expected);_=try registeredBundle(expected.product)
        // With no AX handle, require the one retained WindowServer main-window
        // identity before Reopen. No retained/ambiguous handle means UNKNOWN,
        // not permission to create or silently adopt a fresh document/window.
        let retained=try Self.retainedMainID(retainedWindowIDs(expected))
        try check()
        let scope=try await FamilyPathScope.authorize(target:expected.product,path:expected.path,policyPath:policyPath,
            policySHA:policySHA,registrySHA:FamilyFiles.hash(registryData))
        try check()
        try validate(expected)
        try Self.checkRetainedMain(retained,retainedWindowIDs(expected))
        try FamilyPathScope.revalidate(scope,path:expected.path)
        let configuration=NSWorkspace.OpenConfiguration()
        configuration.activates=false;configuration.createsNewApplicationInstance=false
        let app: NSRunningApplication=try await withCheckedThrowingContinuation { continuation in
            NSWorkspace.shared.openApplication(at:URL(fileURLWithPath:expected.path),configuration:configuration) { app,_ in
                if let app=app { continuation.resume(returning:app) }
                else { continuation.resume(throwing:FamilyFailure("family_reopen_unknown",unknown:true)) }
            }
        }
        // LaunchServices must return the original registered process. A changed
        // PID/start or another installation is UNKNOWN, never silently adopted.
        try validate(expected)
        guard app.processIdentifier==expected.pid else { throw FamilyFailure("family_reopen_unknown",unknown:true) }
        try Self.checkRetainedMain(retained,retainedWindowIDs(expected))
        reopenedWindowIDs[expected.product]=retained
    }
    func bounds(_ app: FamilyIdentity, _ window: FamilyWindow, _ rect: FamilyRect, check: () throws -> Void) throws {
        let e=try element(app,window)
        var size=CGSize(width:rect.width,height:rect.height),point=CGPoint(x:rect.x,y:rect.y)
        try check()
        changingGeometry.insert(app.product)
        guard AXUIElementSetAttributeValue(e,kAXSizeAttribute as CFString,AXValueCreate(.cgSize,&size)!) == .success else { throw FamilyFailure("family_bounds_unknown",unknown:true) }
        try check()
        guard AXUIElementSetAttributeValue(e,kAXPositionAttribute as CFString,AXValueCreate(.cgPoint,&point)!) == .success else { throw FamilyFailure("family_bounds_unknown",unknown:true) }
    }
    func focus(_ identity: FamilyIdentity, _ window: FamilyWindow, check: () throws -> Void) async throws {
        let app=try running(identity),e=try element(identity,window)
        if SystemBridge.attribute(e,kAXMinimizedAttribute) as? Bool==true {
            try check()
            guard AXUIElementSetAttributeValue(e,kAXMinimizedAttribute as CFString,kCFBooleanFalse) == .success else { throw FamilyFailure("family_focus_unknown",unknown:true) }
        }
        if app.isHidden { try check();guard app.unhide() else { throw FamilyFailure("family_focus_unknown",unknown:true) } }
        try check()
        guard AXUIElementPerformAction(e,kAXRaiseAction as CFString) == .success else { throw FamilyFailure("family_focus_unknown",unknown:true) }
        try check()
        guard app.activate(options:[.activateAllWindows,.activateIgnoringOtherApps]) else { throw FamilyFailure("family_focus_unknown",unknown:true) }
        let deadline=ProcessInfo.processInfo.systemUptime+1
        repeat {
            try validate(identity)
            if frontmost()==identity.pid,try self.window(identity)?.visible==true {
                changingGeometry.remove(identity.product)
                return
            }
            try await Task.sleep(nanoseconds:25_000_000)
        } while ProcessInfo.processInfo.systemUptime<deadline
        throw FamilyFailure("family_focus_unknown",unknown:true)
    }
    func hide(_ identity: FamilyIdentity, _ window: FamilyWindow, check: () throws -> Void) async throws {
        let app=try running(identity);_=try element(identity,window)
        if try invisible(identity) { return }
        try check()
        guard app.hide() else { throw FamilyFailure("family_hide_unknown",unknown:true) }
        let deadline=ProcessInfo.processInfo.systemUptime+1
        repeat {
            try validate(identity)
            if try invisible(identity) { return }
            try await Task.sleep(nanoseconds:25_000_000)
        } while ProcessInfo.processInfo.systemUptime<deadline
        throw FamilyFailure("family_hide_unknown",unknown:true)
    }
    func restore(_ app: FamilyIdentity, _ window: FamilyWindow, check: () throws -> Void) async throws {
        try await focus(app,window,check:check)
    }
    func frontmost() -> Int32? { NSWorkspace.shared.frontmostApplication?.processIdentifier }
}

@MainActor
final class FamilyNativeJournal: FamilyWindowJournal {
    let directory: String
    let fd: Int32
    var statePath: String { directory+"/last-operation.json" }
    init(directory: String) throws {
        self.directory=directory
        _=try FamilyFiles.canonical(directory)
        try FileManager.default.createDirectory(atPath:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        var info=stat()
        guard lstat(directory,&info)==0,(info.st_mode&S_IFMT)==S_IFDIR,info.st_uid==getuid(),info.st_mode&0o077==0 else { throw FamilyFailure("family_state_untrusted") }
        fd=open(directory+"/switch.lock",O_CREAT|O_RDWR|O_NOFOLLOW,0o600)
        guard fd>=0 else { throw FamilyFailure("family_lock_unavailable") }
        guard fstat(fd,&info)==0,(info.st_mode&S_IFMT)==S_IFREG,info.st_uid==getuid(),info.st_mode&0o077==0 else { close(fd);throw FamilyFailure("family_state_untrusted") }
        guard flock(fd,LOCK_EX|LOCK_NB)==0 else { close(fd);throw FamilyFailure("family_busy") }
    }
    deinit { flock(fd,LOCK_UN);close(fd) }
    func read() throws -> [String: Any]? { try Self.observation(statePath) }
    static func observation(_ statePath: String) throws -> [String: Any]? {
        var s=stat()
        if lstat(statePath,&s) != 0 { guard errno==ENOENT else { throw FamilyFailure("family_state_unavailable") };return nil }
        guard let data=try JSONSerialization.jsonObject(with:FamilyFiles.read(statePath,privateMode:true)) as? [String:Any] else { throw FamilyFailure("family_state_invalid") }
        return data
    }
    func write(_ value: [String: Any]) throws {
        _=try read()
        let temporary=directory+"/.intent-"+UUID().uuidString
        let file=open(temporary,O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW,0o600)
        guard file>=0 else { throw FamilyFailure("family_state_unavailable") }
        defer { close(file);unlink(temporary) }
        let bytes=try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys])
        try FileHandle(fileDescriptor:file,closeOnDealloc:false).write(contentsOf:bytes)
        guard fsync(file)==0,rename(temporary,statePath)==0 else { throw FamilyFailure("family_state_unavailable") }
        let parent=open(directory,O_RDONLY|O_DIRECTORY|O_NOFOLLOW)
        guard parent>=0 else { throw FamilyFailure("family_state_unavailable") }
        defer { close(parent) }
        guard fsync(parent)==0 else { throw FamilyFailure("family_state_unavailable") }
    }
    func begin(source: FamilyIdentity,target: String) throws -> String {
        if let previous=try read(),!["completed","failed_no_effect"].contains(previous["phase"] as? String ?? "") {
            throw FamilyFailure("family_previous_unknown",unknown:true)
        }
        let operation=UUID().uuidString
        try write(["phase":"prepared","operation_id":operation,"source_identity":source.json,"target":target])
        return operation
    }
    func finish(_ result: [String:Any]) throws { try write(["phase":"completed","receipt":result]) }
    func unknown(_ operation: String) throws {
        var value=try read() ?? [:]
        value["phase"]="unknown";value["operation_id"]=operation
        try write(value)
    }
    func noEffect(_ operation: String) throws { try write(["phase":"failed_no_effect","operation_id":operation]) }
}

@MainActor
enum FamilyWindowNative {
    static func perform(_ operation: String, _ args: [String:Any]) async throws -> [String:Any] {
        do {
            guard SystemBridgeRuntime.principal=="local",Set(args.keys).isSubset(of:["target","source_pid","source_start"]),
                  let target=args["target"] as? String,FamilyWindowBroker.products.contains(target) else { throw FamilyFailure("family_request_invalid") }
            let pid=try SystemBridge.integer(args,"source_pid")
            guard pid>1,pid<=Int(Int32.max),args["source_start"]==nil || args["source_start"] is String else { throw FamilyFailure("family_source_invalid") }
            let port=try FamilyNativePort()
            if operation=="family.window.inspect" {
                let source=try port.source(Int32(pid),args["source_start"] as? String)
                var apps: [[String:Any]]=[]
                for product in FamilyWindowBroker.products {
                    if let app=try port.identity(product) {
                        var row=app.json
                        if let w=try? port.window(app) { row["outer_bounds"]=w.bounds.json;row["visible"]=w.visible }
                        apps.append(row)
                    }
                }
                return ["success":true,"effect":"none","caller_bound":(try? port.caller(pid:Int32(pid),start:source.start)) != nil,
                    "source_identity":source.json,"registered_apps":apps,"accessibility_granted":AXIsProcessTrusted(),
                    "permission_requested":false,"automatic_retry":false,
                    "last_operation":try FamilyNativeJournal.observation(NSHomeDirectory()+"/.local/state/kirabridge/family-windows/last-operation.json") as Any? ?? NSNull(),
                    "display_backing_scales":NSScreen.screens.map(\.backingScaleFactor)]
            }
            guard operation=="family.window.switch" else { throw FamilyFailure("family_request_invalid") }
            _=try port.caller(pid:Int32(pid),start:args["source_start"] as? String)
            let journal=try FamilyNativeJournal(directory:NSHomeDirectory()+"/.local/state/kirabridge/family-windows")
            return try await FamilyWindowBroker(port,journal).switchTo(target,sourcePID:Int32(pid),sourceStart:args["source_start"] as? String)
        } catch let error as FamilyFailure {
            throw SystemBridge.fail(error.code,"Native family operation refused; inspect before retrying",unknown:error.unknown)
        } catch let error as SystemBridgeFailure {
            throw error
        } catch {
            // The broker wraps every error after an attempted effect as UNKNOWN.
            // Remaining decoding/filesystem errors occurred during preflight.
            throw SystemBridge.fail("family_preflight_failed","Family preflight failed",unknown:false)
        }
    }
}

/// Reuse the installed Python PathScope implementation at each URL-open effect.
/// No TOML/root approximation, Store, arbitrary script or browser-supplied path.
@MainActor
enum FamilyPathScope {
    struct Proof { let device: String; let inode: String }
    static func validate(_ data: Data, target: String, path: String, policySHA: String,
                         registrySHA: String) throws -> Proof {
        guard let value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],
              (try? SystemBridge.bool(value,"success"))==true,value["error"]==nil,
              value["execution_outcome_unknown"] as? Bool != true,
              value["target"] as? String==target,value["app_path"] as? String==path,
              value["policy_sha256"] as? String==policySHA,
              value["registry_sha256"] as? String==registrySHA,
              let device=value["directory_device"] as? String,
              let inode=value["directory_inode"] as? String else { throw FamilyFailure("family_path_denied") }
        return Proof(device:device,inode:inode)
    }
    static func revalidate(_ proof: Proof, path: String) throws {
        _=try FamilyFiles.canonical(path)
        var value=stat()
        guard lstat(path,&value)==0,(value.st_mode&S_IFMT)==S_IFDIR,
              String(value.st_dev)==proof.device,String(value.st_ino)==proof.inode else {
            throw FamilyFailure("family_path_changed")
        }
    }
    static func authorize(target: String, path: String, policyPath: String,
                          policySHA: String, registrySHA: String) async throws -> Proof {
        let executable=NSHomeDirectory()+"/.local/bin/kirabridge"
        let args=["--config",policyPath,"--principal","local","family","path-check",target]
        let data=try await Task.detached(priority:.userInitiated) {
            try run(executable:executable,arguments:args)
        }.value
        return try validate(data,target:target,path:path,policySHA:policySHA,registrySHA:registrySHA)
    }
    nonisolated static func run(executable: String,arguments: [String]) throws -> Data {
        let process=Process(),output=Pipe()
        process.executableURL=URL(fileURLWithPath:executable);process.arguments=arguments
        process.standardInput=FileHandle.nullDevice;process.standardOutput=output
        process.standardError=FileHandle.nullDevice
        try process.run()
        try output.fileHandleForWriting.close()
        defer { try? output.fileHandleForReading.close() }
        let deadline=ProcessInfo.processInfo.systemUptime+5
        while process.isRunning && ProcessInfo.processInfo.systemUptime<deadline { usleep(10_000) }
        if process.isRunning {
            // This is only our own read-only path validator, never a GUI app or
            // the persistent native helper. No window effect has been admitted.
            process.terminate();usleep(50_000)
            if process.isRunning { Darwin.kill(process.processIdentifier,SIGKILL) }
            process.waitUntilExit()
            throw FamilyFailure("family_path_check_unavailable")
        }
        process.waitUntilExit()
        // A descendant retaining stdout must not hold the broker open. The
        // completed validator's receipt is bounded; partial output fails closed.
        let fd=output.fileHandleForReading.fileDescriptor
        guard fcntl(fd,F_SETFL,O_NONBLOCK)==0 else { throw FamilyFailure("family_path_check_unavailable") }
        var data=Data(),buffer=[UInt8](repeating:0,count:4096)
        while data.count<=65536 {
            let count=Darwin.read(fd,&buffer,buffer.count)
            if count>0 { data.append(contentsOf:buffer.prefix(count));continue }
            if count==0 || errno==EAGAIN { break }
            if errno==EINTR { continue }
            throw FamilyFailure("family_path_check_unavailable")
        }
        guard process.terminationStatus==0,data.count<=65536 else { throw FamilyFailure("family_path_denied") }
        return data
    }
}

import Foundation
import Darwin

enum FixtureFailure: Error { case assertion(String) }

@MainActor
func check(_ condition: @autoclosure () -> Bool, _ text: String) throws {
    if !condition() { throw FixtureFailure.assertion(text) }
}

@MainActor
func refusal(_ codes: Set<String>, _ body: () throws -> Void) throws {
    do { try body() }
    catch let error as SystemBridgeFailure {
        try check(codes.contains(error.code), "unexpected refusal code")
        try check(!error.effectUnknown, "pure guard invented an effect")
        return
    }
    throw FixtureFailure.assertion("guard accepted an unsafe process; expected \(codes)")
}

@MainActor
func row(_ pid: pid_t, parent: pid_t = 1, uid: uid_t = 501, real: uid_t? = nil,
         saved: uid_t? = nil, name: String = "sleep", path: String? = "/bin/sleep",
         start: String = "1700000000.123456", tty: Bool = false) -> SystemServices.Record {
    SystemServices.Record(pid: pid, parent: parent, uid: uid, realUID: real ?? uid,
        savedUID: saved ?? uid, name: name, path: path, start: start, tty: tty)
}

@MainActor
func acquisitionFixture() throws {
    let old = row(20, path: nil)
    var reads = 0, paths = 0
    let cli = try SystemServices.observedRecord(20, applications: [], kernel: { pid in
        reads += 1; try check(pid == 20, "wrong CLI identity requested"); return old
    }, executable: { _ in paths += 1; return "/must/not/be/queried" })
    try check(reads == 2 && paths == 0 && cli.path == nil, "CLI gained an application path or lost kernel guards")
    let current = row(20, path: nil, start: "1700000001.123456")
    let gui = try SystemServices.observedRecord(20, applications: [20], kernel: { _ in current },
        executable: { pid in paths += 1; return pid == 20 ? "/Applications/New.app/Contents/MacOS/New" : nil })
    try check(gui.start == current.start && gui.path == "/Applications/New.app/Contents/MacOS/New",
              "AppKit PID candidate transferred an old application path/start")
    let denied = try SystemServices.observedRecord(20, applications: [20], kernel: { _ in old },
        executable: { _ in nil })
    try check(denied.path == nil, "Unavailable public code identity invented a path")
    var terminalBefore = row(20, path: nil, tty: true); terminalBefore.terminalDevice = 1
    var terminalAfter = terminalBefore; terminalAfter.terminalDevice = 2
    for changed in [current, row(20, parent: 30, path: nil), row(20, uid: 502, path: nil),
                    row(20, real: 502, path: nil), row(20, saved: 502, path: nil),
                    row(20, name: "replacement", path: nil), row(21, path: nil),
                    row(20, path: nil, tty: true)] {
        var count = 0
        try refusal(["macos_process_changed"]) {
            _ = try SystemServices.observedRecord(20, applications: [20], kernel: { _ in
                count += 1; return count == 1 ? old : changed
            }, executable: { _ in "/Applications/Old.app/Contents/MacOS/Old" })
        }
    }
    var ttyReads = 0
    try refusal(["macos_process_changed"]) {
        _ = try SystemServices.observedRecord(20, applications: [20], kernel: { _ in
            ttyReads += 1; return ttyReads == 1 ? terminalBefore : terminalAfter
        }, executable: { _ in "/Applications/Old.app/Contents/MacOS/Old" })
    }
    var census = 0, maps = 0, rows = 0
    let stable = try SystemServices.acquireSnapshot(census: { census += 1; return [10, 20, 30] },
        applications: { maps += 1; return [20] }, read: { pid, apps in
            rows += 1
            return try SystemServices.observedRecord(pid, applications: apps,
                kernel: { row($0, path: nil) }, executable: { _ in "/Applications/One.app/Contents/MacOS/One" })
        })
    try check(census == 2 && maps == 1 && rows == 3, "Stable census repeated application discovery per PID")
    try check(stable.records.filter { $0.path != nil }.map { $0.pid } == [20], "CLI path scope expanded")
    census = 0; maps = 0
    let sequences: [[pid_t]] = [[10, 20], [10, 30], [10, 30], [10, 30]]
    let refreshed = try SystemServices.acquireSnapshot(census: {
        defer { census += 1 }; return sequences[census]
    }, applications: { maps += 1; return maps == 1 ? [20] : [30] }, read: { pid, apps in
        row(pid, path: apps.contains(pid) ? "/Applications/Current.app/Contents/MacOS/Current" : nil)
    })
    try check(census == 4 && maps == 2 && refreshed.records.map { $0.pid } == [10, 30],
              "Changed census reused stale rows or failed to reacquire")
    try check(refreshed.records.first(where: { $0.pid == 30 })?.path != nil,
              "Changed census reused the preceding application map")
    census = 0; maps = 0
    try refusal(["macos_process_changed"]) {
        _ = try SystemServices.acquireSnapshot(census: {
            census += 1; return census % 2 == 1 ? [10] : [10, 20]
        }, applications: { maps += 1; return [] }, read: { pid, _ in row(pid, path: nil) })
    }
    try check(census == 6 && maps == 3, "Census acquisition exceeded three read-only attempts")
    census = 0; maps = 0
    let buffered = try SystemServices.acquireSnapshot(census: {
        census += 1
        if census == 1 { throw SystemServices.failure("macos_process_changed", "synthetic census buffer churn") }
        return [10]
    }, applications: { maps += 1; return [] }, read: { pid, _ in row(pid, path: nil) })
    try check(census == 3 && maps == 1 && buffered.records.count == 1,
              "Read-only census buffer churn did not reacquire once")
    census = 0; maps = 0
    try refusal(["macos_process_unavailable"]) {
        _ = try SystemServices.acquireSnapshot(census: {
            census += 1; throw SystemServices.failure("macos_process_unavailable", "synthetic unavailable inventory")
        }, applications: { maps += 1; return [] }, read: { pid, _ in row(pid, path: nil) })
    }
    try check(census == 1 && maps == 0, "Non-census failure was silently retried")
    for code in ["macos_process_unavailable", "macos_process_changed"] {
        census = 0; maps = 0
        let incomplete = try SystemServices.acquireSnapshot(census: { census += 1; return [10, 20] },
            applications: { maps += 1; return [] }, read: { pid, _ in
                if pid == 20 { throw SystemServices.failure(code, "synthetic missing or changed row") }
                return row(pid, path: nil)
            })
        try check(incomplete.records.map { $0.pid } == [10] && incomplete.unavailable == [20],
                  "Missing process metadata was silently accepted as complete")
        try check(census == 2 && maps == 1, "Individual identity failure retried a stable census")
    }
}

@MainActor
func runFixture() throws {
    try acquisitionFixture()
    let worker = row(10, parent: 11, name: "KiraBridge", path: "/private/KiraBridge")
    let core = row(11, parent: 12, name: "Python", path: "/opt/python3")
    let ancestor = row(12, name: "Supervisor", path: "/private/Supervisor")
    let target = row(20, parent: 21)
    let supervisor = row(21, name: "Launcher", path: "/private/Launcher")
    let base = [worker, core, ancestor, target, supervisor]
    func guardTarget(_ selected: SystemServices.Record, _ records: [SystemServices.Record], uid: uid_t = 501) throws {
        try SystemServices.authorizeSignal(selected, records: records, workerPID: 10, corePID: 11, ownUID: uid)
    }
    try guardTarget(target, base)
    for selected in [worker, core, ancestor] {
        try refusal(["macos_process_protected"]) { try guardTarget(selected, base) }
    }
    for changed in [row(20, parent: 21, uid: 502), row(20, parent: 21, real: 0), row(20, parent: 21, saved: 0)] {
        try refusal(["macos_process_owner_required"]) { try guardTarget(changed, [worker, core, ancestor, changed, supervisor]) }
    }
    try refusal(["macos_process_owner_required"]) { try guardTarget(target, base, uid: 0) }
    for changed in [row(20, parent: 11), row(20, parent: 21, tty: true),
                    row(20, parent: 21, name: "codex"), row(20, parent: 21, path: "/usr/bin/codex"),
                    row(20, parent: 21, name: "helper", path: "/Applications/Codex.app/Contents/Helpers/helper"),
                    row(20, parent: 21, name: "node", path: "/usr/bin/node"),
                    row(20, parent: 21, path: nil)] {
        try refusal(["macos_process_route_required"]) { try guardTarget(changed, [worker, core, ancestor, changed, supervisor]) }
    }
    let shell = row(21, name: "zsh", path: "/bin/zsh")
    try refusal(["macos_process_route_required"]) { try guardTarget(target, [worker, core, ancestor, target, shell]) }
    let childAgent = row(22, parent: 20, name: "codex", path: "/bin/codex")
    try refusal(["macos_process_route_required"]) { try guardTarget(target, base + [childAgent]) }
    let ttyChild = row(22, parent: 20, tty: true)
    try refusal(["macos_process_route_required"]) { try guardTarget(target, base + [ttyChild]) }
    let unknownChild = row(22, parent: 20, path: nil)
    try refusal(["macos_process_observation"]) { try guardTarget(target, base + [unknownChild]) }
    let reusedParentChild = row(22, parent: 20, start: "1699999999.123456")
    try refusal(["macos_process_changed"]) { try guardTarget(target, base + [reusedParentChild]) }
    try refusal(["macos_process_observation"]) { try guardTarget(target, [worker, core, ancestor, target]) }
    let cyclic = row(21, parent: 20)
    try refusal(["macos_process_observation"]) { try guardTarget(target, [worker, core, ancestor, target, cyclic]) }
    let parentReused = row(21, name: "new-parent", start: "1700000001.123456")
    try refusal(["macos_process_changed"]) { try guardTarget(target, [worker, core, ancestor, target, parentReused]) }
    let missingBoundary = row(21, parent: 0)
    try refusal(["macos_process_observation"]) { try guardTarget(target, [worker, core, ancestor, target, missingBoundary]) }
    try refusal(["macos_process_observation"]) { try guardTarget(target, base + [target]) }
    try refusal(["macos_process_changed"]) { try guardTarget(row(20, parent: 21, start: "1700000001.123456"), base) }
    var deep = base
    for pid in stride(from: 280, through: 22, by: -1) { deep.append(row(pid_t(pid), parent: pid_t(pid == 22 ? 20 : pid - 1))) }
    try refusal(["macos_process_limit"]) { try guardTarget(target, deep) }
    let foreign = row(30, uid: 502, name: "other-user-process", path: nil)
    let observation = SystemServices.Snapshot(records: [foreign, target, worker], unavailable: [999])
    let first = try SystemServices.page(observation, includeSystem: false, uid: 501, offset: 0, limit: 1, expectedRevision: nil)
    try check(first["total"] as? Int == 2, "default scope leaked other UID")
    try check(first["unavailable_pids"] == nil, "default scope exposed unknown-owner PIDs")
    let firstRows = first["processes"] as! [[String: Any]]
    try check(firstRows[0]["pid"] as? Int == 10, "page not sorted")
    let revision = first["revision"] as! String
    let second = try SystemServices.page(observation, includeSystem: false, uid: 501, offset: 1, limit: 1, expectedRevision: revision)
    try check((second["processes"] as! [[String: Any]])[0]["pid"] as? Int == 20, "continuation skipped PID")
    try check(second["eof"] as? Bool == true, "EOF missing")
    try refusal(["macos_process_changed"]) {
        _ = try SystemServices.page(observation, includeSystem: false, uid: 501, offset: 1, limit: 1, expectedRevision: nil)
    }
    try refusal(["macos_process_changed"]) {
        _ = try SystemServices.page(observation, includeSystem: false, uid: 501, offset: 1, limit: 1, expectedRevision: String(repeating: "a", count: 64))
    }
    let all = try SystemServices.page(observation, includeSystem: true, uid: 501, offset: 0, limit: 500, expectedRevision: nil)
    try check(all["total"] as? Int == 3 && all["observation_complete"] as? Bool == false, "all-system scope overstated completeness")
    try check(all["unavailable_pids"] as? [Int] == [999], "missing observations not explicit")
    var info = kinfo_proc(); info.kp_proc.p_un.__p_starttime.tv_sec = 1700000000; info.kp_proc.p_un.__p_starttime.tv_usec = 7
    try check(SystemServices.started(info) == "1700000000.000007", "start microseconds lost")
    // The only real metadata read is this short-lived owned fixture itself.
    let actual = try SystemServices.read(getpid())
    try check(actual.pid == getpid() && actual.uid == geteuid() && actual.parent == getppid(), "public sysctl self binding failed")
    try check(actual.json["path_available"] as? Bool == (actual.path != nil), "public path availability is not explicit")
    if let path = SystemServices.codeExecutablePath(getpid()) {
        let actualPath = URL(fileURLWithPath: path).resolvingSymlinksInPath().path
        let fixturePath = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().path
        try check(actualPath == fixturePath, "public Security self path does not identify this exact fixture executable")
    }
    print("native service acquisition/lineage/pagination/owned-self-metadata checks passed; signals_sent=0")
}

Task { @MainActor in
    do { try runFixture(); exit(0) }
    catch { print("native process fixture failed: \(error)"); exit(1) }
}
RunLoop.main.run()

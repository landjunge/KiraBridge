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
    let stable = try SystemServices.acquireSnapshot(census: {
        census += 1
        return SystemServices.Snapshot(records: [row(10, path: nil), old, row(30, path: nil)], unavailable: [])
    }, applications: { maps += 1; return [20] }, read: { pid, apps in
        rows += 1
        return try SystemServices.observedRecord(pid, applications: apps,
            kernel: { row($0, path: nil) }, executable: { _ in "/Applications/One.app/Contents/MacOS/One" })
    })
    try check(census == 1 && maps == 1 && rows == 1, "Bulk inventory still performs per-PID kernel observations")
    try check(stable.records.filter { $0.path != nil }.map { $0.pid } == [20], "CLI path scope expanded")
    for code in ["macos_process_changed", "macos_process_unavailable"] {
        let historical = try SystemServices.acquireSnapshot(census: {
            SystemServices.Snapshot(records: [old], unavailable: [])
        }, applications: { [20] }, read: { _, _ in throw SystemServices.failure(code, "enrichment churn") })
        try check(historical.records == [old] && historical.unavailable.isEmpty && historical.pathUnavailable == [20],
                  "Optional path churn erased a kernel row or invented full path coverage")
    }
    let changed = try SystemServices.acquireSnapshot(census: {
        SystemServices.Snapshot(records: [old], unavailable: [99])
    }, applications: { [20] }, read: { _, _ in current.withPath("/Applications/New.app/Contents/MacOS/New") })
    try check(changed.records == [old] && changed.unavailable == [99] && changed.pathUnavailable == [20],
              "Read-only path enrichment transferred a reused PID path or hid missing kernel metadata")
    census = 0; maps = 0
    let buffered = try SystemServices.acquireSnapshot(census: {
        census += 1
        if census == 1 { throw SystemServices.failure("macos_process_changed", "synthetic bounded buffer churn") }
        return SystemServices.Snapshot(records: [old], unavailable: [])
    }, applications: { maps += 1; return [] }, read: { _, _ in throw FixtureFailure.assertion("CLI read") })
    try check(census == 2 && maps == 1 && buffered.records == [old], "Bounded buffer retry changed the observation")
    census = 0
    try refusal(["macos_process_changed"]) {
        _ = try SystemServices.acquireSnapshot(census: {
            census += 1; throw SystemServices.failure("macos_process_changed", "buffer churn")
        }, applications: { [] }, read: { _, _ in old })
    }
    try check(census == 3, "Read-only acquisition exceeded three attempts")
    census = 0
    try refusal(["macos_process_unavailable"]) {
        _ = try SystemServices.acquireSnapshot(census: {
            census += 1; throw SystemServices.failure("macos_process_unavailable", "bad header")
        }, applications: { [] }, read: { _, _ in old })
    }
    try check(census == 1, "Invalid census was retried as ordinary churn")
    var raw = kinfo_proc()
    raw.kp_proc.p_pid = 20; raw.kp_eproc.e_ppid = 1
    raw.kp_eproc.e_ucred.cr_uid = 501; raw.kp_eproc.e_pcred.p_ruid = 501; raw.kp_eproc.e_pcred.p_svuid = 501
    raw.kp_proc.p_un.__p_starttime.tv_sec = 1700000000
    raw.kp_proc.p_un.__p_starttime.tv_usec = 7
    raw.kp_eproc.e_tdev = -1
    let decoded = try SystemServices.decodeCensus([kinfo_proc(), raw], workerPID: 20)
    try check(decoded.records.count == 1 && decoded.records[0].start == "1700000000.000007"
              && decoded.records[0].uid == 501 && decoded.records[0].parent == 1,
              "Bulk census lost kernel identity fields")
    try refusal(["macos_process_unavailable"]) { _ = try SystemServices.decodeCensus([raw, raw], workerPID: 20) }
    try refusal(["macos_process_unavailable"]) { _ = try SystemServices.decodeCensus([raw], workerPID: 21) }
    raw.kp_proc.p_un.__p_starttime.tv_usec = 1000000
    let malformed = try SystemServices.decodeCensus([raw], workerPID: 20)
    try check(malformed.records.isEmpty && malformed.unavailable == [20], "Malformed row disappeared from completeness")
}

@MainActor
func guardedAcquisitionFixture() throws {
    let launchd = row(1, parent: 0, uid: 0, name: "launchd", path: nil, start: "1600000000.000000")
    let worker = row(10, parent: 11, name: "Worker", path: nil)
    let core = row(11, parent: 12, name: "Core", path: nil)
    let ancestor = row(12, name: "Supervisor", path: nil)
    let target = row(20, parent: 21, name: "Fixture", path: "/Applications/Fixture.app/Contents/MacOS/Fixture")
    let parent = row(21, name: "Launcher", path: "/Applications/Launcher.app/Contents/MacOS/Launcher")
    let child = row(22, parent: 20, name: "Child", path: "/Applications/Child.app/Contents/MacOS/Child")
    let irrelevant = row(90, name: "background", path: nil)
    let base = [launchd, worker, core, ancestor, target, parent, child]
    func acquire(_ before: [SystemServices.Record], _ after: [SystemServices.Record],
                 missing: [pid_t] = [], lastMissing: [pid_t] = [], pathChange: Bool = false,
                 pathUnknown: Bool = false) throws -> (SystemServices.Snapshot, Int, Int) {
        var censuses = 0, reads = 0
        let table = Dictionary(uniqueKeysWithValues: before.map { ($0.pid, $0) })
        let result = try SystemServices.acquireGuardedSnapshot(targetPID: 20, workerPID: 10, corePID: 11,
            census: {
                censuses += 1
                return SystemServices.Snapshot(records: (censuses % 2 == 1 ? before : after).map { $0.kernel },
                    unavailable: censuses % 2 == 1 ? missing : lastMissing)
            }, applications: { Set(before.filter { $0.path != nil }.map { $0.pid }) }, read: { pid, _ in
                reads += 1
                guard let row = table[pid] else { throw FixtureFailure.assertion("unrelated process path queried") }
                if pathUnknown { return row.kernel }
                return pathChange && reads % 2 == 0 ? row.withPath("/Applications/Changed.app/Contents/MacOS/Changed") : row
            })
        return (result, censuses, reads)
    }
    for pair in [(base + [irrelevant], base), (base, base + [irrelevant])] {
        let (safe, censuses, reads) = try acquire(pair.0, pair.1)
        try check(censuses == 2 && reads == 6 && safe.records.map { $0.pid } == [1, 10, 11, 12, 20, 21, 22],
                  "Unrelated birth/death blocked a stable relevant graph or gained a path")
        try check(safe.records.first(where: { $0.pid == 20 }) == target, "Bound target path lost")
    }
    var ttyOne = child; ttyOne.terminalDevice = 1
    var ttyTwo = child; ttyTwo.terminalDevice = 2
    let replacements = [
        row(20, parent: 21, start: "1700000001.123456"), row(20, parent: 21, uid: 502),
        row(20, parent: 21, real: 502), row(20, parent: 21, saved: 502),
        row(20, parent: 21, name: "replacement"), row(20, parent: 21, tty: true),
        row(20, parent: 12), row(11, parent: 12, start: "1700000001.123456"),
        row(11, parent: 1), row(11, parent: 12, uid: 502), row(11, parent: 12, name: "changedCore"),
        row(21, start: "1700000001.123456"),
        row(22, parent: 21), row(22, parent: 20, start: "1700000001.123456"),
    ]
    for replacement in replacements {
        let after = base.map { $0.pid == replacement.pid ? replacement : $0 }
        try refusal(["macos_process_changed", "macos_process_observation"]) { _ = try acquire(base, after) }
    }
    try refusal(["macos_process_changed"]) { _ = try acquire(base, base + [row(23, parent: 20)]) }
    try refusal(["macos_process_changed"]) { _ = try acquire(base, base.filter { $0.pid != 22 }) }
    try refusal(["macos_process_changed"]) { _ = try acquire(base.map { $0.pid == 22 ? ttyOne : $0 }, base.map { $0.pid == 22 ? ttyTwo : $0 }) }
    try refusal(["macos_process_changed"]) { _ = try acquire(base, base, pathChange: true) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base, base, pathUnknown: true) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base, base, missing: [99]) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base, base, lastMissing: [99]) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base, base.filter { $0.pid != 10 }) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base, base.filter { $0.pid != 11 }) }
    let unknownName = base.map { $0.pid == 22 ? row(22, parent: 20, name: "") : $0 }
    try refusal(["macos_process_observation"]) { _ = try acquire(unknownName, unknownName) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base.filter { $0.pid != 1 }, base) }
    try refusal(["macos_process_observation"]) { _ = try acquire(base.filter { $0.pid != 21 }, base) }
    var calls = 0, pathReads = 0
    try refusal(["macos_process_changed"]) {
        _ = try SystemServices.acquireGuardedSnapshot(targetPID: 20, workerPID: 10, corePID: 11,
            census: {
                calls += 1
                return SystemServices.Snapshot(records: calls % 2 == 1 ? base : base + [row(23, parent: 20)], unavailable: [])
            }, applications: { [] }, read: { _, _ in pathReads += 1; return target })
    }
    try check(calls == 6 && pathReads == 0, "Relevant churn exceeded three pure read attempts")
    print("bulk interval and relevant-graph churn guards passed; effects_attempted=0")
}

@MainActor
func runFixture() throws {
    try acquisitionFixture()
    try guardedAcquisitionFixture()
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
    try check(first["observation_atomic"] as? Bool == false
              && first["kernel_observation_complete"] as? Bool == false,
              "Read-only interval claimed an atomic or complete kernel observation")
    try check((first["kernel_revision"] as? String)?.count == 64, "Kernel revision is absent")
    let noPath = SystemServices.Snapshot(records: [target.kernel], unavailable: [], pathUnavailable: [20])
    let noPathPage = try SystemServices.page(noPath, includeSystem: false, uid: 501, offset: 0, limit: 1, expectedRevision: nil)
    try check(noPathPage["kernel_observation_complete"] as? Bool == true
              && noPathPage["path_enrichment_complete"] as? Bool == false
              && noPathPage["path_unavailable_count"] as? Int == 1,
              "Optional path failure misreported kernel/path completeness")
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

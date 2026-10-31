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
func runFixture() throws {
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
    print("native service primitive/lineage/pagination/self-metadata checks passed; signals_sent=0")
}

Task { @MainActor in
    do { try runFixture(); exit(0) }
    catch { print("native process fixture failed: \(error)"); exit(1) }
}
RunLoop.main.run()

import Foundation
import AppKit
import Darwin
import CryptoKit

/// Public sysctl process metadata observations. No argv/environment, shell, attachment,
/// process groups, scheduler or automatic retry is part of this interface.
@MainActor
enum SystemServices {
    struct Record: Equatable {
        let pid: pid_t
        let parent: pid_t
        let uid: uid_t
        let realUID: uid_t
        let savedUID: uid_t
        let name: String
        let path: String?
        let start: String
        let tty: Bool
        var json: [String: Any] {
            ["pid": Int(pid), "ppid": Int(parent), "uid": Int(uid), "real_uid": Int(realUID),
             "saved_uid": Int(savedUID), "name": name, "path": path as Any? ?? NSNull(),
             "path_available": path != nil, "start": start, "has_controlling_tty": tty]
        }
    }
    struct Snapshot {
        let records: [Record]
        let unavailable: [pid_t]
    }
    static let protectedNames: Set<String> = [
        "codex", "grok", "grok-cli", "claude", "chatgpt", "gemini", "opencode", "copilot", "aider",
        "zsh", "bash", "sh", "dash", "fish", "tcsh", "csh", "ksh", "nu", "xonsh", "pwsh",
        "login", "sshd", "tmux", "screen", "terminal", "iterm2", "ghostty", "wezterm",
        "wezterm-gui", "kitty", "alacritty", "kirabridge", "codex app", "codex helper",
    ]
    static let signals: [String: Int32] = ["TERM": SIGTERM, "INT": SIGINT, "HUP": SIGHUP, "KILL": SIGKILL]
    static func failure(_ code: String, _ message: String, unknown: Bool = false) -> SystemBridgeFailure {
        SystemBridgeFailure(code: code, message: message, effectUnknown: unknown)
    }
    static func string<T>(_ value: inout T) -> String {
        withUnsafeBytes(of: &value) { bytes in
            String(decoding: bytes.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
    }
    static func started(_ info: kinfo_proc) -> String {
        let time = info.kp_proc.p_un.__p_starttime
        return String(time.tv_sec) + "." + String(format: "%06d", time.tv_usec)
    }
    static func processInfo(_ pid: pid_t) throws -> kinfo_proc {
        var info = kinfo_proc()
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, pid]
        var size = MemoryLayout<kinfo_proc>.size
        guard pid > 0, sysctl(&mib, 4, &info, &size, nil, 0) == 0,
              size == MemoryLayout<kinfo_proc>.size, info.kp_proc.p_pid == pid,
              info.kp_proc.p_un.__p_starttime.tv_sec > 0,
              info.kp_proc.p_un.__p_starttime.tv_usec >= 0,
              info.kp_proc.p_un.__p_starttime.tv_usec < 1000000 else {
            throw failure("macos_process_unavailable", "Exact public process metadata cannot currently be observed")
        }
        return info
    }
    static func read(_ pid: pid_t) throws -> Record {
        var info = try processInfo(pid)
        // Public AppKit identifies GUI application executables. CLI/non-app
        // paths remain unknown: no private libproc or argument/environment read.
        var path: String?
        if let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated,
           app.bundleURL != nil, let executable = app.executableURL,
           executable.isFileURL, executable.path.hasPrefix("/") { path = executable.path }
        var after = try processInfo(pid)
        guard started(info) == started(after), info.kp_eproc.e_ppid == after.kp_eproc.e_ppid,
              info.kp_eproc.e_ucred.cr_uid == after.kp_eproc.e_ucred.cr_uid,
              info.kp_eproc.e_pcred.p_ruid == after.kp_eproc.e_pcred.p_ruid,
              info.kp_eproc.e_pcred.p_svuid == after.kp_eproc.e_pcred.p_svuid,
              info.kp_eproc.e_tdev == after.kp_eproc.e_tdev,
              string(&info.kp_proc.p_comm) == string(&after.kp_proc.p_comm) else {
            throw failure("macos_process_changed", "Process changed during its public metadata observation")
        }
        return Record(pid: pid, parent: info.kp_eproc.e_ppid, uid: info.kp_eproc.e_ucred.cr_uid,
            realUID: info.kp_eproc.e_pcred.p_ruid, savedUID: info.kp_eproc.e_pcred.p_svuid,
            name: string(&info.kp_proc.p_comm), path: path, start: started(info),
            tty: info.kp_eproc.e_tdev != -1)
    }
    static func identifiers() throws -> [pid_t] {
        // Apple QA1123: CTL_KERN/KERN_PROC/KERN_PROC_ALL, bounded size query
        // followed by a metadata-only kinfo_proc snapshot. No KERN_PROCARGS.
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_ALL]
        var needed = 0
        guard sysctl(&mib, 3, nil, &needed, nil, 0) == 0,
              needed > 0, needed <= 64 * 1024 * 1024,
              needed % MemoryLayout<kinfo_proc>.stride == 0 else {
            throw failure("macos_process_unavailable", "Public process inventory size is unavailable or exceeds budget")
        }
        let estimate = needed / MemoryLayout<kinfo_proc>.stride
        guard estimate < 100000 else { throw failure("macos_process_limit", "Process inventory exceeds observation budget") }
        let capacity = min(100000, estimate + 1024)
        var rows = [kinfo_proc](repeating: kinfo_proc(), count: capacity)
        var size = capacity * MemoryLayout<kinfo_proc>.stride
        let status = rows.withUnsafeMutableBufferPointer { buffer in
            sysctl(&mib, 3, buffer.baseAddress, &size, nil, 0)
        }
        guard status == 0, size > 0, size <= capacity * MemoryLayout<kinfo_proc>.stride,
              size % MemoryLayout<kinfo_proc>.stride == 0 else {
            throw failure("macos_process_changed", "Process inventory changed or could not be observed within its bounded buffer")
        }
        let count = size / MemoryLayout<kinfo_proc>.stride
        let pids = rows.prefix(count).map { $0.kp_proc.p_pid }.filter { $0 > 0 }
        let result = Array(Set(pids)).sorted()
        guard result.count == pids.count, result.contains(getpid()) else {
            throw failure("macos_process_unavailable", "Calling worker is absent or process identities are duplicated")
        }
        return result
    }
    static func snapshot() throws -> Snapshot {
        let pids = try identifiers()
        var records: [Record] = [], unavailable: [pid_t] = []
        for pid in pids {
            do { records.append(try read(pid)) }
            catch { unavailable.append(pid) }
        }
        guard try identifiers() == pids else { throw failure("macos_process_changed", "Process inventory changed during observation; refresh") }
        return Snapshot(records: records, unavailable: unavailable)
    }
    static func hash(_ object: Any) throws -> String {
        SHA256.hash(data: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])).map { String(format: "%02x", $0) }.joined()
    }
    static func page(_ observation: Snapshot, includeSystem: Bool, uid: uid_t, offset: Int,
                     limit: Int, expectedRevision: String?) throws -> [String: Any] {
        guard offset >= 0, offset <= 100000, limit > 0, limit <= 500 else {
            throw failure("invalid_arguments", "Process page bounds are invalid")
        }
        let visible = observation.records.filter { includeSystem || $0.uid == uid }.sorted { $0.pid < $1.pid }
        let revision = try hash(["include_system": includeSystem, "uid": Int(uid),
            "processes": visible.map { $0.json }, "unavailable_pids": observation.unavailable.map(Int.init)])
        guard (offset == 0 || expectedRevision != nil), expectedRevision == nil || expectedRevision == revision else {
            throw failure("macos_process_changed", "Process inventory revision changed; restart traversal")
        }
        let selected = Array(visible.dropFirst(offset).prefix(limit)).map { $0.json }
        var result: [String: Any] = ["processes": selected, "revision": revision, "offset": offset,
            "total": visible.count, "eof": offset + selected.count >= visible.count,
            "truncated": offset + selected.count < visible.count,
            "observation_complete": observation.unavailable.isEmpty,
            "unavailable_pid_count": observation.unavailable.count,
            "include_system": includeSystem, "default_uid": Int(uid), "effect": "none",
            "scope": "Public sysctl PID/UID/PPID/name/start and AppKit GUI paths; CLI paths can be unavailable; no command arguments or environment; live observations can change"]
        if includeSystem { result["unavailable_pids"] = observation.unavailable.map(Int.init) }
        if offset + selected.count < visible.count { result["next_offset"] = offset + selected.count }
        return result
    }
    static func exact(_ args: [String: Any]) throws -> Record {
        let raw = try SystemBridge.integer(args, "pid")
        guard raw > 0, raw <= Int(Int32.max) else { throw failure("invalid_arguments", "Use one positive process PID") }
        let expected = try SystemBridge.text(args, "expected_start")
        let actual = try read(pid_t(raw))
        guard actual.start == expected else { throw failure("macos_process_changed", "Process PID/start identity changed") }
        return actual
    }
    static func knownProtected(_ record: Record) -> Bool {
        let agents = ["codex", "grok", "claude", "chatgpt", "gemini", "opencode", "copilot"]
        if let path = record.path, path.lowercased().split(separator: "/").contains(where: { component in
            agents.contains(where: { component == $0 + ".app" })
        }) { return true }
        let names = [record.name.lowercased(), record.path.map { URL(fileURLWithPath: $0).lastPathComponent.lowercased() } ?? ""]
        return names.contains { name in
            protectedNames.contains(name) || name.hasPrefix("codex-") || name.hasPrefix("grok-")
                || agents.contains(where: { name.hasPrefix($0 + " ") || name.hasPrefix($0 + "-") })
                || ["node", "bun", "deno", "ruby", "java", "perl", "python"].contains(name)
                || name.range(of: "^python[0-9]+(\\.[0-9]+)*$", options: .regularExpression) != nil
        }
    }
    static func noLater(_ parent: String, than child: String) -> Bool {
        let left = parent.split(separator: "."), right = child.split(separator: ".")
        guard left.count == 2, right.count == 2,
              let ls = UInt64(left[0]), let lu = UInt64(left[1]),
              let rs = UInt64(right[0]), let ru = UInt64(right[1]) else { return false }
        return ls < rs || ls == rs && lu <= ru
    }
    /// Pure guard, separately tested against synthetic process graphs. Unknown
    /// ancestry is a refusal, never a reason to guess that a process is safe.
    static func authorizeSignal(_ target: Record, records: [Record], workerPID: pid_t,
                                corePID: pid_t, ownUID: uid_t) throws {
        guard ownUID != 0, target.pid > 1, target.uid == ownUID,
              target.realUID == ownUID, target.savedUID == ownUID else {
            throw failure("macos_process_owner_required", "Only a process with this user's real/effective/saved UID can receive signals")
        }
        guard !target.tty, target.path != nil, !target.name.isEmpty else {
            throw failure("macos_process_route_required", "TTY or incompletely identified processes require the existing guarded task/session route")
        }
        guard records.count <= 100000 else { throw failure("macos_process_limit", "Process lineage exceeds observation budget") }
        var table: [pid_t: Record] = [:]
        for row in records {
            guard row.pid > 0, table[row.pid] == nil else {
                throw failure("macos_process_observation", "Process lineage contains invalid duplicate identities")
            }
            table[row.pid] = row
        }
        guard table[target.pid] == target else { throw failure("macos_process_changed", "Target differs from the observed process graph") }
        func chain(_ pid: pid_t) throws -> [Record] {
            var result: [Record] = [], next = pid, seen: Set<pid_t> = []
            while next > 1 {
                guard result.count < 256, !seen.contains(next), let row = table[next] else {
                    throw failure("macos_process_observation", "Process ancestry cannot be established safely")
                }
                if let child = result.last, !noLater(row.start, than: child.start) {
                    throw failure("macos_process_changed", "Observed parent PID was reused after its child started")
                }
                seen.insert(next); result.append(row); next = row.parent
            }
            guard next == 1 else { throw failure("macos_process_observation", "Process ancestry has no observed launchd boundary") }
            return result
        }
        let ownChain = try chain(workerPID)
        guard ownChain.contains(where: { $0.pid == corePID }), corePID > 1 else {
            throw failure("macos_process_observation", "Native worker/Core parent identity changed")
        }
        if ownChain.contains(where: { $0.pid == target.pid }) {
            throw failure("macos_process_protected", "Worker, Core and their ancestors cannot be signaled")
        }
        let lineage = try chain(target.pid)
        guard lineage.allSatisfy({ $0.path != nil && !$0.name.isEmpty }) else {
            throw failure("macos_process_observation", "Process ancestry includes an unidentified executable")
        }
        if lineage.contains(where: { $0.pid == workerPID || $0.pid == corePID || knownProtected($0) || $0.tty }) {
            throw failure("macos_process_route_required", "Managed, terminal or agent processes use the existing guarded task/session route")
        }
        var descendants: Set<pid_t> = [target.pid]
        var closureComplete = false
        for _ in 0..<256 {
            let old = descendants
            for row in records where descendants.contains(row.parent) { descendants.insert(row.pid) }
            if descendants == old { closureComplete = true; break }
        }
        guard closureComplete else { throw failure("macos_process_limit", "Process descendant graph exceeds safe depth") }
        for row in records where descendants.contains(row.pid) {
            guard row.path != nil, !row.name.isEmpty else {
                throw failure("macos_process_observation", "Process subtree contains an unidentified executable")
            }
            if row.pid != target.pid {
                guard let parent = table[row.parent], noLater(parent.start, than: row.start) else {
                    throw failure("macos_process_changed", "Observed descendant parent PID was reused")
                }
            }
        }
        if records.contains(where: { descendants.contains($0.pid) && (knownProtected($0) || $0.tty) }) {
            throw failure("macos_process_route_required", "Process hosts a terminal/agent descendant; use its guarded session route")
        }
    }
    static func signal(_ args: [String: Any]) throws -> [String: Any] {
        let name = try SystemBridge.text(args, "signal")
        guard let value = signals[name] else { throw failure("invalid_arguments", "Use TERM, INT, HUP or KILL for one exact process") }
        let target = try exact(args)
        let observation = try snapshot()
        // Missing records could conceal terminal/agent lineage or descendants.
        guard observation.unavailable.isEmpty else { throw failure("macos_process_observation", "Signal requires a complete process ancestry observation") }
        let worker = getpid(), core = getppid(), uid = geteuid()
        try authorizeSignal(target, records: observation.records, workerPID: worker, corePID: core, ownUID: uid)
        let current = try exact(args)
        guard current == target, getppid() == core, getuid() == uid else {
            throw failure("macos_process_changed", "Process credentials or identity changed before signal")
        }
        // Exactly one positive-PID call. A return of zero confirms only kernel
        // acceptance, never work completion or process termination.
        guard Darwin.kill(target.pid, value) == 0 else {
            throw failure("macos_signal_unknown", "Signal outcome cannot be established; do not replay", unknown: true)
        }
        let after = try? read(target.pid)
        return ["pid": Int(target.pid), "start": target.start, "signal": name,
            "signal_accepted": true, "termination_confirmed": false, "automatic_retry": false,
            "same_process_observed_after": after?.start == target.start,
            "effect": "accepted", "scope": "One explicit kernel signal after exact identity preflight; macOS kill has no atomic start-token guard; no process group or completion claim"]
    }
    static func handle(_ operation: String, arguments args: [String: Any]) async throws -> [String: Any]? {
        switch operation {
        case "system.processes":
            return try page(snapshot(), includeSystem: SystemBridge.bool(args, "include_system"),
                uid: geteuid(), offset: SystemBridge.integer(args, "offset", default: 0),
                limit: SystemBridge.integer(args, "limit", default: 100), expectedRevision: args["expected_revision"] as? String)
        case "system.process": return ["process": try exact(args).json, "effect": "none"]
        case "system.signal": return try signal(args)
        default: return nil
        }
    }
}

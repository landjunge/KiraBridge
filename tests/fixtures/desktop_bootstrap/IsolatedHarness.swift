import Foundation

@main
struct IsolatedHarness {
    static func main() {
        let args = CommandLine.arguments
        let directory = URL(fileURLWithPath: args[1])
        let mode = args[2]
        if mode.hasPrefix("receipt:") {
            let json = String(mode.dropFirst("receipt:".count))
            if let receipt = try? DesktopIsolatedReceipt(
                data: Data(json.utf8), directory: directory) {
                print(receipt.origin.absoluteString)
            } else {
                print("invalid")
            }
            return
        }
        if mode == "env" {
            let root = URL(fileURLWithPath: args[3])
            let source = [
                "PATH": "/usr/bin:/bin", "HOME": "/private/home", "LANG": "de_DE.UTF-8",
                "KIRABRIDGE_LOCAL_TOKEN": "prod-token-marker",
                "KIRABRIDGE_CONFIG": "/private/production/config.toml",
                "SECRET_MARKER": "leak-marker",
            ]
            let environment = DesktopBootstrap.isolatedEnvironment(root: root, from: source)
            let keys = environment.keys.sorted().joined(separator: ",")
            print("\(keys)|\(environment["PYTHONPATH"] ?? "")")
            return
        }
        if mode == "owned" {
            var adopted = false
            do {
                _ = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/bin/sh"),
                    arguments: ["-c", "printf '%s\\n' \"$1\"; sleep 5", "fixture", args[3]],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 5,
                    owned: { _ in adopted = true; return true })
                print("unexpected \(adopted)")
            } catch {
                print("failed \(adopted)")
            }
            return
        }
        if mode == "late_child" {
            // A sealed holder refuses the child; startIsolated must stop it and
            // report a confirmed cleanup, never leave it untracked.
            let holder = DesktopOwnedChild()
            _ = holder.stop()
            do {
                _ = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/bin/sh"),
                    arguments: ["-c", "printf '%s\\n' \"$1\"; sleep 5", "fixture", args[3]],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 5,
                    owned: { holder.adopt($0) })
                print("unexpected")
            } catch let failure as DesktopBootstrapFailure {
                print("fenced \(holder.hasHandle) \(failure.cleanupConfirmed)")
            } catch {
                print("unexpected")
            }
            return
        }
        if mode == "owned_fence" {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/sh")
            process.arguments = ["-c", "sleep 3"]
            try? process.run()
            var denials = 0
            let holder = DesktopOwnedChild(stopper: { _ in denials += 1; return false })
            let adopted = holder.adopt(process)
            let firstStop = holder.stop()
            let running = holder.isRunning
            let kept = holder.hasHandle
            let lateAdopt = holder.adopt(process)
            let secondStop = holder.stop()
            print("\(adopted) \(firstStop) \(running) \(kept) \(lateAdopt) \(secondStop) \(denials)")
            _ = DesktopBootstrap.stop(process)
            return
        }
        if mode == "owned_sealed" {
            let holder = DesktopOwnedChild()
            let stoppedEmpty = holder.stop()
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/sh")
            process.arguments = ["-c", "sleep 1"]
            try? process.run()
            let lateAdopt = holder.adopt(process)
            print("\(stoppedEmpty) \(lateAdopt) \(holder.hasHandle)")
            _ = DesktopBootstrap.stop(process)
            return
        }
        if mode == "timeout" {
            do {
                _ = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/bin/sh"),
                    arguments: ["-c", "sleep 5"],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 1)
                print("unexpected")
            } catch {
                print("timeout")
            }
            return
        }
        if mode == "eof" {
            do {
                _ = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/bin/sh"),
                    arguments: ["-c", "exit 3"],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 5)
                print("unexpected")
            } catch {
                print("failed")
            }
            return
        }
        if mode == "eof_live" {
            let start = Date()
            do {
                _ = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/bin/sh"),
                    arguments: ["-c", "exec 1>&-; sleep 5"],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 5)
                print("unexpected")
            } catch {
                print("failed \(String(format: "%.1f", Date().timeIntervalSince(start)))")
            }
            return
        }
        if mode == "old_drain" {
            // Negative control: the previous 64 KiB drain stops reading, so the
            // same 2 MiB child blocks before its receipt. This must print
            // "blocked" — it proves the flood exceeds the old limit.
            let script = """
            import os, sys, time
            os.write(2, b"x" * (2 * 1024 * 1024))
            os.write(1, (sys.argv[1] + "\\n").encode())
            time.sleep(3)
            """
            let child = Process()
            child.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            child.arguments = ["-c", script, args[3]]
            let output = Pipe(), errors = Pipe()
            child.standardOutput = output
            child.standardError = errors
            try? child.run()
            var total = 0
            while total < 65536 {
                guard let chunk = try? errors.fileHandleForReading.read(upToCount: 8192),
                      !chunk.isEmpty else { break }
                total += chunk.count
            }
            let descriptor = output.fileHandleForReading.fileDescriptor
            var ready = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
            let status = withUnsafeMutablePointer(to: &ready) { pointer in
                Darwin.poll(pointer, 1, 2000)
            }
            print(status == 0 ? "blocked" : "receipt")
            _ = DesktopBootstrap.stop(child)
            return
        }
        if mode == "stderr_flood" {
            let script = """
            import os, sys, time
            receipt = sys.argv[1]
            os.write(2, b"x" * (2 * 1024 * 1024))
            os.write(1, (receipt + "\\n").encode())
            os.write(2, b"y" * (2 * 1024 * 1024))
            time.sleep(3)
            """
            do {
                let started = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/usr/bin/python3"),
                    arguments: ["-c", script, args[3]],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 10)
                print("started \(started.receipt.origin.absoluteString)")
                // The child is still flooding stderr after the receipt; it must
                // stay unblocked while the parent keeps draining.
                usleep(400_000)
                print("alive \(started.process.isRunning)")
                _ = DesktopBootstrap.stop(started.process)
                print("stopped \(started.process.isRunning)")
            } catch {
                print("failed")
            }
            return
        }
        let line = args[3]
        do {
            let started = try DesktopBootstrap.startIsolated(
                executable: URL(fileURLWithPath: "/bin/sh"),
                arguments: ["-c", "printf '%s\\n' \"$1\"; sleep 5", "fixture", line],
                environment: ProcessInfo.processInfo.environment,
                privateDirectory: directory, timeout: 5)
            print("started \(started.receipt.origin.absoluteString) \(started.process.isRunning)")
            DesktopBootstrap.stop(started.process)
            print("stopped \(started.process.isRunning)")
        } catch {
            print("failed")
        }
    }
}

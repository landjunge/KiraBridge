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
                    owned: { _ in adopted = true })
                print("unexpected \(adopted)")
            } catch {
                print("failed \(adopted)")
            }
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
        if mode == "stderr_flood" {
            do {
                let started = try DesktopBootstrap.startIsolated(
                    executable: URL(fileURLWithPath: "/bin/sh"),
                    arguments: [
                        "-c",
                        "dd if=/dev/zero of=/dev/stderr bs=1024 count=70 2>/dev/null; "
                            + "printf '%s\\n' \"$1\"; sleep 5",
                        "fixture", args[3],
                    ],
                    environment: ProcessInfo.processInfo.environment,
                    privateDirectory: directory, timeout: 5)
                print("started \(started.receipt.origin.absoluteString)")
                DesktopBootstrap.stop(started.process)
                print("stopped")
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

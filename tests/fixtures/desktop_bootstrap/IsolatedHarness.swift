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

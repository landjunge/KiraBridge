import Foundation
import Darwin

@main
struct OwnedBootstrapHarness {
    static func writeAll(_ fd: Int32, _ bytes: [UInt8]) {
        var offset = 0
        while offset < bytes.count {
            let written = bytes.withUnsafeBytes { pointer in
                Darwin.write(fd, pointer.baseAddress!.advanced(by: offset), bytes.count - offset)
            }
            if written < 0 && errno == EINTR { continue }
            guard written > 0 else { exit(74) }
            offset += written
        }
    }
    static func main() {
        let args = CommandLine.arguments
        if args.count > 2 && args[1] == "--child" {
            alarm(3)  // Fixture owns its own deadline even if the test parent fails.
            let scenario = args[2]
            if scenario == "stderr_pressure" {
                writeAll(STDERR_FILENO, [UInt8](repeating: 120, count: 512 * 1024))
            } else if scenario == "stdout_limit" {
                writeAll(STDOUT_FILENO, [UInt8](repeating: 120, count: 256 * 1024))
            } else if scenario == "stderr_limit" {
                writeAll(STDERR_FILENO, [UInt8](repeating: 120, count: 256 * 1024))
            } else if scenario == "sleep" || scenario == "ignore_term" {
                if scenario == "ignore_term" { signal(SIGTERM, SIG_IGN) }
                usleep(2_000_000)
            }
            writeAll(STDOUT_FILENO, Array("{\"login_file\":\"private-fixture\"}".utf8))
            exit(scenario == "nonzero" ? 7 : 0)
        }
        let scenario = args[1]
        let start = DispatchTime.now().uptimeNanoseconds
        var result: [String: Any] = [:]
        do {
            let data = try DesktopBootstrap.run(executable: URL(fileURLWithPath: args[0]),
                arguments: ["--child", scenario], environment: ProcessInfo.processInfo.environment,
                timeout: ["sleep", "ignore_term"].contains(scenario) ? 0.15 : 2,
                maxStdoutBytes: 4096,
                maxStderrBytes: scenario == "stderr_pressure" ? 1024 * 1024 : 4096)
            result = ["success": true, "bytes": data.count]
        } catch let failure as DesktopBootstrapFailure {
            result = ["success": false, "kind": failure.kind.rawValue,
                      "cleanup_confirmed": failure.cleanupConfirmed]
        } catch {
            result = ["success": false, "kind": "unexpected_error"]
        }
        result["elapsed"] = Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000_000
        let encoded = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: encoded, encoding: .utf8)!)
    }
}

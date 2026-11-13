import Foundation

@main
struct NavigationHarness {
    static func main() {
        let args = CommandLine.arguments
        if args[2].hasPrefix("sequence") {
            let requests = DesktopOpenRequests()
            var policy = DesktopNavigationPolicy(), replies: [Bool] = [], loads: [String] = []
            let count = args[2] == "sequence-overflow" ? 17 : 1
            for _ in 0..<count {
                requests.submit([args[1]], policy: policy, ready: false,
                    load: { loads.append($0) }, reply: { replies.append($0) })
            }
            let before = replies.count, beforeLoads = loads.count
            if args[2] == "sequence-failure" {
                requests.failAll(); requests.failAll()
            } else {
                let path = "/private/custom-config/approval-login.html"
                let data = try! JSONSerialization.data(withJSONObject: ["login_file": path])
                let receipt = try! DesktopLoginReceipt(data: data)
                policy.authorizeLogin(receipt)
                loads.append(receipt.loginFile.path) // The one bootstrap load occurs first.
                requests.resolve(policy, ready: true)
                requests.resolve(policy, ready: true)
            }
            let result: [String: Any] = ["before": before, "before_loads": beforeLoads,
                                       "replies": replies, "loads": loads]
            let encoded = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
            print(String(data: encoded, encoding: .utf8)!)
            return
        }
        if args[2] == "receipt" {
            print((try? DesktopLoginReceipt(data: Data(args[1].utf8))) != nil ? "accepted" : "invalid")
            return
        }
        var policy = args.count > 3
            ? DesktopNavigationPolicy(consolePort: Int(args[3]) ?? 8766)
            : DesktopNavigationPolicy()
        if !args[2].contains("untrusted") {
            let path = args[2].contains("custom")
                ? "/private/custom-config/approval-login.html" : "/private/owned/approval-login.html"
            let data = try! JSONSerialization.data(withJSONObject: ["login_file": path])
            policy.authorizeLogin(try! DesktopLoginReceipt(data: data))
        }
        if args[2].hasPrefix("openfiles") {
            print(String(policy.allowsLoginPath(args[1])))
            return
        }
        let url = args[1] == "nil" ? nil : URL(string: args[1])
        let isolated = args.count > 4 && args[4] == "isolated"
        print(args[2] == "popup" ? String(policy.allowsPopup(url))
              : policy.decision(
                    for: url, activated: args[2] == "activated", isolated: isolated).rawValue)
    }
}

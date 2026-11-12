import Foundation

@main
struct FamilySwitchHarness {
    static func main() throws {
        let args = CommandLine.arguments
        switch args[1] {
        case "quote": print(familySwitchJsonString(args[2]))
        case "outcome":
            print(familySwitchOutcome(status: Int32(args[2])!, data: Data(args[4].utf8), appId: args[3]))
        case "admit":
            let value = try JSONSerialization.jsonObject(with: Data(args[2].utf8)) as! [String: Any]
            print(familySwitchAdmits(sameView: value["sameView"] as! Bool,
                mainFrame: value["mainFrame"] as! Bool, scheme: value["scheme"] as! String,
                host: value["host"] as! String, port: value["port"] as! Int, body: value["body"]!))
        default: fatalError("unknown fixture mode")
        }
    }
}

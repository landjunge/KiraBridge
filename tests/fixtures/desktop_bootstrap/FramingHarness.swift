import Foundation

@main
struct FramingHarness {
    enum FixtureFailure: Error { case callback }
    static func main() {
        let mode = CommandLine.arguments[1]
        if mode == "pipe" {
            var index = 0
            do {
                try SystemRequestFrames.read(from: FileHandle.standardInput) { frame in
                    index += 1
                    var data = try JSONSerialization.data(withJSONObject: ["index": index, "bytes": frame.count])
                    data.append(10)
                    try FileHandle.standardOutput.write(contentsOf: data)
                }
            } catch { exit(65) }
            return
        }
        let input: Data
        if mode == "maximum" || mode == "budget" {
            input = Data(repeating: 120, count: 65535) + Data([10])
        } else if mode == "oversize" {
            input = Data(repeating: 120, count: 65536) + Data([10])
        } else if mode == "prior_then_oversize" {
            input = Data("first\n".utf8) + Data(repeating: 120, count: 65536)
        } else if mode == "empty" {
            input = Data()
        } else if mode == "partial" {
            input = Data("unfinished".utf8)
        } else if mode == "empty_frames" {
            input = Data("\n\n".utf8)
        } else {
            input = Data("one\nGrüße\nlast\npartial".utf8)
        }
        var cursor = 0, reads = 0, frames: [Int] = [], text: [String] = []
        var status = "eof"
        do {
            try SystemRequestFrames.read({ requested in
                reads += 1
                let fragment = mode == "fragmented" ? 2 : requested
                let end = min(input.count, cursor + min(fragment, requested))
                let data = input.subdata(in: cursor..<end)
                cursor = end
                return data
            }) { frame in
                frames.append(frame.count)
                if frame.count < 100 { text.append(String(data: frame, encoding: .utf8)!) }
                if mode == "callback_failure" { throw FixtureFailure.callback }
            }
        } catch SystemRequestFrameFailure.oversized { status = "oversized" }
        catch { status = "callback_failure" }
        let result: [String: Any] = ["frames": frames, "text": text, "reads": reads, "status": status]
        let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
}

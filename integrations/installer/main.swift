import Cocoa
import CryptoKit

enum InstallerFailure: Error, LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let text): return text }
    }
}

func checksum(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

func verifyPackage() throws -> [String: Any] {
    let bundle = Bundle.main
    guard let resources = bundle.resourceURL,
          let version = bundle.object(forInfoDictionaryKey: "KiraBridgeVersion") as? String,
          let commit = bundle.object(forInfoDictionaryKey: "KiraBridgeSourceCommit") as? String,
          let expected = bundle.object(forInfoDictionaryKey: "KiraBridgePackageSHA256") as? String,
          commit.range(of: "^[a-f0-9]{40}$", options: .regularExpression) != nil else {
        throw InstallerFailure.invalid("Die Identität des Installationspakets fehlt.")
    }
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
    task.arguments = ["--verify", "--deep", "--strict", bundle.bundleURL.path]
    task.standardOutput = FileHandle.nullDevice
    task.standardError = FileHandle.nullDevice
    try task.run()
    task.waitUntilExit()
    guard task.terminationStatus == 0 else {
        throw InstallerFailure.invalid("Die App wurde verändert. Bitte das vollständige Paket erneut laden.")
    }
    let manifestURL = resources.appendingPathComponent("installer-package.json")
    let manifestData = try Data(contentsOf: manifestURL)
    guard checksum(manifestData) == expected,
          let manifest = try JSONSerialization.jsonObject(with: manifestData) as? [String: Any],
          manifest["schema"] as? String == "kirabridge.installer-app.v1",
          manifest["source_commit"] as? String == commit,
          manifest["version"] as? String == version,
          let files = manifest["files"] as? [String: String], !files.isEmpty, files.count < 20002 else {
        throw InstallerFailure.invalid("Die Paketprüfung ist fehlgeschlagen.")
    }
    let manager = FileManager.default
    var observed = Set<String>()
    guard let enumerator = manager.enumerator(at: resources,
        includingPropertiesForKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey]) else {
        throw InstallerFailure.invalid("Das Installationspaket ist nicht lesbar.")
    }
    for case let file as URL in enumerator {
        let value = try file.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey])
        guard value.isSymbolicLink != true else {
            throw InstallerFailure.invalid("Eine unerwartete Dateiverknüpfung wurde gefunden.")
        }
        if value.isRegularFile == true {
            let name = String(file.path.dropFirst(resources.path.count + 1))
            if name == "installer-package.json" { continue }
            guard let expectedHash = files[name],
                  let size = value.fileSize, size <= 64 * 1024 * 1024,
                  checksum(try Data(contentsOf: file)) == expectedHash else {
                throw InstallerFailure.invalid("Eine Paketdatei ist unvollständig oder verändert.")
            }
            observed.insert(name)
        }
    }
    guard observed == Set(files.keys) else {
        throw InstallerFailure.invalid("Das Installationspaket ist unvollständig.")
    }
    return ["verified": true, "version": version, "source_commit": commit,
            "file_count": files.count, "signing": "ad-hoc", "installation_performed": false]
}

final class InstallerDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        do {
            let receipt = try verifyPackage()
            if !CommandLine.arguments.contains("--install") {
                let alert = NSAlert()
                alert.messageText = "KiraBridge installieren"
                alert.informativeText = "Version \(receipt["version"] ?? "")\n\nInstalliert oder aktualisiert KiraBridge für deinen Benutzer. Vorhandene Einstellungen und Verbindungen bleiben erhalten.\n\nVoraussetzungen: macOS 15 oder 26, Python 3.11 und uv 0.11.6.\n\nDie Installation wird in einem eigenen sichtbaren Terminalfenster ausgeführt. Dort siehst du Fortschritt und Ergebnis."
                alert.addButton(withTitle: "Installieren")
                alert.addButton(withTitle: "Abbrechen")
                guard alert.runModal() == .alertFirstButtonReturn else { NSApp.terminate(nil); return }
            }
            guard let resources = Bundle.main.resourceURL,
                  let terminal = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Terminal") else {
                throw InstallerFailure.invalid("Das macOS-Terminal wurde nicht gefunden.")
            }
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = true
            NSWorkspace.shared.open([resources.appendingPathComponent("KiraBridge-Installieren.command")],
                withApplicationAt: terminal, configuration: configuration) { _, error in
                DispatchQueue.main.async {
                    if let error { self.fail(error) }
                    else {
                        if CommandLine.arguments.contains("--install") {
                            print("{\"terminal_open_requested\":true,\"installation_complete\":false}")
                        }
                        NSApp.terminate(nil)
                    }
                }
            }
        } catch { fail(error) }
    }

    func fail(_ error: Error) {
        if CommandLine.arguments.contains("--install") {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
            exit(1)
        }
        let alert = NSAlert()
        alert.messageText = "KiraBridge konnte nicht installiert werden"
        alert.informativeText = error.localizedDescription
        alert.runModal()
        NSApp.terminate(nil)
    }
}

if CommandLine.arguments.contains("--verify-package") {
    do {
        let value = try verifyPackage()
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    } catch {
        FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
        exit(1)
    }
} else {
    let application = NSApplication.shared
    let delegate = InstallerDelegate()
    application.delegate = delegate
    application.run()
}

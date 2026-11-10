import Foundation
import ApplicationServices
import Carbon
import CryptoKit

@main
struct KeyboardInspectHarness {
    @MainActor static func main() async throws {
        var checks = 0
        func field(_ scenario: String = "ordinary", selection: CFRange = CFRange(location: 1, length: 2),
                   value: String = "A😀e\u{301}") throws -> SystemKeyboard.Field {
            var prepared = false, valueRead = false
            do {
                let result = try SystemKeyboard.observeField(prepare: {
                    if scenario == "timeout" { throw SystemControl.failure("mock_timeout", "fixture") }
                    prepared = true
                }, read: { name in
                    precondition(prepared, "Attribute read before timeout")
                    switch name {
                    case kAXRoleAttribute:
                        return (scenario == "unknown" ? "AXButton" : "AXTextField") as CFString
                    case kAXSubroleAttribute:
                        if scenario == "missing_subrole" { return nil }
                        return (scenario == "secure" ? "AXSecureTextField" : "") as CFString
                    case kAXEnabledAttribute, kAXFocusedAttribute: return NSNumber(value: scenario != "unfocused")
                    case kAXNumberOfCharactersAttribute:
                        return NSNumber(value: scenario == "oversize" ? SystemKeyboard.maxValueBytes : value.utf16.count)
                    case kAXSelectedTextRangeAttribute:
                        var range = selection
                        return AXValueCreate(.cfRange, &range)
                    case kAXValueAttribute:
                        valueRead = true
                        return value as CFString
                    default: return nil
                    }
                })
                precondition(valueRead)
                return result
            } catch {
                if ["secure", "unknown", "missing_subrole", "timeout", "oversize", "unfocused"].contains(scenario) {
                    precondition(!valueRead, "Unsupported field value was read")
                }
                throw error
            }
        }
        let observed = try field()
        precondition(observed.value == "A😀e\u{301}" && observed.selection.location == 1 && observed.selection.length == 2)
        precondition(observed.metadata["value_utf16_units"] as? Int == 5)
        precondition(observed.metadata["value_utf8_bytes"] as? Int == 8)
        precondition(!observed.metadata.keys.contains("value"))
        checks += 1
        for scenario in ["secure", "unknown", "missing_subrole", "timeout", "oversize", "unfocused", "surrogate_split", "invalid_selection"] {
            do {
                _ = try field(scenario, selection: scenario == "surrogate_split" ? CFRange(location: 2, length: 0) : scenario == "invalid_selection" ? CFRange(location: 6, length: 0) : CFRange(location: 1, length: 2))
                fatalError("Expected refusal: \(scenario)")
            } catch let error as SystemBridgeFailure {
                precondition(error.code == (scenario == "timeout" ? "mock_timeout" : "keyboard_unsupported"))
                checks += 1
            }
        }
        let app: [String: Any] = ["pid": 123, "started_at": 100.5, "active": true]
        let layout: [String: Any] = ["input_source_id": "fixture.de", "layout_id": "fixture.de", "keyboard_type": 40]
        let first = try SystemKeyboard.revision(application: app, window: "window", element: "field", field: observed, layout: layout)
        for change in ["value", "selection", "layout", "focus", "window", "element"] {
            var otherApp = app, otherLayout = layout
            if change == "focus" { otherApp["active"] = false }
            if change == "layout" { otherLayout["layout_id"] = "fixture.us" }
            let otherField = try field(selection: change == "selection" ? CFRange(location: 0, length: 0) : observed.selection,
                                       value: change == "value" ? "B😀e\u{301}" : observed.value)
            let next = try SystemKeyboard.revision(application: otherApp, window: change == "window" ? "other" : "window",
                                                   element: change == "element" ? "other" : "field", field: otherField, layout: otherLayout)
            precondition(first != next, "Snapshot revision ignored \(change)")
            checks += 1
        }
        var keyChecks = 0
        precondition(SystemKeyboard.namedKeys.count == 54 && Set(SystemKeyboard.namedKeys.values).count == 54)
        precondition(SystemKeyboard.namedKeys["enter"] == 36 && SystemKeyboard.namedKeys["keypad_enter"] == 76)
        precondition(SystemKeyboard.namedKeys["backspace"] == 51 && SystemKeyboard.namedKeys["delete"] == 117)
        _ = try SystemKeyboard.namedKey(["named": "enter", "character": NSNull(), "key_code": NSNull()])
        keyChecks += 1
        let unsupportedKeys: [[String: Any]] = [["character": "a"], ["key_code": 0], ["named": "unknown"],
            ["named": "enter", "character": "a"], ["named": "enter", "key_code": 0]]
        for spec in unsupportedKeys {
            do { _ = try SystemKeyboard.namedKey(spec); fatalError("Unsupported key accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); keyChecks += 1 }
        }
        let binding: [String: Any] = ["pid": 123, "expected_started_at": 100.5, "target_token": "field",
            "helper_pid": 456, "worker_generation": "worker", "expected_revision": first]
        try SystemKeyboard.matchingBinding(binding, binding)
        for key in binding.keys {
            var stale = binding; stale[key] = "stale"
            do { try SystemKeyboard.matchingBinding(stale, binding); fatalError("Stale binding accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); keyChecks += 1 }
        }
        for scenario in ["permission", "modifier", "held_key"] {
            var posts = 0
            do {
                _ = try SystemKeyboard.postPair(validate: {
                    try SystemKeyboard.inputAllowed(postAccess: scenario != "permission",
                        flags: scenario == "modifier" ? .maskShift : [], keyHeld: scenario == "held_key")
                }, sameGeneration: { true }, post: { _ in posts += 1 })
                fatalError("Input conflict accepted")
            } catch let error as SystemBridgeFailure {
                precondition(!error.effectUnknown && posts == 0); keyChecks += 1
            }
        }
        var order: [String] = []
        let posted = try SystemKeyboard.postPair(validate: {
            order.append("validate")
            try SystemKeyboard.inputAllowed(postAccess: true, flags: [], keyHeld: false)
        }, sameGeneration: { order.append("generation"); return true }, post: { order.append($0 ? "down" : "up") })
        precondition(order == ["validate", "generation", "down", "generation", "up"])
        precondition(posted["post_calls_returned"] as? Int == 2 && posted["app_processing_confirmed"] as? Bool == false)
        keyChecks += 1
        for scenario in ["target_before", "generation_before", "generation_after", "down_error", "up_error", "cleanup_error"] {
            var posts: [String] = []
            do {
                _ = try SystemKeyboard.postPair(validate: {
                    if scenario == "target_before" { throw SystemControl.failure("changed", "fixture") }
                }, sameGeneration: {
                    scenario != "generation_before" && !(scenario == "generation_after" && !posts.isEmpty)
                }, post: { down in
                    posts.append(down ? "down" : "up")
                    if (scenario == "down_error" && down) || (scenario == "up_error" && posts.count == 2)
                        || scenario == "cleanup_error" { throw SystemControl.failure("post_lost", "fixture") }
                })
                fatalError("Expected key pair failure")
            } catch let error as SystemBridgeFailure {
                let before = ["target_before", "generation_before"].contains(scenario)
                precondition(error.effectUnknown == !before)
                if before { precondition(posts.isEmpty) }
                else if scenario == "generation_after" { precondition(posts == ["down"]) }
                else if scenario == "up_error" { precondition(posts == ["down", "up", "up"]) }
                else { precondition(posts == ["down", "up"]) }
                keyChecks += 1
            }
        }
        var layoutChecks = 0
        var layoutPositions: [String: [String: Int]] = [:]
        var layouts: [SystemKeyboard.Layout] = []
        // Read installed layout DATA, never select an input source or post an event.
        for id in ["com.apple.keylayout.US", "com.apple.keylayout.German"] {
            let filter = [kTISPropertyInputSourceID as String: id] as CFDictionary
            let sources = TISCreateInputSourceList(filter, true)!.takeRetainedValue()
            precondition(CFArrayGetCount(sources) == 1)
            let source = unsafeBitCast(CFArrayGetValueAtIndex(sources, 0), to: TISInputSource.self)
            let raw = TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData)!
            let data = Unmanaged<CFData>.fromOpaque(raw).takeUnretainedValue()
            let layout = SystemKeyboard.Layout(metadata: ["layout_id": id, "layout_sha256": id], translate: {
                SystemKeyboard.translate(data, code: $0, flags: $1, keyboardType: 40)
            })
            layouts.append(layout)
            for character in ["z", "Z", "y", "Y"] {
                let expected: UInt16 = (character.lowercased() == "z") == id.hasSuffix("US") ? 6 : 16
                for modifiers in [["command"], ["command", "shift"]] {
                    let resolved = try SystemKeyboard.resolve(["character": character], modifiers: modifiers, layout: layout)
                    precondition(resolved.code == expected)
                    precondition(resolved.flags == (modifiers.count == 1 ? .maskCommand : [.maskCommand, .maskShift]))
                    layoutChecks += 1
                }
                layoutPositions[id, default: [:]][character] = Int(expected)
            }
            if id.hasSuffix("US") {
                precondition(SystemKeyboard.translate(data, code: UInt16(kVK_ANSI_E), flags: .maskAlternate,
                                                     keyboardType: 40) == nil)
                layoutChecks += 1
            }
        }
        func refuses(_ validation: () throws -> Void) {
            var posts = 0
            do {
                _ = try SystemKeyboard.postPair(validate: validation, sameGeneration: { true }, post: { _ in posts += 1 })
                fatalError("Unsafe layout resolution accepted")
            } catch let error as SystemBridgeFailure {
                precondition(!error.effectUnknown && posts == 0); layoutChecks += 1
            } catch { fatalError("Unexpected fixture error: \(error)") }
        }
        for code in [54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 72, 73, 74, 102, 104, 127] {
            refuses { _ = try SystemKeyboard.resolve(["key_code": code], modifiers: [], layout: layouts[0]) }
        }
        for code in [0, 6, 16, 82, 123] {
            let resolved = try SystemKeyboard.resolve(["key_code": code], modifiers: ["control"], layout: layouts[0])
            precondition(Int(resolved.code) == code && resolved.flags == .maskControl); layoutChecks += 1
        }
        let symbols = SystemKeyboard.Layout(metadata: [:], translate: { code, flags in
            guard code == 0 else { return nil }
            if flags.contains(.maskAlternate) { return flags.contains(.maskShift) ? "#" : "@" }
            return nil
        })
        let option = try SystemKeyboard.resolve(["character": "@"], modifiers: ["command"], layout: symbols)
        precondition(option.code == 0 && option.flags == [.maskCommand, .maskAlternate]); layoutChecks += 1
        let shiftOption = try SystemKeyboard.resolve(["character": "#"], modifiers: ["option"], layout: symbols)
        precondition(shiftOption.code == 0 && shiftOption.flags == [.maskShift, .maskAlternate]); layoutChecks += 1
        let positionsAmbiguous = SystemKeyboard.Layout(metadata: [:], translate: { code, _ in code < 2 ? "@" : nil })
        refuses { _ = try SystemKeyboard.resolve(["character": "@"], modifiers: [], layout: positionsAmbiguous) }
        let flagsAmbiguous = SystemKeyboard.Layout(metadata: [:], translate: { code, flags in
            code == 0 && (flags == .maskShift || flags == .maskAlternate) ? "@" : nil
        })
        refuses { _ = try SystemKeyboard.resolve(["character": "@"], modifiers: [], layout: flagsAmbiguous) }
        refuses { _ = try SystemKeyboard.resolve(["character": "😀"], modifiers: [], layout: symbols) }
        refuses { try SystemKeyboard.matchingLayout(layouts[0].metadata, layouts[1].metadata) }
        var changedData = layouts[0].metadata; changedData["layout_sha256"] = "changed"
        refuses { try SystemKeyboard.matchingLayout(layouts[0].metadata, changedData) }
        refuses { _ = try SystemKeyboard.resolve(["named": "enter"], modifiers: ["shift", "shift"], layout: symbols) }
        let fn = try SystemKeyboard.resolve(["named": "enter"], modifiers: ["fn"], layout: symbols)
        precondition(fn.code == CGKeyCode(kVK_Return) && fn.flags == .maskSecondaryFn)
        layoutChecks += 1
        for type in [40, 41] {
            let (down, up) = try SystemKeyboard.events(["keyboard_type": type], code: 6, flags: [.maskCommand, .maskShift], observedCapsLock: false)
            precondition(down.type == .keyDown && up.type == .keyUp)
            for event in [down, up] {
                precondition(event.getIntegerValueField(.keyboardEventKeyboardType) == Int64(type))
                precondition(event.flags == [.maskCommand, .maskShift])
            }
            layoutChecks += 1
        }
        let invalidTypes: [Any] = [true, -1, 40.5, Double(UInt32.max) + 1]
        for invalid in invalidTypes {
            refuses { _ = try SystemKeyboard.events(["keyboard_type": invalid], code: 6, flags: []) }
        }
        var extendedKeyChecks = 0
        let unavailable = try SystemKeyboard.observedLayout(sourceID: nil, layoutID: nil,
            keyboardType: 40, data: nil)
        precondition(unavailable.metadata["input_source_id"] is NSNull
                     && unavailable.metadata["layout_id"] is NSNull
                     && unavailable.metadata["logical_keys_available"] as? Bool == false)
        for (name, expectedCode) in SystemKeyboard.namedKeys {
            let key = try SystemKeyboard.resolve(["named": name], modifiers: ["fn"], layout: unavailable)
            let physical = try SystemKeyboard.resolve(["key_code": Int(expectedCode)],
                modifiers: ["command", "control", "option", "shift", "fn"], layout: unavailable)
            let fnCode = SystemKeyboard.fnNavigation[expectedCode]?.0 ?? expectedCode
            precondition(key.code == fnCode && key.flags == (fnCode == expectedCode ? .maskSecondaryFn : []))
            precondition(physical.code == expectedCode
                && physical.flags == [.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn])
            extendedKeyChecks += 1
        }
        for failure: () throws -> Void in [
            { _ = try SystemKeyboard.resolve(["character": "a"], modifiers: [], layout: unavailable) },
            { _ = try SystemKeyboard.resolve(["named": "left"], modifiers: ["fn", "fn"], layout: unavailable) },
            { _ = try SystemKeyboard.resolve(["named": "left"], modifiers: ["hyper"], layout: unavailable) },
            { try SystemKeyboard.inputAllowed(postAccess: true, flags: .maskSecondaryFn, keyHeld: false) },
            { _ = try SystemKeyboard.observedLayout(sourceID: "", layoutID: nil, keyboardType: 40, data: nil) },
        ] {
            do { try failure(); fatalError("Invalid extended keyboard state accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); extendedKeyChecks += 1 }
        }
        let ime = try SystemKeyboard.observedLayout(sourceID: "fixture.ime", layoutID: "fixture.layout",
            keyboardType: 40, data: Data() as CFData)
        precondition(ime.metadata["logical_keys_available"] as? Bool == false
                     && ime.translate(0, []) == nil)
        extendedKeyChecks += 1
        var fnNavigationChecks = 0
        for (name, originalCode, transformedCode): (String, CGKeyCode, CGKeyCode) in [
            ("backspace", 51, 117), ("left", 123, 115), ("right", 124, 119),
            ("up", 126, 116), ("down", 125, 121),
        ] {
            for modifiers in [["fn"], ["fn", "shift"], ["fn", "control"],
                              ["fn", "command"], ["fn", "option"], ["fn", "control", "shift"]] {
                let shouldTransform = !modifiers.contains(where: { ["control", "command", "option"].contains($0) })
                for spec: [String: Any] in [["named": name], ["key_code": Int(originalCode)]] {
                    let result = try SystemKeyboard.resolve(spec, modifiers: modifiers, layout: unavailable)
                    if shouldTransform {
                        precondition(result.code == transformedCode && result.originalCode == originalCode)
                        precondition(result.flags == (modifiers.contains("shift") ? .maskShift : []))
                        precondition(result.originalFlags?.contains(.maskSecondaryFn) == true)
                        precondition(result.transformation != nil)
                    } else {
                        precondition(result.code == originalCode && result.flags.contains(.maskSecondaryFn))
                        precondition(result.originalCode == nil && result.transformation == nil)
                    }
                    fnNavigationChecks += 1
                }
            }
        }
        var textChecks = 0
        let textLayout: [String: Any] = ["keyboard_type": 40]
        for sample in [" aA \t\r\n", "A😀e\u{301}中", "0123456789abcdef😀e\u{301}", "é", "e\u{301}"] {
            let chunks = try SystemKeyboard.textChunks(sample)
            precondition(chunks.flatMap { $0 }.elementsEqual(sample.utf16))
            for units in chunks {
                let pair = try SystemKeyboard.unicodeEvents(textLayout, units: units)
                for event in [pair.0, pair.1] {
                    precondition(event.getIntegerValueField(.keyboardEventKeycode) == 0) // Never Return.
                    var count = 0
                    event.keyboardGetUnicodeString(maxStringLength: 0, actualStringLength: &count, unicodeString: nil)
                    precondition(count == units.count)
                }
            }
            textChecks += 1
        }
        for tail in ["😀", "e\u{301}", "👨‍👩‍👧‍👦"] {
            let chunks = try SystemKeyboard.textChunks(String(repeating: "a", count: 15) + tail)
            precondition(chunks.count == 2 && chunks[0].count == 15 && chunks[1].elementsEqual(tail.utf16))
            textChecks += 1
        }
        let area = SystemKeyboard.Field(value: "prefix😀suffix", selection: CFRange(location: 6, length: 2),
                                        metadata: ["role": "AXTextArea", "subrole": ""])
        let insertion = "A😀e\u{301}"
        let expected = try SystemKeyboard.expectedText(area, inserting: Array(insertion.utf16))
        precondition(expected.value.utf8.elementsEqual(("prefix" + insertion + "suffix").utf8))
        precondition(expected.selection.location == 11 && expected.selection.length == 0)
        precondition(expected.matches(SystemKeyboard.Field(value: expected.value, selection: expected.selection, metadata: [:])))
        precondition(!expected.matches(SystemKeyboard.Field(value: expected.value, selection: CFRange(location: 0, length: 0), metadata: [:])))
        textChecks += 1
        let composed = SystemKeyboard.Field(value: "é", selection: CFRange(location: 2, length: 0), metadata: [:])
        let decomposed = SystemKeyboard.TextState(value: "e\u{301}", units: Array("e\u{301}".utf16), selection: composed.selection)
        precondition(decomposed.value == composed.value && !decomposed.matches(composed))
        textChecks += 1
        try SystemKeyboard.textFieldAllowed(area, text: "\r\n\t"); textChecks += 1
        let textFailures: [() throws -> Void] = [
            { _ = try SystemKeyboard.textChunks("e" + String(repeating: "\u{301}", count: 16)) },
            { _ = try SystemKeyboard.textChunks("a", capacity: 1) },
            { _ = try SystemKeyboard.textChunks("a\u{1b}") },
            { try SystemKeyboard.checkedUnicode([65], actualCount: 0, actual: []) },
            { try SystemKeyboard.checkedUnicode([65], actualCount: 1, actual: [66]) },
            { _ = try SystemKeyboard.expectedText(SystemKeyboard.Field(value: "😀", selection: CFRange(location: 1, length: 0), metadata: [:]), inserting: [65]) },
            { _ = try SystemKeyboard.expectedText(SystemKeyboard.Field(value: String(repeating: "😀", count: SystemKeyboard.maxValueBytes / 4), selection: CFRange(location: 0, length: 0), metadata: [:]), inserting: [65]) },
        ]
        for check in textFailures {
            do { try check(); fatalError("Unsafe Unicode text accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); textChecks += 1 }
        }
        for subrole in ["", "AXSearchField"] {
            let field = SystemKeyboard.Field(value: "", selection: CFRange(location: 0, length: 0), metadata: ["role": "AXTextField", "subrole": subrole])
            do { try SystemKeyboard.textFieldAllowed(field, text: "\n"); fatalError("Single-line control accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); textChecks += 1 }
        }
        let pieces = try SystemKeyboard.textChunks("0123456789abcdef😀x")
        var unit: [UniChar] = [], received: [UniChar] = [], posts: [Bool] = [], validated: [Int] = []
        let textReceipt = try await SystemKeyboard.writeText(pieces, prepare: { unit = $0 }, validate: {
            validated.append($0)
            if $0 > 0 { precondition(!received.isEmpty) } // Own insertion does not require the old value revision.
        }, sameGeneration: { true }, post: { down in
            posts.append(down); if down { received += unit }
        }, verify: { received.elementsEqual("0123456789abcdef😀x".utf16) })
        precondition(posts == [true, false, true, false] && validated == [0, 1])
        precondition(textReceipt["text_verified"] as? Bool == true && textReceipt["return_posted"] as? Bool == false)
        textChecks += 1
        for scenario in ["target_before", "target_after", "capacity_before", "capacity_after", "verification"] {
            var prepared = 0, postCount = 0, returnCount = 0
            do {
                _ = try await SystemKeyboard.writeText(pieces, prepare: { _ in
                    let index = prepared; prepared += 1
                    if scenario == "capacity_\(index == 0 ? "before" : "after")" {
                        throw SystemControl.failure("capacity", "fixture")
                    }
                }, validate: { index in
                    if scenario == "target_\(index == 0 ? "before" : "after")" {
                        throw SystemControl.failure("target", "fixture")
                    }
                }, sameGeneration: { true }, post: { _ in postCount += 1 }, verify: { false },
                    submit: true, returnPair: { returnCount += 1 })
                fatalError("Unsafe text write completed")
            } catch let error as SystemBridgeFailure {
                let before = scenario.hasSuffix("before")
                precondition(error.effectUnknown == !before)
                precondition(postCount == (before ? 0 : scenario == "verification" ? 4 : 2))
                precondition(returnCount == 0)
                textChecks += 1
            }
        }
        do {
            _ = try SystemKeyboard.submitIntent(["submit": 1])
            fatalError("Non-Boolean text submit")
        } catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); textChecks += 1 }
        var returnChecks = 0
        let defaultSubmit = try SystemKeyboard.submitIntent([:])
        let falseSubmit = try SystemKeyboard.submitIntent(["submit": false])
        let trueSubmit = try SystemKeyboard.submitIntent(["submit": true])
        precondition(!defaultSubmit && !falseSubmit && trueSubmit); returnChecks += 1
        let invalidSubmit: [Any] = [0, 1, "false", NSNull()]
        for value in invalidSubmit {
            do { _ = try SystemKeyboard.submitIntent(["submit": value]); fatalError("Coerced submit") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); returnChecks += 1 }
        }
        var noReturn = 0
        let withoutReturn = try await SystemKeyboard.writeText([pieces[0]], prepare: { _ in }, validate: { _ in },
            sameGeneration: { true }, post: { _ in }, verify: { true }, returnPair: { noReturn += 1 })
        precondition(noReturn == 0 && withoutReturn["return_posted"] as? Bool == false); returnChecks += 1
        var returnOrder: [String] = []
        let withReturn = try await SystemKeyboard.writeText(pieces, prepare: { _ in }, validate: { _ in },
            sameGeneration: { true }, post: { returnOrder.append($0 ? "text_down" : "text_up") },
            verify: { returnOrder.append("verified"); return true }, submit: true, returnPair: {
                _ = try SystemKeyboard.postPair(validate: { returnOrder.append("return_guard") }, sameGeneration: { true },
                    post: { returnOrder.append($0 ? "return_down" : "return_up") })
            })
        precondition(returnOrder == ["text_down", "text_up", "text_down", "text_up", "verified", "return_guard", "return_down", "return_up"])
        precondition(withReturn["return_posted"] as? Bool == true && withReturn["post_calls_returned"] as? Int == 6)
        precondition(withReturn["submitted"] as? Bool == false && withReturn["app_processing_confirmed"] as? Bool == false)
        returnChecks += 1
        let actualReturn = try SystemKeyboard.events(textLayout, code: UInt16(kVK_Return), flags: [])
        precondition(actualReturn.0.getIntegerValueField(.keyboardEventKeycode) == 36
                     && actualReturn.1.getIntegerValueField(.keyboardEventKeycode) == 36)
        precondition(actualReturn.0.flags.isEmpty && actualReturn.1.flags.isEmpty); returnChecks += 1
        do { try SystemKeyboard.inputAllowed(postAccess: true, flags: [], keyHeld: true); fatalError("Held Return accepted") }
        catch let error as SystemBridgeFailure {
            precondition(error.message.contains("conflict_mask=0") && error.message.contains("key_held=true")); returnChecks += 1
        }
        for scenario in ["verify", "guard", "post"] {
            var textPosts = 0, returnPosts: [Bool] = []
            do {
                _ = try await SystemKeyboard.writeText([pieces[0]], prepare: { _ in }, validate: { _ in },
                    sameGeneration: { true }, post: { _ in textPosts += 1 }, verify: { scenario != "verify" },
                    submit: true, returnPair: {
                        _ = try SystemKeyboard.postPair(validate: {
                            if scenario == "guard" { throw SystemControl.failure("changed", "fixture") }
                        }, sameGeneration: { true }, post: { down in
                            returnPosts.append(down)
                            if down && scenario == "post" { throw SystemControl.failure("lost", "fixture") }
                        })
                    })
                fatalError("Unsafe optional Return accepted")
            } catch let error as SystemBridgeFailure {
                precondition(error.effectUnknown && textPosts == 2)
                precondition(returnPosts == (scenario == "post" ? [true, false] : [])); returnChecks += 1
            }
        }
        var cancelReturn = 0
        let cancelledText = Task { @MainActor in
            try await SystemKeyboard.writeText([pieces[0]], prepare: { _ in }, validate: { _ in }, sameGeneration: { true },
                post: { _ in }, verify: { withUnsafeCurrentTask { $0?.cancel() }; return true },
                submit: true, returnPair: { cancelReturn += 1 })
        }
        do { _ = try await cancelledText.value; fatalError("Return after cancellation") }
        catch let error as SystemBridgeFailure { precondition(error.effectUnknown && cancelReturn == 0); returnChecks += 1 }
        do {
            _ = try await SystemKeyboard.writeText([pieces[0]], prepare: { _ in }, validate: { _ in },
                sameGeneration: { true }, post: { _ in }, verify: { true }, submit: true)
            fatalError("Missing Return callback accepted")
        } catch let error as SystemBridgeFailure { precondition(error.effectUnknown); returnChecks += 1 }
        var axChecks = 0
        for (status, flag, expected) in [(AXError.success, true, true), (.success, false, false),
                                       (.attributeUnsupported, false, false), (.notImplemented, false, false)] {
            let writable = try SystemKeyboard.selectedTextWritable(status: status, settable: flag)
            precondition(writable == expected); axChecks += 1
        }
        for status in [AXError.cannotComplete, .invalidUIElement, .apiDisabled, .noValue] {
            do { _ = try SystemKeyboard.selectedTextWritable(status: status, settable: false); fatalError("Uncertain capability accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown); axChecks += 1 }
        }
        let axLiteral = "\u{FEFF}e" + String(repeating: "\u{301}", count: 17) + "😀"
        try SystemKeyboard.validateText(axLiteral)
        let axExpected = try SystemKeyboard.expectedText(area, inserting: Array(axLiteral.utf16))
        let cfLiteral = axLiteral as CFString
        var cfUnits = [UniChar](repeating: 0, count: CFStringGetLength(cfLiteral))
        CFStringGetCharacters(cfLiteral, CFRange(location: 0, length: cfUnits.count), &cfUnits)
        precondition(cfUnits.elementsEqual(axLiteral.utf16))
        var axField = area, axSets = 0, axReturns = 0
        let axReceipt = try await SystemKeyboard.writeSelectedText(validate: {}, setter: {
            axSets += 1
            axField = SystemKeyboard.Field(value: axExpected.value, selection: axExpected.selection, metadata: area.metadata)
            return .success
        }, verify: { axExpected.matches(axField) }, returnPair: { axReturns += 1 })
        precondition(axSets == 1 && axReturns == 0 && axReceipt["insertion_method"] as? String == "ax_selected_text")
        precondition(axReceipt["text_event_count"] as? Int == 0 && axReceipt["post_calls_returned"] as? Int == 0)
        precondition(axReceipt["ax_set_calls_returned"] as? Int == 1 && axReceipt["text_verified"] as? Bool == true)
        axChecks += 1
        var axReturnOrder: [Bool] = []
        let axSubmitted = try await SystemKeyboard.writeSelectedText(validate: {}, setter: { .success }, verify: { true },
            submit: true, returnPair: {
                _ = try SystemKeyboard.postPair(validate: {}, sameGeneration: { true }, post: { axReturnOrder.append($0) })
            })
        precondition(axReturnOrder == [true, false] && axSubmitted["text_event_count"] as? Int == 0)
        precondition(axSubmitted["post_calls_returned"] as? Int == 2 && axSubmitted["return_posted"] as? Bool == true)
        precondition(axSubmitted["submitted"] as? Bool == false && axSubmitted["app_processing_confirmed"] as? Bool == false)
        axChecks += 1
        for scenario in ["guard", "setter_status", "setter_throw", "verify", "return_guard"] {
            var sets = 0, observed = 0, returns = 0
            do {
                _ = try await SystemKeyboard.writeSelectedText(validate: {
                    if scenario == "guard" { throw SystemControl.failure("changed", "fixture") }
                }, setter: {
                    sets += 1 // A failed setter may already have changed the target.
                    if scenario == "setter_throw" { throw SystemControl.failure("lost", "fixture") }
                    return scenario == "setter_status" ? .cannotComplete : .success
                }, verify: { observed += 1; return scenario != "verify" }, submit: true, returnPair: {
                    _ = try SystemKeyboard.postPair(validate: { throw SystemControl.failure("changed", "fixture") },
                        sameGeneration: { true }, post: { _ in returns += 1 })
                })
                fatalError("Unsafe AX insertion completed")
            } catch let error as SystemBridgeFailure {
                precondition(error.effectUnknown == (scenario != "guard") && sets == (scenario == "guard" ? 0 : 1))
                precondition(returns == 0 && observed == (["verify", "return_guard"].contains(scenario) ? 1 : 0))
                axChecks += 1
            }
        }
        var cancelledSets = 0, cancelledReturns = 0
        let cancelledAX = Task { @MainActor in
            try await SystemKeyboard.writeSelectedText(validate: {}, setter: { cancelledSets += 1; return .success },
                verify: { withUnsafeCurrentTask { $0?.cancel() }; return true }, submit: true,
                returnPair: { cancelledReturns += 1 })
        }
        do { _ = try await cancelledAX.value; fatalError("Return after AX cancellation") }
        catch let error as SystemBridgeFailure {
            precondition(error.effectUnknown && cancelledSets == 1 && cancelledReturns == 0); axChecks += 1
        }
        let fixture = try JSONSerialization.jsonObject(with: FileHandle.standardInput.readDataToEndOfFile()) as! [String: Any]
        var manifest = fixture["begin"] as! [String: Any]
        var stageTarget = manifest["target"] as! [String: Any]
        stageTarget["helper_pid"] = Int(getpid()); stageTarget["worker_generation"] = SystemBridgeRuntime.generation
        manifest["target"] = stageTarget
        // Preserve Python canonical bytes, including 123.0. Only substitute this private process identity.
        let canonical = (manifest["binding_json"] as! String)
            .replacingOccurrences(of: "\"helper_pid\":11111111", with: "\"helper_pid\":\(getpid())")
            .replacingOccurrences(of: "00000000-0000-0000-0000-000000000000", with: SystemBridgeRuntime.generation)
        func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        manifest["binding_json"] = canonical; manifest["transfer_id"] = sha(Data(canonical.utf8))
        let expectedBytes = Data(base64Encoded: fixture["expected_utf8_b64"] as! String)!
        let expectedLarge = String(decoding: expectedBytes, as: UTF8.self)
        precondition(expectedLarge.unicodeScalars.first?.value == 0xFEFF && expectedLarge.utf8.count > 65536)
        let basePackets = fixture["chunks"] as! [[String: Any]]
        SystemBridgeRuntime.principal = "fixture_owner"
        SystemKeyboard.transfer = nil; SystemKeyboard.consumedTransfers = []
        var stageChecks = 0, writes = 0, caseNumber = 0
        let rawText = try await SystemKeyboard.handle("keyboard.text", arguments: [:])
        precondition(rawText == nil); stageChecks += 1 // Only the staged binary codec reaches the text writer.
        func signed(_ candidate: [String: Any]) throws -> [String: Any] {
            var result = candidate.filter { !["transfer_id", "binding_json"].contains($0.key) }
            let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
            result["binding_json"] = String(data: data, encoding: .utf8)!; result["transfer_id"] = sha(data)
            return result
        }
        func fresh() throws -> [String: Any] {
            caseNumber += 1
            var result = manifest; result["task_id"] = "stage_case_\(caseNumber)"
            return try signed(result)
        }
        func packets(_ value: [String: Any]) -> [[String: Any]] {
            basePackets.map { var packet = $0; packet["transfer_id"] = value["transfer_id"]; return packet }
        }
        func fill(_ value: [String: Any], now: Double = 10) throws {
            SystemKeyboard.transfer = nil
            let accepted = try SystemKeyboard.beginTransfer(value, now: now)
            precondition(accepted["state"] as? String == "accepted" && accepted["input_attempted"] as? Bool == false)
            var count = 0
            for packet in packets(value) {
                let receipt = try SystemKeyboard.chunkTransfer(packet, now: now)
                count += 1
                precondition(receipt["state"] as? String == "received" && receipt["received_chunks"] as? Int == count)
                precondition(receipt["input_attempted"] as? Bool == false)
            }
        }
        func refusedStage(_ body: () async throws -> Void) async throws {
            let before = writes
            do { try await body(); fatalError("Unsafe staging accepted") }
            catch let error as SystemBridgeFailure { precondition(!error.effectUnknown && writes == before); stageChecks += 1 }
        }
        let writer: ([String: Any]) async throws -> [String: Any] = { payload in
            writes += 1
            precondition((payload["text"] as! String).utf8.elementsEqual(expectedLarge.utf8))
            let targetHash = try SystemControl.hash(payload["target"]!)
            let expectedTargetHash = try SystemControl.hash(stageTarget)
            precondition(targetHash == expectedTargetHash)
            precondition(payload["submit"] as? Bool == false)
            return ["text_verified": true]
        }
        try fill(manifest)
        let reference = ["transfer_id": manifest["transfer_id"]!]
        let committed = try await SystemKeyboard.commitTransfer(reference, now: 10, writer: writer)
        precondition(writes == 1 && committed["staging_verified"] as? Bool == true && SystemKeyboard.transfer == nil)
        stageChecks += 1
        try await refusedStage { _ = try await SystemKeyboard.commitTransfer(reference, now: 10, writer: writer) }
        try await refusedStage { _ = try SystemKeyboard.beginTransfer(manifest, now: 10) }
        var tampered = try fresh(); tampered["utf8_bytes"] = 100
        try await refusedStage { _ = try SystemKeyboard.beginTransfer(tampered, now: 10) }
        var missing = try fresh(); missing.removeValue(forKey: "binding_json")
        try await refusedStage { _ = try SystemKeyboard.beginTransfer(missing, now: 10) }
        var malformed = try fresh(); malformed["binding_json"] = "{"; malformed["transfer_id"] = sha(Data("{".utf8))
        try await refusedStage { _ = try SystemKeyboard.beginTransfer(malformed, now: 10) }
        var oldWorker = try fresh(), oldTarget = stageTarget
        oldTarget["worker_generation"] = "00000000-0000-0000-0000-000000000000"; oldWorker["target"] = oldTarget
        oldWorker = try signed(oldWorker)
        try await refusedStage { _ = try SystemKeyboard.beginTransfer(oldWorker, now: 10) }
        let invalidManifestFields: [(String, Any)] = [("principal", "foreign"), ("submit", 1), ("encoding", "utf-16-be"), ("utf8_bytes", 1048577)]
        for (key, value) in invalidManifestFields {
            var invalid = try fresh(); invalid[key] = value; invalid = try signed(invalid)
            try await refusedStage { _ = try SystemKeyboard.beginTransfer(invalid, now: 10) }
        }
        let pending = try fresh(), other = try fresh()
        _ = try SystemKeyboard.beginTransfer(pending, now: 10)
        try await refusedStage { _ = try SystemKeyboard.beginTransfer(other, now: 10) }
        let aborted = try SystemKeyboard.abortTransfer(["transfer_id": pending["transfer_id"]!], now: 10)
        precondition(aborted["state"] as? String == "aborted" && SystemKeyboard.transfer == nil)
        let ordered = try fresh(); _ = try SystemKeyboard.beginTransfer(ordered, now: 10)
        let firstPacket = packets(ordered)[0]
        var outOfOrder = firstPacket; outOfOrder["index"] = 1
        try await refusedStage { _ = try SystemKeyboard.chunkTransfer(outOfOrder, now: 10) }
        var wrongID = firstPacket; wrongID["transfer_id"] = String(repeating: "f", count: 64)
        try await refusedStage { _ = try SystemKeyboard.chunkTransfer(wrongID, now: 10) }
        _ = try SystemKeyboard.chunkTransfer(firstPacket, now: 10)
        try await refusedStage { _ = try SystemKeyboard.chunkTransfer(firstPacket, now: 10) }
        try await refusedStage {
            SystemBridgeRuntime.principal = "foreign"; defer { SystemBridgeRuntime.principal = "fixture_owner" }
            _ = try SystemKeyboard.chunkTransfer(packets(ordered)[1], now: 10)
        }
        try await refusedStage {
            SystemBridgeRuntime.principal = "foreign"; defer { SystemBridgeRuntime.principal = "fixture_owner" }
            _ = try await SystemKeyboard.commitTransfer(["transfer_id": ordered["transfer_id"]!], now: 10, writer: writer)
        }
        SystemKeyboard.transfer = nil
        let invalidBytes = try fresh(); _ = try SystemKeyboard.beginTransfer(invalidBytes, now: 10)
        for bytes in [Data([0, 216]), Data([65]), Data(repeating: 65, count: 32770)] {
            var packet = packets(invalidBytes)[0]; packet["data_b64"] = bytes.base64EncodedString()
            try await refusedStage { _ = try SystemKeyboard.chunkTransfer(packet, now: 10) }
        }
        SystemKeyboard.transfer = nil
        var quota = try fresh(); quota["utf8_bytes"] = 1; quota["utf16_units"] = 1; quota["chunk_count"] = 1
        quota = try signed(quota); _ = try SystemKeyboard.beginTransfer(quota, now: 10)
        let overQuota: [String: Any] = ["transfer_id": quota["transfer_id"]!, "index": 0, "data_b64": Data([65, 0, 66, 0]).base64EncodedString()]
        try await refusedStage { _ = try SystemKeyboard.chunkTransfer(overQuota, now: 10) }
        SystemKeyboard.transfer = nil
        let incomplete = try fresh(); _ = try SystemKeyboard.beginTransfer(incomplete, now: 10)
        try await refusedStage { _ = try await SystemKeyboard.commitTransfer(["transfer_id": incomplete["transfer_id"]!], now: 10, writer: writer) }
        var wrongHash = try fresh(); wrongHash["sha256"] = String(repeating: "c", count: 64); wrongHash = try signed(wrongHash)
        try fill(wrongHash)
        try await refusedStage { _ = try await SystemKeyboard.commitTransfer(["transfer_id": wrongHash["transfer_id"]!], now: 10, writer: writer) }
        let expired = try fresh(); _ = try SystemKeyboard.beginTransfer(expired, now: 10)
        try await refusedStage { _ = try SystemKeyboard.chunkTransfer(packets(expired)[0], now: 70) }
        precondition(SystemKeyboard.transfer == nil)
        let uncertain = try fresh(); try fill(uncertain)
        do {
            _ = try await SystemKeyboard.commitTransfer(["transfer_id": uncertain["transfer_id"]!], now: 10, writer: { _ in
                writes += 1; throw SystemControl.failure("lost", "fixture", unknown: true)
            })
            fatalError("Expected uncertain text writer")
        } catch let error as SystemBridgeFailure { precondition(error.effectUnknown && writes == 2) }
        do {
            _ = try await SystemKeyboard.commitTransfer(["transfer_id": uncertain["transfer_id"]!], now: 10, writer: writer)
            fatalError("Uncertain commit replayed")
        } catch let error as SystemBridgeFailure { precondition(!error.effectUnknown && writes == 2) }
        do { _ = try SystemKeyboard.beginTransfer(uncertain, now: 10); fatalError("Uncertain stage replayed") }
        catch let error as SystemBridgeFailure { precondition(!error.effectUnknown && writes == 2) }
        stageChecks += 1
        var submitManifest = try fresh(); submitManifest["submit"] = true; submitManifest = try signed(submitManifest)
        try fill(submitManifest)
        precondition(SystemKeyboard.transfer?.submit == true)
        var sawSubmit = false
        _ = try await SystemKeyboard.commitTransfer(["transfer_id": submitManifest["transfer_id"]!], now: 10, writer: {
            sawSubmit = $0["submit"] as? Bool == true
            return ["return_posted": true]
        })
        precondition(sawSubmit && SystemKeyboard.transfer == nil); stageChecks += 1
        SystemKeyboard.transfer = nil; SystemKeyboard.consumedTransfers = []; SystemBridgeRuntime.principal = ""
        // Window-less app: only an observed empty AX window list counts; only Command chords pass.
        var windowlessChecks = 0
        let emptyWindows = [AnyObject]() as CFArray, oneWindow = [AXUIElementCreateSystemWide()] as CFArray
        precondition(SystemKeyboard.windowlessApplication(focusedWindow: nil, windows: emptyWindows))
        precondition(!SystemKeyboard.windowlessApplication(focusedWindow: nil, windows: nil))
        precondition(!SystemKeyboard.windowlessApplication(focusedWindow: nil, windows: oneWindow))
        precondition(!SystemKeyboard.windowlessApplication(focusedWindow: AXUIElementCreateSystemWide(), windows: emptyWindows))
        precondition(!SystemKeyboard.windowlessApplication(focusedWindow: nil, windows: "AXWindow" as CFString))
        windowlessChecks += 5
        try SystemKeyboard.requireWindowlessShortcut(SystemKeyboard.windowlessMetadata, chord: true, modifiers: ["command"])
        try SystemKeyboard.requireWindowlessShortcut(observed.metadata, chord: false, modifiers: [])
        windowlessChecks += 2
        for (chord, modifiers) in [(false, [String]()), (true, ["shift"]), (true, ["control", "option"])] {
            do {
                try SystemKeyboard.requireWindowlessShortcut(SystemKeyboard.windowlessMetadata, chord: chord, modifiers: modifiers)
                fatalError("Window-less app accepted a non-Command key")
            } catch let error as SystemBridgeFailure { precondition(error.code == "keyboard_unsupported" && !error.effectUnknown) }
            windowlessChecks += 1
        }
        let result: [String: Any] = ["checks": checks, "field": observed.metadata,
                                   "windowless_checks": windowlessChecks,
                                   "key_checks": keyChecks, "named_key_codes": SystemKeyboard.namedKeys,
                                   "extended_key_checks": extendedKeyChecks,
                                   "fn_navigation_checks": fnNavigationChecks,
                                   "layout_checks": layoutChecks, "layout_positions": layoutPositions,
                                   "text_checks": textChecks,
                                   "stage_checks": stageChecks,
                                   "return_checks": returnChecks,
                                   "ax_checks": axChecks,
                                   "native_ui_calls": 0, "event_posts": 0, "permission_requests": 0]
        print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
    }
}

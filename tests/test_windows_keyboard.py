"""Documented Win32 event/guard contracts, injected API; not guest acceptance."""

import ctypes
import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.windows.keyboard import (
    EXTENDED,
    INPUT,
    KEYBDINPUT,
    KEYUP,
    SCANCODE,
    UNICODE,
    KeyStroke,
    Win32KeyboardAPI,
    WindowsKeyboard,
    WindowTarget,
)


class FakeWin32:
    def __init__(self, layout=0x04090409):
        self.target = WindowTarget(100, 400, 132000000000000000, 401, layout)
        self.calls = []
        self.held = set()
        self.modifiers = ()
        self.desktop_available = True
        self.ack = None
        self.after_send = None

    def foreground(self):
        return self.target

    def validate_desktop(self):
        if not self.desktop_available:
            raise BridgeError("windows_desktop_unavailable", "locked")

    def pressed_modifiers(self):
        return self.modifiers

    def key_is_down(self, vk):
        return vk in self.held

    def map_character(self, char, layout):
        if char == "@":
            return (0x51, 6) if layout == 0x04070407 else (0x32, 1)
        if char == "ä" and layout == 0x04070407:
            return 0xDE, 0
        if len(char) == 1 and "a" <= char <= "z":
            return ord(char.upper()), 0
        raise BridgeError("windows_key_unavailable", "unmapped")

    def map_scan(self, vk, layout):
        scans = {
            0x53: 0x1F,
            0x41: 0x1E,
            0x42: 0x30,
            0x54: 0x14,
            0x45: 0x12,
            0x52: 0x13,
            0x4E: 0x31,
            0x20: 0x39,
            0x4D: 0x32,
            0x51: 0x10,
            0x32: 0x03,
            0xDE: 0x28,
            0x0D: 0x1C,
            0xA0: 0x2A,
            0xA2: 0x1D,
            0xA4: 0x38,
            0x5B: 0x5B,
            0x25: 0x4B,
            0x59: 0x2C if layout == 0x04070407 else 0x15,
        }
        if vk not in scans:
            raise BridgeError("windows_key_unavailable", "unmapped")
        return scans[vk], vk in (0x5B, 0x25)

    def map_scan_to_virtual(self, scan, extended, layout):
        return 0x25 if extended and scan == 0x4B else 0x41

    def send_input(self, events):
        self.calls.append(events)
        if self.after_send:
            self.after_send()
        if isinstance(self.ack, Exception):
            raise self.ack
        return self.ack if self.ack is not None else (len(events), 0)


def expect_error(code, fn):
    with pytest.raises(BridgeError) as error:
        fn()
    assert error.value.code == code
    return error.value


def test_win32_fixed_width_abi_on_lp64_test_hosts():
    # INPUT is 40 bytes on Windows x64, 28 on x86. Do not use host c_ulong.
    pointer64 = ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(KEYBDINPUT) == (24 if pointer64 else 16)
    assert ctypes.sizeof(INPUT) == (40 if pointer64 else 28)
    assert INPUT.payload.offset == (8 if pointer64 else 4)


def test_target_wire_uses_exact_strings_beyond_javascript_integer_precision():
    target = WindowTarget(2**53 + 3, 400, 132000000000000003, 401, 2**63 + 1)
    value = json.loads(json.dumps(target.to_wire()))
    assert value["hwnd"] == "9007199254740995"
    assert value["process_created_100ns"] == "132000000000000003"
    assert value["keyboard_layout"] == "9223372036854775809"
    assert WindowTarget.from_wire(value) == target
    value["process_created_100ns"] = 132000000000000003
    with pytest.raises(ValueError):
        WindowTarget.from_wire(value)


@pytest.mark.parametrize("value", ["01", "0", "+3", "1e2", "１", "9" * 21])
def test_target_wire_rejects_ambiguous_or_unbounded_opaque_identity(value):
    target = FakeWin32().target.to_wire()
    target["hwnd"] = value
    with pytest.raises(ValueError):
        WindowTarget.from_wire(target)


@pytest.mark.skipif(os.name == "nt", reason="Windows native constructor is valid")
def test_native_constructor_never_posts_host_macos_keys():
    expect_error("unsupported_platform", WindowsKeyboard)


def test_eight_real_strokes_keep_shift_owned_and_pairs_ordered():
    api = FakeWin32()
    strokes = [KeyStroke(character="S", modifiers=("shift",))]
    strokes.extend(
        KeyStroke(named="space") if c == " " else KeyStroke(character=c) for c in "tern am"
    )
    hook_calls = []
    result = WindowsKeyboard(api).send(
        api.target, strokes, before_send=lambda: hook_calls.append(1)
    )
    assert result["completed_keys"] == result["requested_keys"] == len(api.calls) == 8
    assert result["inserted_events"] == 18
    assert len(hook_calls) == 8
    assert result["physical_key_events"] and not result["receiver_processing_confirmed"]
    first = api.calls[0]
    assert [(e.scan_code, bool(e.flags & KEYUP)) for e in first] == [
        (0x2A, False),
        (0x1F, False),
        (0x1F, True),
        (0x2A, True),
    ]
    assert all(e.flags & SCANCODE for call in api.calls for e in call)
    assert len({e.extra_info for call in api.calls for e in call}) == 1


def test_character_case_does_not_silently_add_shift():
    api = FakeWin32()
    WindowsKeyboard(api).send(api.target, [KeyStroke(character="A")])
    assert len(api.calls[0]) == 2
    assert [e.scan_code for e in api.calls[0]] == [0x1E, 0x1E]


@pytest.mark.parametrize("layout,scan", [(0x04090409, 0x15), (0x04070407, 0x2C)])
def test_logical_base_label_uses_target_us_or_german_layout(layout, scan):
    api = FakeWin32(layout)
    WindowsKeyboard(api).send(api.target, [KeyStroke(character="y")])
    assert [e.scan_code for e in api.calls[0]] == [scan, scan]


@pytest.mark.parametrize(
    "layout,mods,vk", [(0x04090409, ("shift",), 0x32), (0x04070407, ("control", "alt"), 0x51)]
)
def test_layout_required_modifiers_are_explicit(layout, mods, vk):
    api = FakeWin32(layout)
    keyboard = WindowsKeyboard(api)
    expect_error(
        "windows_key_modifiers_required",
        lambda: keyboard.send(api.target, [KeyStroke(character="@")]),
    )
    assert not api.calls
    keyboard.send(api.target, [KeyStroke(character="@", modifiers=mods)])
    assert api.calls[0][len(mods)].virtual_key == vk
    assert len(api.calls[0]) == 2 + 2 * len(mods)


def test_unicode_packets_are_explicit_not_physical_and_preserve_surrogates():
    api = FakeWin32()
    result = WindowsKeyboard(api).send(api.target, [KeyStroke(unicode="😀")])
    assert not result["physical_key_events"]
    assert [(e.virtual_key, e.scan_code, e.flags) for e in api.calls[0]] == [
        (0, 0xD83D, UNICODE),
        (0, 0xD83D, UNICODE | KEYUP),
        (0, 0xDE00, UNICODE),
        (0, 0xDE00, UNICODE | KEYUP),
    ]


@pytest.mark.parametrize(
    "stroke", [KeyStroke(named="keypad_enter"), KeyStroke(scan_code=0x4B, extended=True)]
)
def test_extended_keys_keep_e0_flag_and_matching_release(stroke):
    api = FakeWin32()
    WindowsKeyboard(api).send(api.target, [stroke])
    down, up = api.calls[0]
    assert down.flags == SCANCODE | EXTENDED
    assert up.flags == SCANCODE | EXTENDED | KEYUP


@pytest.mark.parametrize(
    "name,scan",
    [
        ("left", 0x4B),
        ("right", 0x4D),
        ("up", 0x48),
        ("down", 0x50),
        ("home", 0x47),
        ("end", 0x4F),
        ("page_up", 0x49),
        ("page_down", 0x51),
        ("insert", 0x52),
        ("delete", 0x53),
        ("print_screen", 0x37),
        ("keypad_divide", 0x35),
        ("keypad_enter", 0x1C),
    ],
)
def test_named_enhanced_keys_reach_native_input_encoder_with_e0_even_if_mapping_omits_it(
    name, scan, monkeypatch
):
    captured = []

    def native_send(count, records, size):
        assert count == 2 and size == ctypes.sizeof(INPUT)
        captured.extend((item.type, item.ki.wScan, item.ki.dwFlags) for item in records)
        return count

    encoder = Win32KeyboardAPI.__new__(Win32KeyboardAPI)
    encoder.user = SimpleNamespace(SendInput=native_send)
    monkeypatch.setattr(ctypes, "set_last_error", lambda value: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    api = FakeWin32()
    api.map_scan = lambda vk, layout: (scan, False)
    api.send_input = encoder.send_input
    result = WindowsKeyboard(api).send(api.target, [KeyStroke(named=name)])
    assert result["inserted_events"] == 2
    assert captured == [(1, scan, SCANCODE | EXTENDED), (1, scan, SCANCODE | EXTENDED | KEYUP)]


@pytest.mark.parametrize(
    "name,scan",
    [
        ("enter", 0x1C),
        ("keypad_0", 0x52),
        ("keypad_1", 0x4F),
        ("keypad_2", 0x50),
        ("keypad_3", 0x51),
        ("keypad_4", 0x4B),
        ("keypad_6", 0x4D),
        ("keypad_7", 0x47),
        ("keypad_8", 0x48),
        ("keypad_9", 0x49),
        ("keypad_decimal", 0x53),
        ("num_lock", 0x45),
    ],
)
def test_main_enter_and_numeric_keypad_do_not_gain_navigation_e0_flag(name, scan):
    api = FakeWin32()
    api.map_scan = lambda vk, layout: (scan, False)
    WindowsKeyboard(api).send(api.target, [KeyStroke(named=name)])
    assert [(event.scan_code, event.flags) for event in api.calls[0]] == [
        (scan, SCANCODE),
        (scan, SCANCODE | KEYUP),
    ]


def test_explicit_unextended_raw_scan_is_not_reinterpreted_as_named_navigation():
    api = FakeWin32()
    WindowsKeyboard(api).send(api.target, [KeyStroke(scan_code=0x4D)])
    assert [event.flags for event in api.calls[0]] == [SCANCODE, SCANCODE | KEYUP]


def test_windows_modifier_keeps_e0_when_mapping_omits_prefix():
    api = FakeWin32()
    api.map_scan = lambda vk, layout: (0x5B if vk == 0x5B else 0x1E, False)
    WindowsKeyboard(api).send(api.target, [KeyStroke(character="a", modifiers=("windows",))])
    assert [(event.scan_code, event.flags) for event in api.calls[0]] == [
        (0x5B, SCANCODE | EXTENDED),
        (0x1E, SCANCODE),
        (0x1E, SCANCODE | KEYUP),
        (0x5B, SCANCODE | EXTENDED | KEYUP),
    ]


def test_pause_uses_virtual_key_not_invented_e1_scan_sequence():
    api = FakeWin32()
    WindowsKeyboard(api).send(api.target, [KeyStroke(named="pause")])
    assert [(e.virtual_key, e.scan_code, e.flags) for e in api.calls[0]] == [
        (0x13, 0, 0),
        (0x13, 0, KEYUP),
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("hwnd", 101),
        ("pid", 402),
        ("process_created_100ns", 132000000000000001),
        ("thread_id", 403),
        ("keyboard_layout", 0x04070407),
    ],
)
def test_each_pinned_target_identity_change_blocks_before_input(field, value):
    api = FakeWin32()
    stale = api.target
    api.target = replace(api.target, **{field: value})
    expect_error(
        "windows_target_changed",
        lambda: WindowsKeyboard(api).send(stale, [KeyStroke(character="a")]),
    )
    assert not api.calls


def test_locked_desktop_and_held_modifiers_or_base_key_never_inject():
    api = FakeWin32()
    keyboard = WindowsKeyboard(api)
    api.desktop_available = False
    expect_error(
        "windows_desktop_unavailable", lambda: keyboard.send(api.target, [KeyStroke(character="a")])
    )
    api.desktop_available = True
    api.modifiers = ("right_control",)
    expect_error(
        "windows_modifiers_busy", lambda: keyboard.send(api.target, [KeyStroke(character="a")])
    )
    api.modifiers = ()
    api.held.add(0x41)
    expect_error("windows_key_busy", lambda: keyboard.send(api.target, [KeyStroke(character="a")]))
    expect_error("windows_key_busy", lambda: keyboard.send(api.target, [KeyStroke(scan_code=0x1E)]))
    assert not api.calls


def test_all_keys_validate_before_any_effect():
    api = FakeWin32()
    expect_error(
        "windows_key_unavailable",
        lambda: WindowsKeyboard(api).send(
            api.target, [KeyStroke(character="a"), KeyStroke(character="ä")]
        ),
    )
    assert not api.calls


def test_authorization_hook_and_fresh_target_after_hook():
    api = FakeWin32()

    def change_focus():
        api.target = replace(api.target, hwnd=200)

    expect_error(
        "windows_target_changed",
        lambda: WindowsKeyboard(api).send(
            api.target, [KeyStroke(character="a")], before_send=change_focus
        ),
    )
    assert not api.calls


@pytest.mark.parametrize("ack", [(0, 5), (1, 0), (3, 0), OSError("native failure")])
def test_zero_partial_invalid_or_exception_after_call_is_unknown_without_replay(ack):
    api = FakeWin32()
    api.ack = ack
    with pytest.raises(UncertainExecution) as error:
        WindowsKeyboard(api).send(api.target, [KeyStroke(character="a"), KeyStroke(character="b")])
    assert len(api.calls) == 1
    assert error.value.provider_error["completed_keys"] == 0
    assert not error.value.provider_error["automatic_retry"]


def test_later_focus_loss_retains_completed_count_without_new_target_input():
    api = FakeWin32()
    target = api.target
    api.after_send = lambda: setattr(api, "target", replace(target, hwnd=200))
    with pytest.raises(UncertainExecution) as error:
        WindowsKeyboard(api).send(target, [KeyStroke(character="a"), KeyStroke(character="b")])
    assert error.value.provider_error["completed_keys"] == 1
    assert error.value.provider_error["cause_code"] == "windows_target_changed"
    assert len(api.calls) == 1


def test_permission_revocation_after_first_key_stops_sequence_unknown():
    api = FakeWin32()

    def authorize():
        if api.calls:
            raise BridgeError("permission_denied", "revoked")

    with pytest.raises(UncertainExecution) as error:
        WindowsKeyboard(api).send(
            api.target, [KeyStroke(character="a"), KeyStroke(character="b")], before_send=authorize
        )
    assert error.value.provider_error["completed_keys"] == 1
    assert error.value.provider_error["cause_code"] == "permission_denied"
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(),
        dict(named="enter", character="a"),
        dict(named="fn"),
        dict(character="\ud800"),
        dict(unicode="x", modifiers=("control",)),
        dict(scan_code=True),
        dict(scan_code=128),
        dict(character="a", modifiers=("command",)),
        dict(character="a", modifiers=("shift", "shift")),
        dict(character="a", repeat=True),
        dict(character="a", extended=True),
    ],
)
def test_invalid_or_macos_specific_intents_are_rejected(kwargs):
    with pytest.raises(ValueError):
        KeyStroke(**kwargs)


def test_sequence_limit_counts_repeats():
    api = FakeWin32()
    with pytest.raises(ValueError):
        WindowsKeyboard(api).send(
            api.target, [KeyStroke(character="a", repeat=20), KeyStroke(character="b", repeat=13)]
        )
    assert not api.calls

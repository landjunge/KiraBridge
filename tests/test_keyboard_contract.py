"""Keyboard contracts and genuine long-payload/frame boundaries, without UI effects."""

import base64
import hashlib
import json

import pytest
from pydantic import ValidationError

from kirabridge.keyboard_models import (
    MAX_TEXT_UTF8_BYTES,
    KeyboardChordInput,
    KeyboardKeyInput,
    KeyboardTextInput,
)
from kirabridge.keyboard_text import native_frame_bytes, plan_text, utf16_chunks

TARGET = {
    "pid": 321,
    "expected_started_at": 1700000000.125,
    "target_token": "a" * 32,
    "helper_pid": 123,
    "worker_generation": "12345678-1234-1234-1234-123456789012",
    "expected_revision": "b" * 64,
}


@pytest.mark.parametrize(
    "text",
    [
        " /resume go-go-go \r\n",
        "äöü 日本語 e\u0301 👩‍💻 🇩🇪\n\t",
        "A" * MAX_TEXT_UTF8_BYTES,
        ('quote"\\\n😀e\u0301' * 20000),
    ],
    ids=["literal", "unicode", "one-mib", "multi-frame"],
)
def test_roundtrip_exact_text_and_complete_frame_budget(text):
    request = KeyboardTextInput(target=TARGET, text=text, submit=True)
    plan = plan_text(request, task_id="native-text-1", principal="ä" * 128)
    decoded = []
    for index, packet in enumerate(plan.chunks):
        frame = native_frame_bytes("keyboard.text.chunk", packet, principal="ä" * 128)
        assert len(frame) <= 65536
        assert json.loads(frame)["arguments"]["index"] == index
        raw = base64.b64decode(packet["data_b64"], validate=True)
        decoded.append(raw.decode("utf-16-le"))  # Each chunk independently valid.
        assert packet["transfer_id"] == plan.manifest["transfer_id"]
    assert "".join(decoded) == text
    assert plan.manifest["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert plan.manifest["utf8_bytes"] == len(text.encode())
    assert plan.manifest["utf16_units"] == len(text.encode("utf-16-le")) // 2
    assert plan.manifest["submit"] is True
    assert len(plan.chunks) <= 65


def test_surrogate_pair_at_transport_boundary_and_tiny_capacity():
    text = "A" * 16383 + "😀" + "B"
    chunks = utf16_chunks(text)
    assert chunks[0].decode("utf-16-le") == "A" * 16383
    assert chunks[1].decode("utf-16-le") == "😀B"
    assert [chunk.decode("utf-16-le") for chunk in utf16_chunks("A😀B", units=2)] == [
        "A",
        "😀",
        "B",
    ]
    with pytest.raises(ValueError):
        utf16_chunks("😀", units=1)


@pytest.mark.parametrize(
    "change",
    [
        {"submit": True},
        {"text": "changed"},
        {"target": {**TARGET, "pid": 322}},
    ],
)
def test_transfer_binding_changes_with_exact_intent(change):
    initial = {"target": TARGET, "text": "literal", "submit": False}
    a = plan_text(KeyboardTextInput(**initial), task_id="task-1", principal="alice")
    b = plan_text(KeyboardTextInput(**{**initial, **change}), task_id="task-1", principal="alice")
    assert a.manifest["transfer_id"] != b.manifest["transfer_id"]
    assert a.manifest["submit"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"submit": "true"},
        {"text": ""},
        {"text": "\ud800"},
        {"text": "\udc00"},
        {"text": "\0"},
        {"text": "a" * (MAX_TEXT_UTF8_BYTES + 1)},
        {"text": "😀" * (MAX_TEXT_UTF8_BYTES // 4 + 1)},
        {"target": {**TARGET, "pid": True}},
        {"target": {k: v for k, v in TARGET.items() if k != "worker_generation"}},
        {"clipboard": True},
    ],
)
def test_text_contract_refuses_invalid_or_mixed_intents(change):
    with pytest.raises(ValidationError):
        KeyboardTextInput(**{"target": TARGET, "text": "literal", **change})


@pytest.mark.parametrize(
    "key",
    [
        {},
        {"named": "enter", "character": "a"},
        {"key_code": True},
        {"key_code": 128},
        {"character": "\ud800"},
        {"character": "\n"},
        {"named": "power"},
    ],
)
def test_key_contract_refuses_ambiguous_or_unsupported_keys(key):
    with pytest.raises(ValidationError):
        KeyboardKeyInput(target=TARGET, key=key)


def test_key_and_chord_are_distinct_from_text_submit():
    assert KeyboardKeyInput(target=TARGET, key={"named": "enter"}).key.named == "enter"
    with pytest.raises(ValidationError):
        KeyboardKeyInput(target=TARGET, key={"named": "enter"}, submit=True)
    for modifiers in [[], ["command", "command"], ["super"]]:
        with pytest.raises(ValidationError):
            KeyboardChordInput(target=TARGET, key={"character": "z"}, modifiers=modifiers)
    chord = KeyboardChordInput(target=TARGET, key={"character": "z"}, modifiers=["command"])
    assert chord.key.character == "z"


@pytest.mark.parametrize("mutation", ["oversize", "submit", "target"])
def test_plan_revalidates_mutated_request(mutation):
    request = KeyboardTextInput(target=TARGET, text="literal")
    if mutation == "oversize":
        request.text = "x" * (MAX_TEXT_UTF8_BYTES + 1)
    elif mutation == "submit":
        request.submit = "true"
    else:
        request.target.pid = True
    with pytest.raises(ValidationError):
        plan_text(request, task_id="task-1", principal="alice")


def test_plan_revalidates_unchecked_model_copy():
    request = KeyboardTextInput(target=TARGET, text="literal").model_copy(update={"submit": "true"})
    with pytest.raises(ValidationError):
        plan_text(request, task_id="task-1", principal="alice")


def test_wire_dicts_cannot_change_the_approved_plan():
    plan = plan_text(
        KeyboardTextInput(target=TARGET, text="literal"), task_id="task-1", principal="a"
    )
    manifest, chunks = plan.manifest, plan.chunks
    manifest["submit"] = True
    manifest["target"]["pid"] = 999
    chunks[0]["data_b64"] = "changed"
    assert plan.manifest["submit"] is False
    assert plan.manifest["target"]["pid"] == TARGET["pid"]
    assert base64.b64decode(plan.chunks[0]["data_b64"]).decode("utf-16-le") == "literal"

"""Lossless staged-text packets; no clipboard, process, registry or event access."""

import base64
import hashlib
import json
from dataclasses import dataclass

from kirabridge.bridge_core.models import TaskRequest, canonical, digest
from kirabridge.keyboard_models import KeyboardTextInput

# UTF-16LE without BOM. These are transfer chunks, not CGEvent string boundaries.
CHUNK_UTF16_UNITS = 16384
MAX_NATIVE_FRAME_BYTES = 65536


def utf16_chunks(text: str, *, units: int = CHUNK_UTF16_UNITS) -> tuple[bytes, ...]:
    if type(units) is not int or not 2 <= units <= CHUNK_UTF16_UNITS:
        raise ValueError("Chunk capacity must hold at least one complete surrogate pair")
    raw = text.encode("utf-16-le")  # Strict encoding refuses isolated surrogates.
    chunks, offset = [], 0
    while offset < len(raw):
        end = min(len(raw), offset + units * 2)
        if end < len(raw) and 0xD800 <= int.from_bytes(raw[end - 2 : end], "little") <= 0xDBFF:
            end -= 2
        chunks.append(raw[offset:end])
        offset = end
    return tuple(chunks)


def native_frame_bytes(operation: str, arguments: dict, *, principal: str) -> bytes:
    """Use the existing transport's complete JSON envelope, including newline."""
    if not principal or len(principal.encode("utf-8")) > 256:
        raise ValueError("A bounded authenticated principal is required")
    raw = (
        json.dumps(
            {
                "protocol": 1,
                "revision": "system-v1:" + "0" * 40,
                "request_id": "0" * 32,
                "principal": principal,
                "operation": operation,
                "arguments": arguments,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if len(raw) > MAX_NATIVE_FRAME_BYTES:
        raise ValueError("Complete native frame exceeds 64 KiB")
    return raw


@dataclass(frozen=True)
class NativeTextPlan:
    """Staging proves payload integrity only; it grants no input or Return authority."""

    _manifest_json: str
    _chunks_json: tuple[str, ...]

    @property
    def manifest(self) -> dict:
        return json.loads(self._manifest_json)

    @property
    def chunks(self) -> tuple[dict, ...]:
        return tuple(json.loads(packet) for packet in self._chunks_json)


def plan_text(request: KeyboardTextInput, *, task_id: str, principal: str) -> NativeTextPlan:
    # Assignment/model_copy do not validate Input instances. Bind a fresh deep snapshot.
    request = KeyboardTextInput.model_validate(request.model_dump(warnings=False))
    # Reuse the established task-ID grammar without creating or submitting a task.
    TaskRequest(task_id=task_id, idempotency_key=task_id, operation="keyboard.text", arguments={})
    raw = request.text.encode("utf-8")
    chunks = utf16_chunks(request.text)
    binding = {
        "task_id": task_id,
        "principal": principal,
        "target": request.target.model_dump(),
        "submit": request.submit,
        "utf8_bytes": len(raw),
        "utf16_units": sum(map(len, chunks)) // 2,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "chunk_count": len(chunks),
        "encoding": "utf-16-le",
    }
    transfer_id = digest(binding)
    manifest = {"transfer_id": transfer_id, **binding}
    packets = tuple(
        {
            "transfer_id": transfer_id,
            "index": index,
            "data_b64": base64.b64encode(chunk).decode("ascii"),
        }
        for index, chunk in enumerate(chunks)
    )
    native_frame_bytes("keyboard.text.begin", manifest, principal=principal)
    for packet in packets:
        native_frame_bytes("keyboard.text.chunk", packet, principal=principal)
    return NativeTextPlan(canonical(manifest), tuple(canonical(packet) for packet in packets))

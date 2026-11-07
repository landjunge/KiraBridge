"""PNG screenshots retain metadata while validating bounded image payloads."""

import base64
import binascii
import hashlib
import struct
import zlib

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.filesystem_manager import PathScope
from kirabridge.image_manager import ImageManager, image_task_result, validate_png


def chunk(name: bytes, payload: bytes = b"") -> bytes:
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", binascii.crc32(name + payload) & 0xFFFFFFFF)
    )


def png(extra=(), after=()):
    # 1x1, 8-bit RGBA pixel with an unfiltered scanline.
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(bytes([0, 12, 34, 56, 255]))
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        [chunk(b"IHDR", header)]
        + list(extra)
        + [chunk(b"IDAT", pixels)]
        + list(after)
        + [chunk(b"IEND")]
    )


def test_png_metadata_preserved_byte_for_byte(tmp_path):
    metadata = (
        chunk(b"iCCP", b"macOS\x00\x00" + zlib.compress(b"profile data")),
        chunk(b"eXIf", b"Exif data"),
        chunk(b"iTXt", b"Title\x00\x00\x00\x00\x00original"),
        chunk(b"vpAg", b"private metadata"),
    )
    original = png(metadata, [chunk(b"tEXt", b"Author\x00User")])
    path = tmp_path / "real-metadata.png"
    path.write_bytes(original)

    assert validate_png(original) == (1, 1)
    result = ImageManager().read(PathScope([str(tmp_path)]), str(path))
    assert base64.b64decode(result["image_data"]) == original
    assert result["content_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["bytes"] == len(original)

    delivered = image_task_result(
        {"operation": "file.image", "state": "completed", "result": result}
    )
    images = [entry for entry in delivered.content if entry.type == "image"]
    assert len(images) == 1
    assert base64.b64decode(images[0].data) == original


def test_ancillary_metadata_does_not_disable_pixel_safety():
    valid = png([chunk(b"iTXt", b"payload")])
    damaged = valid.replace(b"payload", b"payl0ad")
    with pytest.raises(BridgeError) as exception:
        validate_png(damaged)
    assert exception.value.code == "image_invalid"

    with pytest.raises(BridgeError) as exception:
        validate_png(png([chunk(b"ABCD", b"unknown critical")]))
    assert exception.value.code == "image_invalid"

    with pytest.raises(BridgeError) as exception:
        validate_png(png([chunk(b"vpag", b"invalid reserved bit")]))
    assert exception.value.code == "image_invalid"


def test_reject_interrupted_image_stream():
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    full = zlib.compress(bytes([0, 12, 34, 56, 255]))
    invalid = (
        b"\x89PNG\r\n\x1a\n"
        + header
        + chunk(b"IDAT", full[:4])
        + chunk(b"eXIf", b"metadata")
        + chunk(b"IDAT", full[4:])
        + chunk(b"IEND")
    )
    with pytest.raises(BridgeError) as exception:
        validate_png(invalid)
    assert exception.value.code == "image_invalid"

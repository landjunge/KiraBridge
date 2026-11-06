"""Layout-independent Windows Unicode text as explicit VK_PACKET strokes.

Newlines become Enter and tabs become Tab. No other ASCII control is inserted.
Characters are not normalized, and nothing is placed on the clipboard. This is
not the macOS staged 1 MiB helper.
"""

from __future__ import annotations

from kirabridge.platform_adapters.windows.keyboard import MAX_KEYS, KeyStroke

TEXT_UTF8_BYTES = 4096
TEXT_STROKES = 512


def text_strokes(text: str) -> tuple[KeyStroke, ...]:
    """One stroke per scalar, with CRLF counted as a single Enter."""
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("Windows text must be a Unicode string without NUL")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        raw = normalized.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Windows text must contain valid Unicode scalars") from None
    if not raw or len(raw) > TEXT_UTF8_BYTES:
        raise ValueError("Windows text must contain between 1 and 4096 UTF-8 bytes")
    strokes = []
    for char in normalized:
        if char == "\n":
            strokes.append(KeyStroke(named="enter"))
        elif char == "\t":
            strokes.append(KeyStroke(named="tab"))
        elif ord(char) < 32 or ord(char) == 127:
            raise ValueError("Windows text allows tab and line breaks only as Enter or Tab")
        else:
            strokes.append(KeyStroke(unicode=char))
    if not strokes or len(strokes) > TEXT_STROKES:
        raise ValueError("Windows text must contain between 1 and 512 strokes")
    return tuple(strokes)


def text_batches(text: str) -> tuple[tuple[KeyStroke, ...], ...]:
    """Split into the existing 32-key SendInput batches without dropping a stroke."""
    strokes, batches, current = text_strokes(text), [], []
    for stroke in strokes:
        if len(current) == MAX_KEYS:
            batches.append(tuple(current))
            current = []
        current.append(stroke)
    if current:
        batches.append(tuple(current))
    return tuple(batches)

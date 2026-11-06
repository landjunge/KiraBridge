"""Exact single-row Grok paste proof; preserves boxed footer and all adjacent rows."""

import json
import re

from ._legacy_readiness import display_text, input_view


def single_line_payload(text):
    # Padding and payload edge spaces are visually indistinguishable. Wrapped,
    # multiline and non-ASCII rendering need separate geometry-aware evidence.
    return bool(text and text == text.strip(" ") and re.fullmatch(r"[ -~]+", text))


def single_row_capacity(raw):
    cleaned, controls = display_text(raw)
    rows = input_view("grok", cleaned).splitlines()
    if controls or len(rows) < 3 or not re.fullmatch(r"╭─+╮ *", rows[0]):
        return None
    match = re.fullmatch(r" *│ *❯ ( *)│ *", rows[1])
    if match is None or not re.fullmatch(r" *╰─+ Grok [^\n]+ ─╯ *", rows[2]):
        return None
    return len(match[1])


def insertion_observed(raw, text, before):
    if not single_line_payload(text):
        return False
    previous, old_controls = display_text(before)
    current, controls = display_text(raw)
    if controls or old_controls:
        return False
    old, new = input_view("grok", previous), input_view("grok", current)
    lines = old.splitlines(keepends=True)
    if len(lines) < 3 or not re.fullmatch(r"╭─+╮ *\n", lines[0]):
        return False
    match = re.fullmatch(r"( *│ *❯ )( *)│ *(\n)", lines[1])
    if match is None or len(text) > len(match[2]):
        return False
    if not re.fullmatch(r" *╰[^\n]*╯ *(?:\n)?", lines[2]):
        return False
    # Replace only the known empty body cells. The same title-bearing bottom
    # border, shortcut rows, padding, and top border must remain byte-for-byte.
    start = len(lines[0]) + match.start(2)
    expected = old[:start] + text + old[start + len(text) :]
    return new == expected


def paste_source(text):
    if not single_line_payload(text):
        return None
    return (
        "\nfunction observedPaste(before, after) {"
        "const oldStart=before.lastIndexOf('╭'), newStart=after.lastIndexOf('╭');"
        "if(oldStart<0||newStart<0) return false;"
        "const old=before.slice(oldStart), current=after.slice(newStart);"
        "const rows=old.split('\\n');"
        "if(rows.length<3||!/^╭─+╮ *$/.test(rows[0])||"
        "!/^ *╰[^\\n]*╯ *$/.test(rows[2]))return false;"
        "const match=/^( *│ *❯ )( *)│ *$/.exec(rows[1]);"
        "const payload=" + json.dumps(text) + ";"
        "if(!match||payload.length>match[2].length)return false;"
        "const start=rows[0].length+1+match[1].length;"
        "return current===old.slice(0,start)+payload+old.slice(start+payload.length);}\n"
    )

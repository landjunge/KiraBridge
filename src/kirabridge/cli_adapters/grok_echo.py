"""Exact single-row Grok paste proof; preserves boxed footer and all adjacent rows."""

import json
import re

from ._legacy_readiness import GROK_PLACEHOLDERS, display_text, input_view


def single_line_payload(text):
    # Padding and payload edge spaces are visually indistinguishable.
    return bool(text and text == text.strip(" ") and re.fullmatch(r"[ -~]+", text))


def _compact(text):
    return re.sub(r"[\s\u00a0]+", "", text)


def _placeholder(text):
    """An empty composer, including Grok's rendered placeholder text."""
    compact = _compact(text)
    return not compact or compact in {_compact(item) for item in GROK_PLACEHOLDERS}


def verifiable_payload(text):
    # Edge spaces remain ambiguous. Newlines and other visible characters can
    # be proven from the composer cells alone.
    return bool(
        text and text == text.strip(" ") and not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text)
    )


def single_row_capacity(raw):
    cleaned, controls = display_text(raw)
    rows = input_view("grok", cleaned).splitlines()
    if controls or len(rows) < 3 or not re.fullmatch(r"╭─+╮ *", rows[0]):
        return None
    match = re.fullmatch(r" *│ *❯ (.*?)│ *", rows[1])
    if (
        match is None
        or not _placeholder(match[1])
        or not re.fullmatch(r" *╰─+ Grok [^\n]+ ─╯ *", rows[2])
    ):
        return None
    return len(match[1])


def _box(view):
    lines = view.splitlines()
    if len(lines) < 3 or not re.fullmatch(r"╭─+╮ *", lines[0]):
        return None
    end = next(
        (index for index, line in enumerate(lines) if index and re.match(r" *╰", line)),
        None,
    )
    if end is None or end < 2 or not re.fullmatch(r" *╰─+ .*─╯ *", lines[end]):
        return None
    return lines[: end + 1], lines[end + 1 :]


def _composer_cells(box):
    cells = []
    for index, line in enumerate(box[1:-1]):
        match = re.fullmatch(r" *│(.*)│ *", line)
        if match is None:
            return None
        cell = match.group(1)
        if index == 0:
            if not re.match(r" *❯ ", cell):
                return None
            cell = re.sub(r"^ *❯ ", "", cell, count=1)
        cells.append(cell)
    return cells


def insertion_observed(raw, text, before):
    if not verifiable_payload(text):
        return False
    previous, old_controls = display_text(before)
    current, controls = display_text(raw)
    if controls or old_controls:
        return False
    old, new = input_view("grok", previous), input_view("grok", current)
    lines = old.splitlines(keepends=True)
    if len(lines) < 3 or not re.fullmatch(r"╭─+╮ *\n", lines[0]):
        return False
    match = re.fullmatch(r"( *│ *❯ )(.*?)(│ *\n)", lines[1])
    if (
        match is not None
        and len(text) <= len(match[2])
        and _placeholder(match[2])
        and re.fullmatch(r" *╰[^\n]*╯ *(?:\n)?", lines[2])
    ):
        # Replace only the known empty/placeholder body cells. The same
        # title-bearing bottom border, shortcut rows, padding, and top border
        # must remain byte-for-byte. The empty placeholder leaves the cell
        # layout intact, so the inserted text keeps the same right border.
        start = len(lines[0]) + match.start(2)
        padded = text + " " * (len(match[2]) - len(text))
        expected = old[:start] + padded + old[start + len(match[2]) :]
        if new == expected:
            return True
    # Longer and multiline text is proven only from the composer cells. Text
    # above the box, including older quoted work, does not count.
    old_box, old_tail = _box(old) or (None, None)
    new_box, new_tail = _box(new) or (None, None)
    if old_box is None or new_box is None or old_tail != new_tail:
        return False
    if old_box[0] != new_box[0] or old_box[-1] != new_box[-1]:
        return False
    old_cells, new_cells = _composer_cells(old_box), _composer_cells(new_box)
    if old_cells is None or new_cells is None or not _placeholder("".join(old_cells)):
        return False
    return _compact("".join(new_cells)) == _compact(text)


def _paste_helpers(text):
    return (
        "const boxContent=s=>{const i=s.lastIndexOf('╭'); if(i<0)return '';"
        "const rows=s.slice(i).split('\\n');"
        "const end=rows.findIndex((row,index)=>index&&/^ *╰/.test(row));"
        "if(end<2)return '';"
        "return rows.slice(1,end).map((row,index)=>{"
        "let cell=row.replace(/^ *│/,'').replace(/│ *$/,'');"
        "if(index===0)cell=cell.replace(/^\\s*❯ ?/,'');"
        "return cell;}).join('');};"
        "const compact=s=>s.replace(/[\\s\\u00a0]/g,'');"
        "const placeholders=" + json.dumps([_compact(item) for item in GROK_PLACEHOLDERS]) + ";"
        "const emptyContent=s=>{const c=compact(s);"
        "return c.length===0||placeholders.includes(c);};"
        "const payload=compact(" + json.dumps(text) + ");"
    )


def paste_source(text):
    if not verifiable_payload(text):
        return None
    if not single_line_payload(text):
        return (
            "\nfunction observedPaste(before, after) {"
            + _paste_helpers(text)
            + "const old=compact(boxContent(before)), current=compact(boxContent(after));"
            "return payload.length>0 && emptyContent(old) && current===payload;}\n"
        )
    return (
        "\nfunction observedPaste(before, after) {"
        + _paste_helpers(text)
        + "const oldStart=before.lastIndexOf('╭'), newStart=after.lastIndexOf('╭');"
        "if(oldStart<0||newStart<0) return false;"
        "const old=before.slice(oldStart), current=after.slice(newStart);"
        "const rows=old.split('\\n');"
        "if(rows.length<3||!/^╭─+╮ *$/.test(rows[0])||"
        "!/^ *╰[^\\n]*╯ *$/.test(rows[2]))return false;"
        "const match=/^( *│ *❯ )(.*?)(│ *)$/.exec(rows[1]);"
        "const rawPayload=" + json.dumps(text) + ";"
        "if(match&&rawPayload.length<=match[2].length){"
        "const cells=match[2], text=cells.trim();"
        "if(text!==''&&!" + json.dumps(list(GROK_PLACEHOLDERS)) + ".includes(text))return false;"
        "const start=rows[0].length+1+match[1].length;"
        "const padded=rawPayload+' '.repeat(cells.length-rawPayload.length);"
        "return current===old.slice(0,start)+padded+old.slice(start+cells.length);}"
        # A payload longer than one row wraps in the box. The exact payload is
        # proven from the composer cells; the whole-widget check above remains
        # authoritative for the single-row case.
        "const oldContent=compact(boxContent(before)), newContent=compact(boxContent(after));"
        "return payload.length>0 && emptyContent(oldContent) && newContent===payload;}\n"
    )
